#!/usr/bin/env python3
"""Shared Jarvis functions — imported by check_audio.py, check_text.py, and check_amazon.py."""

import os
import sys
import json
import asyncio
import subprocess
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path

# Fix stdout for unicode
if sys.stdout.encoding != 'utf-8':
    sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', closefd=False)

# ── Credentials & defaults ────────────────────────────────────────────────────
WHATSAPP_TARGET       = os.environ.get("WHATSAPP_TARGET", "")         # Your WhatsApp number
GATEWAY_TOKEN         = os.environ.get("GATEWAY_TOKEN", "")           # From openclaw.json → gateway.token
DEFAULT_LOCATION      = os.environ.get("DEFAULT_LOCATION", "10001")   # ZIP code or city name
DEFAULT_LOCATION_NAME = os.environ.get("DEFAULT_LOCATION_NAME", "New York")  # Human-readable city name

GROQ_API_KEY          = os.environ.get("GROQ_API_KEY", "")            # From console.groq.com
GROQ_MODEL            = "llama-3.3-70b-versatile"

USDA_API_KEY          = os.environ.get("USDA_API_KEY", "")            # From api.nal.usda.gov

# ── Weather codes ─────────────────────────────────────────────────────────────
WEATHER_CODES = {
    0: "Clear sky ☀️", 1: "Mainly clear 🌤️", 2: "Partly cloudy ⛅", 3: "Overcast ☁️",
    45: "Foggy 🌫️", 48: "Icy fog 🌫️",
    51: "Light drizzle 🌦️", 53: "Drizzle 🌦️", 55: "Heavy drizzle 🌧️",
    61: "Light rain 🌧️", 63: "Rain 🌧️", 65: "Heavy rain 🌧️",
    71: "Light snow 🌨️", 73: "Snow 🌨️", 75: "Heavy snow ❄️", 77: "Snow grains ❄️",
    80: "Showers 🌦️", 81: "Heavy showers 🌧️", 82: "Violent showers ⛈️",
    85: "Snow showers 🌨️", 86: "Heavy snow showers ❄️",
    95: "Thunderstorm ⛈️", 96: "Thunderstorm w/ hail ⛈️", 99: "Thunderstorm w/ hail ⛈️",
}

WEATHER_KEYWORDS = {"weather", "temperature", "forecast", "rain", "snow", "sunny",
                    "cold", "hot", "warm", "humid", "wind", "storm", "cloudy", "degrees",
                    "umbrella", "jacket", "coat", "raincoat", "outside", "outdoors",
                    "outdoor", "raining", "freezing", "chilly"}

TIME_KEYWORDS = {"time", "clock", "timezone", "o'clock"}

EMAIL_KEYWORDS = {"email", "emails", "mail", "inbox", "amazon", "order", "orders",
                  "shipment", "delivery", "package"}

CALENDAR_KEYWORDS = {"calendar", "calender", "schedule", "meeting", "appointment", "appointments",
                     "agenda", "plans", "events", "busy", "free", "availability"}

# ── Keyword detectors ─────────────────────────────────────────────────────────
def is_weather_question(text):
    words = set(text.lower().split())
    return bool(words & WEATHER_KEYWORDS)

def is_time_question(text):
    text_lower = text.lower()
    words = set(text_lower.split())
    # Require a time word AND a location indicator ("in"/"at") to avoid matching
    # things like "what time is the meeting" which have no location.
    has_time_word = bool(words & TIME_KEYWORDS)
    has_location = " in " in f" {text_lower} " or " at " in f" {text_lower} "
    return has_time_word and has_location

def is_email_question(text):
    words = set(text.lower().split())
    return bool(words & EMAIL_KEYWORDS)

def is_calendar_question(text):
    words = set(text.lower().split())
    return bool(words & CALENDAR_KEYWORDS)

_CALENDAR_CREATE_KEYWORDS = {
    "create", "add", "schedule", "set", "book", "make", "put", "place"
}
_CALENDAR_CREATE_CONTEXT = {
    "event", "meeting", "appointment", "lunch", "dinner",
    "breakfast", "call", "interview", "session"
}

def is_calendar_create_question(text):
    tl = text.lower()
    words = set(tl.split())
    has_create = bool(words & _CALENDAR_CREATE_KEYWORDS)
    has_context = bool(words & _CALENDAR_CREATE_CONTEXT) or any(
        w in tl for w in ("tomorrow", "monday", "tuesday", "wednesday",
                           "thursday", "friday", "saturday", "sunday",
                           "next week", " am", " pm")
    )
    return has_create and has_context

def is_reminder_question(text):
    tl = text.lower()
    return "remind" in tl or "remember to" in tl or "don't forget" in tl or "dont forget" in tl

# ── Reminders ─────────────────────────────────────────────────────────────────
REMINDERS_FILE = Path(os.environ.get("USERPROFILE", ".")) / ".openclaw" / "workspace" / "reminders.json"

def parse_reminder_groq(text):
    """Use Groq to extract task + datetime from natural language. Returns (task, iso_str) or None."""
    import urllib.request, urllib.error, json as _json
    from datetime import datetime as _dt
    now = _dt.now()
    system = (
        "You are a reminder time parser. Extract the task and time from a reminder request. "
        "Return ONLY valid JSON: {\"task\": \"brief task\", \"remind_at\": \"YYYY-MM-DDTHH:MM:00\"} "
        "Use 24-hour time. If no date mentioned, assume today. "
        "If only an hour is given (e.g. 'at 9'), pick AM or PM based on current time. "
        "Return null if no clear time is found."
    )
    user_msg = (
        f"Today is {now.strftime('%Y-%m-%d')}, current time is {now.strftime('%H:%M')}. "
        f"Parse this reminder request: \"{text}\""
    )
    payload = _json.dumps({
        "model": GROQ_MODEL,
        "messages": [{"role": "system", "content": system},
                     {"role": "user",   "content": user_msg}],
        "max_tokens": 80,
        "temperature": 0,
    }).encode("utf-8")
    try:
        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {GROQ_API_KEY}"},
        )
        resp = urllib.request.urlopen(req, timeout=15)
        content = _json.loads(resp.read())["choices"][0]["message"]["content"].strip()
        s, e = content.find("{"), content.rfind("}") + 1
        if s >= 0 and e > s:
            parsed = _json.loads(content[s:e])
            task = parsed.get("task", "").strip()
            remind_at = parsed.get("remind_at", "").strip()
            if task and remind_at:
                return task, remind_at
    except Exception as ex:
        print(f"Reminder parse error: {ex}")
    return None

def save_reminder(task, remind_at_iso):
    """Append a new reminder to reminders.json."""
    import uuid
    try:
        reminders = json.loads(REMINDERS_FILE.read_text()) if REMINDERS_FILE.exists() else []
    except Exception:
        reminders = []
    reminders.append({"id": str(uuid.uuid4())[:8], "task": task,
                      "remind_at": remind_at_iso, "sent": False})
    REMINDERS_FILE.write_text(json.dumps(reminders, indent=2))

def check_due_reminders():
    """Fire any reminders whose time has passed. Returns list of fired task strings."""
    if not REMINDERS_FILE.exists():
        return []
    try:
        reminders = json.loads(REMINDERS_FILE.read_text())
    except Exception:
        return []
    from datetime import datetime as _dt
    now = _dt.now()
    fired = []
    for r in reminders:
        if r.get("sent") or not r.get("remind_at"):
            continue
        try:
            if now >= _dt.fromisoformat(r["remind_at"]):
                send_whatsapp(f"📌 Reminder: {r['task']}, sir.")
                r["sent"] = True
                fired.append(r["task"])
        except Exception:
            pass
    # Drop sent reminders from yesterday or earlier
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    reminders = [r for r in reminders
                 if not r.get("sent") or _dt.fromisoformat(r["remind_at"]) >= today_start]
    REMINDERS_FILE.write_text(json.dumps(reminders, indent=2))
    return fired

# ── Geocoding & weather ───────────────────────────────────────────────────────
CITY_PREFIXES = ["new", "san", "los", "las", "el", "st", "fort", "port",
                 "north", "south", "east", "west"]

def _normalize_city(search):
    """Insert a space after common city-name prefixes when the user types them
    as one word (e.g. 'new york' or 'san francisco' typed without a space)."""
    if " " in search:
        return search
    lower = search.lower()
    for prefix in CITY_PREFIXES:
        if lower.startswith(prefix) and len(lower) > len(prefix):
            return search[:len(prefix)] + " " + search[len(prefix):]
    return search

def geocode(search):
    """Return the best-matching geocoding result, or None."""
    search = _normalize_city(search)
    geo_url = (f"https://geocoding-api.open-meteo.com/v1/search"
               f"?name={urllib.parse.quote(search)}&count=5&language=en&format=json")
    geo = json.loads(urllib.request.urlopen(geo_url, timeout=8).read())
    results = geo.get("results")
    if not results:
        return None
    # Log all candidates so we can debug wrong-city picks
    for i, r in enumerate(results):
        print(f"  geocode[{i}]: {r.get('name')}, {r.get('admin1')}, {r.get('country')} pop={r.get('population')}")
    # Combine population with API rank (rank 0 = best text match from the geocoding API).
    # Without the rank bonus, cities with missing population data (e.g. NYC returns
    # population=null) lose to tiny obscure towns that have a population value set.
    rank_bonus = [50_000, 25_000, 10_000, 5_000, 1_000]
    scored = [(r.get("population") or 0) + rank_bonus[i] for i, r in enumerate(results)]
    best = results[scored.index(max(scored))]
    print(f"  geocode winner: {best.get('name')}, {best.get('admin1')}, {best.get('country')} score={max(scored)}")
    return best

def fetch_weather(location=None):
    """Fetch weather from open-meteo. Returns formatted string or None."""
    loc_name = location or DEFAULT_LOCATION_NAME
    search = location or DEFAULT_LOCATION
    try:
        # Geocode the location
        r = geocode(search)
        if not r:
            return None
        lat, lon = r["latitude"], r["longitude"]
        loc_name = r.get("name", loc_name)
        admin = r.get("admin1", "")
        if admin:
            loc_name = f"{loc_name}, {admin}"

        # Fetch current conditions + hourly precipitation + 2-day daily forecast
        wx_url = (f"https://api.open-meteo.com/v1/forecast"
                  f"?latitude={lat}&longitude={lon}"
                  f"&current_weather=true&temperature_unit=fahrenheit&windspeed_unit=mph"
                  f"&hourly=precipitation_probability&forecast_days=2"
                  f"&daily=weathercode,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
                  f"&timezone=America%2FLos_Angeles")
        wx = json.loads(urllib.request.urlopen(wx_url, timeout=8).read())
        cw = wx["current_weather"]
        desc = WEATHER_CODES.get(int(cw["weathercode"]), "Unknown")
        current_line = f"{loc_name}: {desc}, {cw['temperature']}°F, wind {cw['windspeed']} mph"

        # Build hourly rain chance string for today (every 2 hours, 8am–8pm)
        hourly = wx.get("hourly", {})
        times = hourly.get("time", [])
        probs = hourly.get("precipitation_probability", [])
        today_str = times[0][:10] if times else ""
        slots = []
        for t, p in zip(times, probs):
            if p is None or t[:10] != today_str:
                continue
            hour_str = t[11:16]  # "HH:MM"
            h = int(hour_str[:2])
            if 8 <= h <= 20 and h % 2 == 0:
                label = f"{h if h <= 12 else h - 12}{'am' if h < 12 else 'pm'}"
                slots.append(f"{label} {p}%")

        # Build tomorrow's daily summary
        daily = wx.get("daily", {})
        daily_dates = daily.get("time", [])
        tomorrow_line = ""
        if len(daily_dates) >= 2:
            tmr_code = daily.get("weathercode", [None, None])[1]
            tmr_max = daily.get("temperature_2m_max", [None, None])[1]
            tmr_min = daily.get("temperature_2m_min", [None, None])[1]
            tmr_rain = daily.get("precipitation_probability_max", [None, None])[1]
            tmr_desc = WEATHER_CODES.get(int(tmr_code), "Unknown") if tmr_code is not None else "Unknown"
            tomorrow_line = (f"Tomorrow ({daily_dates[1]}): {tmr_desc}, "
                             f"high {tmr_max}°F, low {tmr_min}°F, rain {tmr_rain}%")

        result = current_line
        if slots:
            result += "\nToday rain chance: " + " | ".join(slots)
        if tomorrow_line:
            result += "\n" + tomorrow_line
        return result
    except Exception as e:
        print(f"Weather fetch error: {e}")
        return None

# ── Time ──────────────────────────────────────────────────────────────────────
def fetch_time(location=None):
    """Fetch current local time for a city using open-meteo geocoding + zoneinfo."""
    from zoneinfo import ZoneInfo
    from datetime import datetime

    search = location or DEFAULT_LOCATION
    loc_display = location or DEFAULT_LOCATION_NAME
    try:
        r = geocode(search)
        if not r:
            return None
        lat, lon = r["latitude"], r["longitude"]
        loc_display = r.get("name", loc_display)
        admin = r.get("admin1", "")
        if admin:
            loc_display = f"{loc_display}, {admin}"

        # open-meteo returns timezone name (e.g. "Asia/Kolkata") when timezone=auto
        tz_url = (f"https://api.open-meteo.com/v1/forecast"
                  f"?latitude={lat}&longitude={lon}&timezone=auto&forecast_days=1")
        tz_data = json.loads(urllib.request.urlopen(tz_url, timeout=8).read())
        tz_name = tz_data.get("timezone")
        if not tz_name:
            return None

        now = datetime.now(ZoneInfo(tz_name))
        time_str = now.strftime("%I:%M %p").lstrip("0")   # "7:54 AM"
        day_str  = now.strftime("%A, %b %d")               # "Thursday, Feb 27"
        tz_abbr  = now.strftime("%Z")                      # "IST"
        return f"{loc_display}: {time_str} ({day_str}) [{tz_abbr}]"
    except Exception as e:
        print(f"Timezone fetch error: {e}")
        return None

# ── Nearby places (Overpass / OpenStreetMap) ─────────────────────────────────
_DAY_MAP = {"Mo": "Mon", "Tu": "Tue", "We": "Wed", "Th": "Thu",
            "Fr": "Fri", "Sa": "Sat", "Su": "Sun", "PH": "Holidays"}

def _fmt_time(t):
    """'09:00' → '9am', '21:30' → '9:30pm', '00:00' → '12am'"""
    try:
        h, m = int(t[:2]), int(t[3:5])
        if h == 0:    base = "12am"
        elif h < 12:  base = f"{h}am"
        elif h == 12: base = "12pm"
        else:         base = f"{h - 12}pm"
        return base if m == 0 else base[:-2] + f":{m:02d}" + base[-2:]
    except Exception:
        return t

def _fmt_days(d):
    """'Mo-Fr' → 'Mon–Fri', 'Sa' → 'Sat'"""
    if "-" in d:
        a, b = d.split("-", 1)
        return f"{_DAY_MAP.get(a, a)}–{_DAY_MAP.get(b, b)}"
    return _DAY_MAP.get(d, d)

def _format_osm_hours(raw):
    """Convert OSM opening_hours to readable form.
    'Mo-Fr 09:00-21:00; Sa-Su 10:00-18:00' → 'Mon–Fri 9am–9pm, Sat–Sun 10am–6pm'
    """
    if not raw:
        return ""
    if raw.strip() == "24/7":
        return "Open 24/7"
    try:
        parts = []
        for segment in raw.split(";"):
            segment = segment.strip()
            if not segment:
                continue
            tokens = segment.split(None, 1)
            if len(tokens) == 2:
                days = _fmt_days(tokens[0])
                spans = []
                for span in tokens[1].split(","):
                    span = span.strip()
                    if "-" in span:
                        t1, t2 = span.split("-", 1)
                        spans.append(f"{_fmt_time(t1.strip())}–{_fmt_time(t2.strip())}")
                    else:
                        spans.append(span)
                parts.append(f"{days} {', '.join(spans)}")
            else:
                parts.append(segment)
        return "; ".join(parts) if parts else raw
    except Exception:
        return raw


def fetch_nearby(user_query, location=None):
    """Find nearby places using Overpass API (OpenStreetMap).
    Returns formatted string of results, 'no_places_found', or None on error.
    """
    import math, json as _j

    # 1. Use Groq to extract amenity type + optional cuisine from the query
    extract_system = (
        "Extract the place type from the user query. Reply with ONLY valid JSON, no other text.\n"
        "Format: {\"amenity\": \"osm_amenity_value\", \"cuisine\": \"cuisine_or_null\"}\n"
        "amenity must be one of: restaurant, cafe, bar, pub, pharmacy, hospital, "
        "supermarket, atm, bank, fuel, parking, hotel, gym, fast_food, cinema, library\n"
        "cuisine: for restaurants/cafes only — italian, chinese, japanese, indian, "
        "mexican, thai, american, pizza, sushi, etc. or null"
    )
    amenity = "restaurant"
    cuisine = None
    try:
        payload = _j.dumps({
            "model": "llama-3.1-8b-instant",
            "messages": [
                {"role": "system", "content": extract_system},
                {"role": "user",   "content": user_query},
            ],
            "max_tokens": 60,
            "temperature": 0,
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            },
        )
        raw = _j.loads(urllib.request.urlopen(req, timeout=10).read())["choices"][0]["message"]["content"].strip()
        parsed = _j.loads(raw)
        amenity = parsed.get("amenity", "restaurant").strip()
        cuisine = parsed.get("cuisine") or None
        print(f"nearby: amenity={amenity}, cuisine={cuisine}")
    except Exception as e:
        print(f"nearby: Groq extract error: {e} — defaulting to restaurant")

    # 2. Geocode location
    r = geocode(location or DEFAULT_LOCATION)
    if not r:
        return None
    lat, lon = r["latitude"], r["longitude"]
    loc_name = r.get("name", location or DEFAULT_LOCATION_NAME)
    admin = r.get("admin1", "")
    if admin:
        loc_name = f"{loc_name}, {admin}"

    # 3. Build and run Overpass query (nodes + ways, 5 km radius, up to 10 results)
    cuisine_filter = f'[cuisine={cuisine}]' if cuisine else ""
    oq = (
        f'[out:json][timeout:15];'
        f'(node[amenity={amenity}]{cuisine_filter}(around:5000,{lat},{lon});'
        f'way[amenity={amenity}]{cuisine_filter}(around:5000,{lat},{lon}););'
        f'out center 10;'
    )
    try:
        req = urllib.request.Request(
            "https://overpass-api.de/api/interpreter",
            data=urllib.parse.urlencode({"data": oq}).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     "User-Agent": "JarvisBot/1.0"},
        )
        data = _j.loads(urllib.request.urlopen(req, timeout=20).read())
    except Exception as e:
        print(f"Overpass error: {e}")
        return None

    elements = data.get("elements", [])
    if not elements:
        return "no_places_found"

    # 4. Format results with distance
    def _dist_mi(la, lo):
        dlat = math.radians(la - lat)
        dlon = math.radians(lo - lon)
        a = math.sin(dlat/2)**2 + math.cos(math.radians(lat)) * math.cos(math.radians(la)) * math.sin(dlon/2)**2
        return 3958.8 * 2 * math.asin(math.sqrt(a))

    lines = []
    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name") or tags.get("brand")
        if not name:
            continue
        el_lat = el.get("lat") or (el.get("center") or {}).get("lat")
        el_lon = el.get("lon") or (el.get("center") or {}).get("lon")
        dist = f"{_dist_mi(el_lat, el_lon):.1f}mi" if el_lat and el_lon else ""
        detail = []
        if tags.get("cuisine"):
            detail.append(tags["cuisine"])
        addr = " ".join(p for p in [tags.get("addr:housenumber", ""), tags.get("addr:street", "")] if p)
        if addr:
            detail.append(addr)
        if tags.get("opening_hours"):
            detail.append(_format_osm_hours(tags["opening_hours"]))
        if dist:
            detail.append(dist)
        line = f"• {name}"
        if detail:
            line += f" — {', '.join(detail[:3])}"
        lines.append(line)
        if len(lines) == 3:
            break

    if not lines:
        return "no_places_found"

    label = f"{cuisine} {amenity}" if cuisine else amenity
    return f"Nearby {label}s near {loc_name}:\n" + "\n".join(lines)


# ── Gmail (Zapier MCP) ────────────────────────────────────────────────────────
def fetch_gmail_zapier(instructions=None):
    """Fetch Gmail emails via Zapier MCP. Returns formatted string or None.
    Requires a Gmail AI Action added at zapier.com/ai-actions.
    """
    try:
        cfg = json.loads(_ZAPIER_MCP_CFG.read_text())
        mcp_url = cfg["mcpServers"]["zapier"]["baseUrl"]
    except Exception as e:
        print(f"Zapier config error: {e}")
        return None

    def zapier_rpc(method, params, req_id=None):
        body = {"jsonrpc": "2.0", "method": method, "params": params}
        if req_id is not None:
            body["id"] = req_id
        req = urllib.request.Request(
            mcp_url,
            data=json.dumps(body).encode(),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            }
        )
        resp = urllib.request.urlopen(req, timeout=45)
        raw = resp.read().decode("utf-8")
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                try:
                    msg = json.loads(line[5:].strip())
                    if "result" in msg or "error" in msg:
                        return msg
                except Exception:
                    pass
        return None

    try:
        # 1. Initialize
        init_r = zapier_rpc("initialize", {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "jarvis", "version": "1.0"},
        }, req_id=1)
        if not init_r:
            print("Zapier: no initialize response")
            return None

        # 2. Notify initialized
        try:
            zapier_rpc("notifications/initialized", {})
        except Exception:
            pass

        # 3. List tools
        list_r = zapier_rpc("tools/list", {}, req_id=2)
        if not list_r:
            print("Zapier: no tools/list response")
            return None
        tools = list_r.get("result", {}).get("tools", [])
        print(f"Zapier tools (email): {[t.get('name') for t in tools]}")

        # 4. Find best Gmail/email tool
        def _score(t):
            n = t.get("name", "").lower()
            if "gmail" in n and "find" in n:
                return 4
            if "gmail" in n and "search" in n:
                return 3
            if "gmail" in n:
                return 2
            if ("email" in n or "mail" in n) and ("find" in n or "search" in n or "read" in n):
                return 1
            return 0
        email_tools = sorted([t for t in tools if _score(t) > 0], key=_score, reverse=True)
        if not email_tools:
            print("No Gmail tool found in Zapier. Add 'Gmail: Find Email' at zapier.com/ai-actions.")
            return None
        email_tool = email_tools[0]
        print(f"Using email tool: {email_tool['name']}")

        # 5. Build args
        from datetime import datetime as _dt_local
        today_human = _dt_local.now().strftime("%B %d, %Y")
        query = instructions or f"Find emails from today, {today_human}. Return up to 5 most recent."

        props = email_tool.get("inputSchema", {}).get("properties", {})
        args = {}
        for key in props:
            kl = key.lower()
            if any(w in kl for w in ("instructions", "query", "search", "input", "text")):
                args[key] = query
                break
        if not args and props:
            args[next(iter(props))] = query

        print(f"Calling {email_tool['name']} args={args}")
        call_r = zapier_rpc("tools/call", {
            "name": email_tool["name"],
            "arguments": args,
        }, req_id=3)
        if not call_r:
            print("Zapier: no tools/call response for email")
            return None

        content = call_r.get("result", {}).get("content", [])
        raw_text = next(
            (item["text"] for item in content
             if isinstance(item, dict) and item.get("type") == "text" and item.get("text")),
            None
        )
        if not raw_text:
            print("Zapier: empty content in email tools/call response")
            return None

        # Try to parse and format structured results
        try:
            data = json.loads(raw_text)
            results = data.get("results", [])
            if isinstance(results, dict):
                results = [results]
            if results:
                lines = []
                for em in results[:5]:
                    if not isinstance(em, dict):
                        continue
                    subject = em.get("subject") or em.get("Subject") or "(no subject)"
                    sender = em.get("from") or em.get("From") or em.get("sender") or ""
                    parts = [subject]
                    if sender:
                        parts.append(f"From: {sender}")
                    lines.append("• " + " | ".join(parts))
                if lines:
                    return f"{len(results)} email(s):\n" + "\n".join(lines)
            else:
                # Empty results array — no emails matched the query
                return "no_emails_found"
        except (json.JSONDecodeError, ValueError):
            pass

        return raw_text.strip()[:500] if raw_text else None

    except Exception as e:
        print(f"Zapier email error: {e}")
        return None

# ── Zapier MCP ────────────────────────────────────────────────────────────────
_ZAPIER_MCP_CFG = Path(os.environ.get("USERPROFILE", ".")) / ".openclaw" / "workspace" / "config" / "mcporter.json"

def fetch_calendar_zapier(query=None):
    """Fetch Google Calendar events via Zapier MCP (Streamable HTTP).
    query: the user's raw transcript so we can pick the right date range.
    Zapier POSTs return SSE-formatted responses: event: message / data: {json}
    """
    from datetime import datetime, timezone

    try:
        cfg = json.loads(_ZAPIER_MCP_CFG.read_text())
        mcp_url = cfg["mcpServers"]["zapier"]["baseUrl"]
    except Exception as e:
        print(f"Zapier config error: {e}")
        return None

    def zapier_rpc(method, params, req_id=None):
        """POST JSON-RPC; response is SSE with a single 'data:' line."""
        body = {"jsonrpc": "2.0", "method": method, "params": params}
        if req_id is not None:
            body["id"] = req_id
        req = urllib.request.Request(
            mcp_url,
            data=json.dumps(body).encode(),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            }
        )
        resp = urllib.request.urlopen(req, timeout=45)
        raw = resp.read().decode("utf-8")
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                try:
                    msg = json.loads(line[5:].strip())
                    if "result" in msg or "error" in msg:
                        return msg
                except Exception:
                    pass
        return None

    try:
        # 1. Initialize
        init_r = zapier_rpc("initialize", {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "jarvis", "version": "1.0"},
        }, req_id=1)
        if not init_r:
            print("Zapier: no initialize response")
            return None
        print(f"Zapier initialized: {init_r.get('result', {}).get('serverInfo', {})}")

        # 2. Notify initialized (notification — server may not respond)
        try:
            zapier_rpc("notifications/initialized", {})
        except Exception:
            pass

        # 3. List tools
        list_r = zapier_rpc("tools/list", {}, req_id=2)
        if not list_r:
            print("Zapier: no tools/list response")
            return None
        tools = list_r.get("result", {}).get("tools", [])
        print(f"Zapier tools: {[t.get('name') for t in tools]}")

        # 4. Find best calendar tool — must be "find_events", not "delete" or "update"
        def _score(t):
            n = t.get("name", "").lower()
            d = t.get("description", "").lower()
            if "calendar" in n and "find" in n and "event" in n:
                return 3  # google_calendar_find_events
            if "calendar" in n and "find" in n:
                return 2  # google_calendar_find_calendars
            if "calendar" in n or "calendar" in d:
                return 1  # other calendar tools
            return 0
        cal_tools = sorted([t for t in tools if _score(t) > 0], key=_score, reverse=True)
        if not cal_tools:
            print("No Google Calendar tool found in Zapier.")
            return None
        cal_tool = cal_tools[0]
        print(f"Using: {cal_tool['name']}")

        # 5. Build arguments from tool's input schema
        # Use local time so the range matches the user's calendar timezone.
        # Zapier's parameter semantics (from resolvedParams labels):
        #   start_time = "Start Time Before" = Google timeMax (events starting BEFORE this)
        #   end_time   = "End Time After"    = Google timeMin (events ending AFTER this)
        # So: end_time=window_start, start_time=window_end  (reversed vs intuition)
        from datetime import datetime as _dt_local, timedelta as _td
        now_local = _dt_local.now()
        today_human = now_local.strftime("%B %d, %Y")
        tl = (query or "").lower()

        # Determine target date window from the user's query
        if "tomorrow" in tl:
            target = now_local + _td(days=1)
            sod = target.replace(hour=0,  minute=0,  second=0,  microsecond=0)
            eod = target.replace(hour=23, minute=59, second=59, microsecond=0)
            date_desc = "tomorrow"
        elif "yesterday" in tl:
            target = now_local - _td(days=1)
            sod = target.replace(hour=0,  minute=0,  second=0,  microsecond=0)
            eod = target.replace(hour=23, minute=59, second=59, microsecond=0)
            date_desc = "yesterday"
        elif "this week" in tl or "week" in tl:
            sod = now_local.replace(hour=0,  minute=0,  second=0,  microsecond=0)
            eod = (sod + _td(days=7)).replace(hour=23, minute=59, second=59, microsecond=0)
            date_desc = "this week"
        elif "next week" in tl:
            # Monday of next week → Sunday of next week
            days_to_monday = (7 - now_local.weekday()) % 7 or 7
            monday = now_local + _td(days=days_to_monday)
            sod = monday.replace(hour=0,  minute=0,  second=0,  microsecond=0)
            eod = (sod + _td(days=6)).replace(hour=23, minute=59, second=59, microsecond=0)
            date_desc = "next week"
        else:
            # Default: today
            sod = now_local.replace(hour=0,  minute=0,  second=0,  microsecond=0)
            eod = now_local.replace(hour=23, minute=59, second=59, microsecond=0)
            date_desc = "today"

        props = cal_tool.get("inputSchema", {}).get("properties", {})
        print(f"Zapier schema props: {list(props.keys())}")
        args = {}
        target_human = sod.strftime("%B %d, %Y")
        for key in props:
            kl = key.lower()
            if kl == "instructions":
                if query:
                    # Pass the user's exact query — Zapier's AI filters appropriately.
                    # "dinner tomorrow" → returns dinner only. "what's on my calendar" → returns all.
                    args[key] = (
                        f"Today is {today_human}. The date to search is {target_human}. "
                        f"User asked: \"{query}\". "
                        "Return every matching event — do not stop at the first result."
                    )
                else:
                    args[key] = f"Find ALL events scheduled for today, {today_human}. Return every event. Include events from all calendars."
            elif kl == "output_hint":
                args[key] = "all event titles, start times, end times, locations"
            elif kl == "start_time":
                # timeMax — events starting BEFORE end of window
                args[key] = eod.isoformat()
            elif kl == "end_time":
                # timeMin — events ending AFTER start of window
                args[key] = sod.isoformat()
            elif kl in ("should_find_all", "find_all", "return_all", "find_all_records"):
                # Zapier "Should Find All?" parameter — return every match, not just first
                args[key] = True
            # NOTE: do NOT set calendar_id — leaving it unset lets Zapier search all calendars
        if not args and props:
            first_key = next(iter(props))
            args[first_key] = f"events {query or 'today'}"

        print(f"Calling {cal_tool['name']} args={args}")
        call_r = zapier_rpc("tools/call", {
            "name": cal_tool["name"],
            "arguments": args,
        }, req_id=3)
        if not call_r:
            print("Zapier: no tools/call response")
            return None

        content = call_r.get("result", {}).get("content", [])
        raw_text = next(
            (item["text"] for item in content
             if isinstance(item, dict) and item.get("type") == "text" and item.get("text")),
            None
        )
        if not raw_text:
            print("Zapier: empty content in tools/call response")
            return None

        # Zapier returns a JSON string in the text field — parse and format it
        try:
            data = json.loads(raw_text)
        except (json.JSONDecodeError, ValueError):
            return raw_text.strip()  # Not JSON — return as-is

        results = data.get("results", [])
        if not results:
            return f"No events scheduled for {date_desc}."

        # Zapier returns a dict for a single event, list for multiple events.
        if isinstance(results, dict):
            results = [results]

        from datetime import datetime as _dt
        def _fmt_time_str(val):
            if not val:
                return ""
            try:
                d = _dt.fromisoformat(str(val).replace("Z", "+00:00"))
                return d.strftime("%I:%M %p").lstrip("0") or "12:00 AM"
            except Exception:
                return str(val)[:16]

        lines = []
        for ev in results:
            if not isinstance(ev, dict):
                continue
            title = ev.get("title") or ev.get("summary") or "(No title)"
            t_start = _fmt_time_str(ev.get("start_time") or ev.get("start"))
            t_end   = _fmt_time_str(ev.get("end_time")   or ev.get("end"))
            location = ev.get("location") or ""
            parts = [title]
            if t_start and t_end:
                parts.append(f"{t_start} - {t_end}")
            elif t_start:
                parts.append(t_start)
            if location:
                parts.append(location)
            lines.append("• " + " | ".join(parts))

        return "\n".join(lines) if lines else "No events scheduled for today."

    except Exception as e:
        print(f"Zapier calendar error: {e}")
        return None


def create_calendar_event_zapier(query):
    """Create a Google Calendar event via Zapier Quick Add Event tool."""
    try:
        cfg = json.loads(_ZAPIER_MCP_CFG.read_text())
        mcp_url = cfg["mcpServers"]["zapier"]["baseUrl"]
    except Exception as e:
        print(f"Zapier config error: {e}")
        return None

    def zapier_rpc(method, params, req_id=None):
        body = {"jsonrpc": "2.0", "method": method, "params": params}
        if req_id is not None:
            body["id"] = req_id
        req = urllib.request.Request(
            mcp_url,
            data=json.dumps(body).encode(),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            }
        )
        resp = urllib.request.urlopen(req, timeout=45)
        raw = resp.read().decode("utf-8")
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                try:
                    msg = json.loads(line[5:].strip())
                    if "result" in msg or "error" in msg:
                        return msg
                except Exception:
                    pass
        return None

    try:
        # 1. Initialize
        init_r = zapier_rpc("initialize", {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "jarvis", "version": "1.0"},
        }, req_id=1)
        if not init_r:
            return None

        # 2. Notify initialized
        try:
            zapier_rpc("notifications/initialized", {})
        except Exception:
            pass

        # 3. List tools
        list_r = zapier_rpc("tools/list", {}, req_id=2)
        if not list_r:
            return None
        tools = list_r.get("result", {}).get("tools", [])
        print(f"Zapier tools (create): {[t.get('name') for t in tools]}")

        # 4. Pick best create tool — prefer Quick Add (natural language), then Create Detailed
        def _score(t):
            n = t.get("name", "").lower()
            if "quick" in n and ("add" in n or "create" in n):
                return 3
            if "create" in n and "event" in n:
                return 2
            if "create" in n:
                return 1
            return 0
        create_tools = sorted([t for t in tools if _score(t) > 0], key=_score, reverse=True)
        if not create_tools:
            print("No create event tool found in Zapier.")
            return None
        create_tool = create_tools[0]
        print(f"Using create tool: {create_tool['name']}")

        # 5. Build args — include today's date so Google parses relative words correctly
        from datetime import datetime as _dt_local
        today_human = _dt_local.now().strftime("%B %d, %Y")
        text_value = f"Today is {today_human}. {query}"

        props = create_tool.get("inputSchema", {}).get("properties", {})
        args = {}
        for key in props:
            kl = key.lower()
            if any(w in kl for w in ("text", "query", "instructions", "event", "input")):
                args[key] = text_value
                break
        if not args and props:
            args[next(iter(props))] = text_value

        print(f"Calling {create_tool['name']} args={args}")
        call_r = zapier_rpc("tools/call", {"name": create_tool["name"], "arguments": args}, req_id=3)
        if not call_r:
            return None

        # 6. Parse result
        result_data = call_r.get("result", {})
        content = result_data.get("content", [])
        raw_text = ""
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                raw_text += item.get("text", "")

        # Try to get structured event data
        try:
            parsed = json.loads(raw_text)
            if isinstance(parsed, list) and parsed:
                parsed = parsed[0]
            if isinstance(parsed, dict):
                title = parsed.get("title") or parsed.get("summary") or "Event"
                start = parsed.get("start_time") or parsed.get("start") or ""
                if start:
                    try:
                        from datetime import datetime as _dtp
                        d = _dtp.fromisoformat(str(start).replace("Z", "+00:00"))
                        start = d.strftime("%b %d, %I:%M %p").lstrip("0")
                    except Exception:
                        start = str(start)[:16]
                return f"✅ Created: {title}" + (f" | {start}" if start else "")
        except Exception:
            pass

        # Fallback: return raw text if it looks like a confirmation
        if raw_text and len(raw_text) < 300:
            return f"✅ {raw_text.strip()}"
        return "✅ Event created successfully."

    except Exception as e:
        print(f"Zapier create calendar error: {e}")
        return None

# ── Groq ──────────────────────────────────────────────────────────────────────
JARVIS_INSTRUCTIONS = (
    "You are JARVIS, the highly intelligent and formal AI assistant from the Iron Man "
    "and Avengers films. Respond with a refined British manner. "
    "Always use 'sir' exactly once per response as a direct address — place it at the end "
    "of a complete sentence (e.g. '...at noon, sir.') or after a comma before a new clause "
    "(e.g. 'Very well, sir, your lunch has been scheduled.'). Never place 'sir' in a position "
    "that breaks grammatical flow or splits a noun phrase. "
    "Every sentence must be grammatically complete and correct. "
    "Keep replies concise — two sentences at most. Never mention being an AI or a language model. "
    "CRITICAL: Never invent, fabricate, or assume real-world facts such as calendar events, emails, "
    "weather, or times. If data is provided to you, report only that data exactly. "
    "If no data is provided, say you do not have that information."
)

def get_groq_response(user_text):
    """Call Groq API with Jarvis system prompt. Returns text or None."""
    import urllib.request, urllib.error, json as _json
    payload = _json.dumps({
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": JARVIS_INSTRUCTIONS},
            {"role": "user",   "content": user_text},
        ],
        "max_tokens": 150,
        "temperature": 0.7,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        },
    )
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        data = _json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"Groq error: {e}")
        return None

# ── Nutrition (USDA FoodData Central) ────────────────────────────────────────
_USDA_NUTRIENTS = {
    "208": ("Calories", "kcal"),
    "203": ("Protein", "g"),
    "204": ("Fat", "g"),
    "205": ("Carbs", "g"),
    "291": ("Fiber", "g"),
    "269": ("Sugar", "g"),
}

def fetch_nutrition(query):
    """Look up macros for one or more foods with quantities via USDA FoodData Central.
    Parses multi-item queries (e.g. '8 sushi rolls and 130g yogurt'), scales each
    item to the requested quantity, and returns per-item breakdown + total calories.
    Returns formatted string, 'no_food_found', or None on error.
    """
    if not USDA_API_KEY:
        print("USDA_API_KEY not set")
        return None

    # 1. Use Groq to extract food items + quantities from natural language query
    parse_system = (
        "Extract all food items and quantities from the user query.\n"
        "Reply with ONLY a valid JSON array, no other text.\n"
        'Format: [{"food": "food name", "quantity": number, "unit": "g|ml|pieces|cups|oz|tbsp", "approx_grams": number}]\n'
        "approx_grams = estimated weight in grams for ONE unit of that item.\n"
        "For g/ml units set approx_grams=1 (quantity is already in grams).\n"
        "Examples: 1 sushi roll piece≈30g, 1 egg≈60g, 1 banana≈120g, 1 cup yogurt≈245g, 1oz≈28g"
    )
    items = []
    try:
        payload = json.dumps({
            "model": "llama-3.1-8b-instant",
            "messages": [
                {"role": "system", "content": parse_system},
                {"role": "user",   "content": query},
            ],
            "max_tokens": 250,
            "temperature": 0,
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {GROQ_API_KEY}",
                     "User-Agent": "Mozilla/5.0"},
        )
        raw = json.loads(urllib.request.urlopen(req, timeout=10).read())["choices"][0]["message"]["content"].strip()
        if "```" in raw:
            raw = raw.split("```")[1].lstrip("json").strip()
        items = json.loads(raw)
        print(f"nutrition items: {items}")
    except Exception as e:
        print(f"nutrition parse error: {e} — treating as single 100g item")
        items = [{"food": query, "quantity": 100, "unit": "g", "approx_grams": 1}]

    if not items:
        return "no_food_found"

    # 2. Look up each item in USDA and scale to requested quantity
    results = []
    total_cal = 0
    total_p   = 0.0
    total_f   = 0.0
    total_c   = 0.0

    for item in items[:4]:
        food_name  = item.get("food", "")
        quantity   = float(item.get("quantity", 100))
        unit       = item.get("unit", "g")
        approx_g   = float(item.get("approx_grams", 1))
        total_g    = quantity if unit in ("g", "ml", "grams") else quantity * approx_g

        try:
            url = (
                "https://api.nal.usda.gov/fdc/v1/foods/search"
                f"?query={urllib.parse.quote(food_name)}"
                f"&api_key={USDA_API_KEY}"
                "&pageSize=3&dataType=Foundation,SR%20Legacy"
            )
            data = json.loads(urllib.request.urlopen(url, timeout=10).read())
            foods = data.get("foods", [])
        except Exception as e:
            print(f"USDA lookup error for {food_name}: {e}")
            continue

        if not foods:
            results.append(f"• {food_name}: not found")
            continue

        food = foods[0]
        usda_name = food.get("description", food_name).title()
        by_num = {n["nutrientNumber"]: n.get("value") for n in food.get("foodNutrients", [])
                  if n.get("nutrientNumber") and n.get("value") is not None}

        scale = total_g / 100.0
        parts = []

        prot  = by_num.get("203")
        fat   = by_num.get("204")
        carb  = by_num.get("205")
        fiber = by_num.get("291")

        prot_s  = round(prot  * scale, 1) if prot  is not None else None
        fat_s   = round(fat   * scale, 1) if fat   is not None else None
        carb_s  = round(carb  * scale, 1) if carb  is not None else None
        fiber_s = round(fiber * scale, 1) if fiber is not None else None

        # Prefer USDA "208" energy value; fall back to Atwater calculation
        cal = by_num.get("208")
        if cal is not None:
            cal_s = round(cal * scale)
        elif prot_s is not None or fat_s is not None or carb_s is not None:
            cal_s = round((prot_s or 0) * 4 + (fat_s or 0) * 9 + (carb_s or 0) * 4)
        else:
            cal_s = None

        if cal_s:
            total_cal += cal_s
            parts.append(f"{cal_s}kcal")
        if prot_s is not None:
            total_p += prot_s
            parts.append(f"Protein: {prot_s}g")
        if fat_s is not None:
            total_f += fat_s
            parts.append(f"Fat: {fat_s}g")
        if carb_s is not None:
            total_c += carb_s
            parts.append(f"Carbs: {carb_s}g")
        if fiber_s is not None:
            parts.append(f"Fiber: {fiber_s}g")

        qty_str = f"{int(quantity) if quantity == int(quantity) else quantity}{unit}"
        if unit not in ("g", "ml", "grams"):
            qty_str += f" (~{int(total_g)}g)"
        results.append(f"• {qty_str} {usda_name}: {', '.join(parts)}")

    if not results:
        return "no_food_found"

    output = "\n".join(results)
    if len(results) > 1:
        total_parts = [f"{total_cal}kcal"]
        if total_p > 0: total_parts.append(f"Protein: {round(total_p, 1)}g")
        if total_f > 0: total_parts.append(f"Fat: {round(total_f, 1)}g")
        if total_c > 0: total_parts.append(f"Carbs: {round(total_c, 1)}g")
        output += f"\nTotal: {' | '.join(total_parts)}"
    return output


# ── Intent classification ─────────────────────────────────────────────────────
_INTENT_CATEGORIES = {
    "reminder", "weather", "time", "email",
    "calendar_find", "calendar_create", "nearby", "nutrition", "general"
}

def _keyword_fallback(text):
    """Safety net if Groq classification fails."""
    if is_reminder_question(text):        return "reminder"
    if is_weather_question(text):         return "weather"
    if is_time_question(text):            return "time"
    if is_email_question(text):           return "email"
    if is_calendar_create_question(text): return "calendar_create"
    if is_calendar_question(text):        return "calendar_find"
    tl = text.lower()
    if any(w in tl for w in ("nearby", "near me", "close by", "around here", "find a ", "find me a", "restaurant", "cafe", "pharmacy", "hospital")):
        return "nearby"
    if any(w in tl for w in ("calorie", "calories", "macro", "macros", "protein", "carb", "carbs", "nutrition", "fat in", "how much fat", "how many calories")):
        return "nutrition"
    return "general"

def classify_intent(text):
    """Classify user intent and extract location via Groq (llama-3.1-8b-instant, temp=0).
    Returns (intent, location) where location is a city/place string or None."""
    import urllib.request, urllib.error, json as _json
    system = (
        "Classify the message and extract the location. Reply with ONLY valid JSON, no other text.\n"
        "Format: {\"intent\": \"category\", \"location\": \"City Name or null\"}\n\n"
        "intent must be exactly one of:\n"
        "reminder — setting or asking about a reminder\n"
        "weather — weather, temperature, rain, umbrella, jacket, outdoor conditions, what to wear outside, going out/outside now, heading out, leaving now, any message implying the user is about to be outdoors and would benefit from weather context\n"
        "time — current time in a specific location\n"
        "email — checking, reading, or searching emails or inbox\n"
        "calendar_find — asking about existing events, schedule, meetings, or availability\n"
        "calendar_create — creating, adding, booking, or scheduling a new event\n"
        "nearby — finding nearby places: restaurants, cafes, bars, pharmacies, hospitals, shops, etc.\n"
        "nutrition — calories, macros, protein, fat, carbs, or nutrition info for any food\n"
        "general — anything else\n\n"
        "location: the specific city or place explicitly mentioned, or null if none. "
        "Do not infer locations from context (e.g. 'a walk', 'a trip', 'outside' are not locations)."
    )
    payload = _json.dumps({
        "model": "llama-3.1-8b-instant",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": text},
        ],
        "max_tokens": 50,
        "temperature": 0,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        },
    )
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        raw = _json.loads(resp.read())["choices"][0]["message"]["content"].strip()
        parsed = _json.loads(raw)
        intent = parsed.get("intent", "").strip().lower()
        location = parsed.get("location") or None
        if location:
            location = str(location).strip()
        if intent not in _INTENT_CATEGORIES:
            intent = _keyword_fallback(text)
        print(f"classify_intent: '{text[:60]}' → {intent}, location={location}")
        return intent, location
    except Exception as e:
        print(f"classify_intent error: {e} — using keyword fallback")
        return _keyword_fallback(text), None

def _strip_emoji(text):
    """Remove emoji characters so TTS doesn't read them aloud."""
    import re
    return re.sub(r'[^\w\s,.()\[\]:°%\-/]', '', text).strip()

# ── Audio / TTS ───────────────────────────────────────────────────────────────
def _mp3_to_ogg(mp3_path, ogg_path):
    """Convert MP3 to OGG/Opus using PyAV (bundled ffmpeg). WhatsApp plays OGG
    inline as audio; MP3 is sent as a document download."""
    import av
    with av.open(str(mp3_path)) as inp:
        with av.open(str(ogg_path), "w", format="ogg") as out:
            out_stream = out.add_stream("libopus", rate=24000)
            out_stream.layout = "mono"
            for frame in inp.decode(audio=0):
                frame.pts = None
                for packet in out_stream.encode(frame):
                    out.mux(packet)
            for packet in out_stream.encode(None):
                out.mux(packet)

def send_whatsapp_audio(text_to_speak):
    """Generate TTS audio via edge-tts, convert to OGG, send as WhatsApp voice note."""
    import edge_tts
    pid = os.getpid()
    mp3 = Path(__file__).parent / f"tts_tmp_{pid}.mp3"
    ogg = Path(__file__).parent / f"tts_tmp_{pid}.ogg"
    try:
        async def _gen():
            communicate = edge_tts.Communicate(text_to_speak, "en-GB-RyanNeural")
            await communicate.save(str(mp3))
        asyncio.run(_gen())
        _mp3_to_ogg(mp3, ogg)
        cmd = [
            "openclaw.cmd", "message", "send",
            "--channel", "whatsapp",
            "--target", WHATSAPP_TARGET,
            "--media", str(ogg),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        print(f"Audio send exit={result.returncode}")
        if result.returncode != 0:
            print(f"Audio send stderr: {result.stderr.strip()}")
            print(f"Audio send stdout: {result.stdout.strip()}")
        return result.returncode == 0
    except Exception as e:
        print(f"TTS error: {e}")
        return False
    finally:
        mp3.unlink(missing_ok=True)
        ogg.unlink(missing_ok=True)

# ── WhatsApp send ─────────────────────────────────────────────────────────────
def send_whatsapp(message):
    """Send WhatsApp message via openclaw CLI."""
    cmd = [
        "openclaw.cmd", "message", "send",
        "--channel", "whatsapp",
        "--target", WHATSAPP_TARGET,
        "--message", message
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0

# ── OpenClaw API ──────────────────────────────────────────────────────────────
def get_ai_response(transcript, instructions=None):
    """Send transcript to OpenClaw API and get response."""
    payload = {
        'model': 'openclaw:main',
        'input': [
            {'type': 'message', 'role': 'user', 'content': transcript}
        ]
    }
    if instructions:
        payload['instructions'] = instructions
    req = urllib.request.Request(
        'http://127.0.0.1:18789/v1/responses',
        data=json.dumps(payload).encode('utf-8'),
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {GATEWAY_TOKEN}'
        }
    )
    try:
        resp = urllib.request.urlopen(req, timeout=120)
        result = json.loads(resp.read().decode('utf-8'))
        output = result.get('output', [])
        if output and output[0].get('content'):
            for item in output[0]['content']:
                if item.get('type') == 'output_text':
                    return item.get('text', '')
    except Exception as e:
        print(f"API Error: {e}")
    return None
