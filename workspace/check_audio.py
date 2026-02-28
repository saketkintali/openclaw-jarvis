#!/usr/bin/env python3
"""Check for new audio files, transcribe, get AI response, and send via WhatsApp."""

import os
import sys
import json
import time
import subprocess
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path

MEDIA_DIR = Path(os.environ.get("USERPROFILE", ".")) / ".openclaw" / "media" / "inbound"
STATE_FILE = Path(__file__).parent / "audio_state.json"
LOCK_FILE = Path(__file__).parent / "check_audio.lock"
WHATSAPP_TARGET = os.environ.get("WHATSAPP_TARGET", "")  # Your WhatsApp number, e.g. "+15551234567"
GATEWAY_TOKEN = os.environ.get("GATEWAY_TOKEN", "")  # From openclaw.json → gateway.token

# Default location — always use this unless the user specifies otherwise
DEFAULT_LOCATION = os.environ.get("DEFAULT_LOCATION", "10001")  # ZIP code or city name
DEFAULT_LOCATION_NAME = os.environ.get("DEFAULT_LOCATION_NAME", "New York")  # Human-readable city name

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

GMAIL_EMAIL = os.environ.get("GMAIL_EMAIL", "")  # your.email@gmail.com
GMAIL_PASSWORD = os.environ.get("GMAIL_PASSWORD", "")  # Gmail App Password (not your login password)

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

_CALENDAR_DELETE_KEYWORDS = {
    "remove", "delete", "cancel", "clear", "drop", "erase"
}

def is_calendar_delete_question(text):
    tl = text.lower()
    words = set(tl.split())
    return bool(words & _CALENDAR_DELETE_KEYWORDS) and bool(
        words & _CALENDAR_CREATE_CONTEXT or
        any(w in tl for w in ("event", "appointment", "meeting", "calendar"))
    )

def is_reminder_question(text):
    tl = text.lower()
    return "remind" in tl or "remember to" in tl or "don't forget" in tl or "dont forget" in tl

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

def fetch_amazon_emails():
    """Fetch today's Amazon emails from Gmail. Returns formatted string or None."""
    import imaplib
    import email as email_lib
    from datetime import datetime
    try:
        mail = imaplib.IMAP4_SSL('imap.gmail.com')
        mail.login(GMAIL_EMAIL, GMAIL_PASSWORD)
        mail.select('INBOX')
        today = datetime.now().strftime("%d-%b-%Y")  # e.g. "26-Feb-2026"
        status, messages = mail.search(None, f'FROM amazon SINCE {today}')
        ids = messages[0].split() if messages[0] else []
        if not ids:
            mail.logout()
            return f"No Amazon emails today ({today})."
        results = []
        for mid in reversed(ids[-5:]):  # last 5, newest first
            status, msg_data = mail.fetch(mid, '(RFC822)')
            msg = email_lib.message_from_bytes(msg_data[0][1])
            subject = msg['Subject'] or '(no subject)'
            results.append(f"• {subject}")
        mail.logout()
        count = len(ids)
        return f"{count} Amazon email(s) today ({today}):\n" + "\n".join(results)
    except Exception as e:
        print(f"Gmail fetch error: {e}")
        return None

_ZAPIER_MCP_CFG = Path(os.environ.get("USERPROFILE", ".")) / ".openclaw" / "workspace" / "config" / "mcporter.json"

def fetch_gmail_zapier(instructions_override=None, want_body=False):
    """Fetch Gmail emails via Zapier MCP. Falls back to fetch_amazon_emails() on failure."""
    from datetime import datetime as _dt_local
    try:
        cfg = json.loads(_ZAPIER_MCP_CFG.read_text())
        mcp_url = cfg["mcpServers"]["zapier"]["baseUrl"]
    except Exception as e:
        print(f"Zapier config error: {e}")
        return fetch_amazon_emails()

    def zapier_rpc(method, params, req_id=None):
        body = {"jsonrpc": "2.0", "method": method, "params": params}
        if req_id is not None:
            body["id"] = req_id
        req = urllib.request.Request(
            mcp_url, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json",
                     "Accept": "application/json, text/event-stream",
                     "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
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
        init_r = zapier_rpc("initialize", {"protocolVersion": "2025-03-26",
            "capabilities": {}, "clientInfo": {"name": "jarvis", "version": "1.0"}}, req_id=1)
        if not init_r:
            return fetch_amazon_emails()
        try:
            zapier_rpc("notifications/initialized", {})
        except Exception:
            pass

        list_r = zapier_rpc("tools/list", {}, req_id=2)
        if not list_r:
            return fetch_amazon_emails()
        tools = list_r.get("result", {}).get("tools", [])

        def _score(t):
            n = t.get("name", "").lower()
            if "gmail" in n and "find" in n: return 2
            if "gmail" in n: return 1
            return 0
        gmail_tools = sorted([t for t in tools if _score(t) > 0], key=_score, reverse=True)
        if not gmail_tools:
            print("No Gmail tool found in Zapier — falling back to IMAP.")
            return fetch_amazon_emails()
        gmail_tool = gmail_tools[0]
        print(f"Using Gmail tool: {gmail_tool['name']}")

        now_local = _dt_local.now()
        today_human = now_local.strftime("%B %d, %Y")
        props = gmail_tool.get("inputSchema", {}).get("properties", {})
        args = {}
        for key in props:
            kl = key.lower()
            if kl == "instructions":
                args[key] = instructions_override or f"Find all emails received today, {today_human}. Most recent first. Up to 5."
            elif kl == "output_hint":
                if want_body:
                    args[key] = "email subject, sender name, email body or message content"
                else:
                    args[key] = "email subject, sender name or email address"

        print(f"Calling {gmail_tool['name']} args={args}")
        call_r = zapier_rpc("tools/call", {"name": gmail_tool["name"], "arguments": args}, req_id=3)
        if not call_r:
            return fetch_amazon_emails()

        content = call_r.get("result", {}).get("content", [])
        raw_text = next((item["text"] for item in content
            if isinstance(item, dict) and item.get("type") == "text" and item.get("text")), None)
        if not raw_text:
            return fetch_amazon_emails()

        try:
            data = json.loads(raw_text)
        except (json.JSONDecodeError, ValueError):
            return raw_text.strip()

        results = data.get("results", [])
        if not results:
            return "No emails found."
        if isinstance(results, dict):
            results = [results]

        lines = []
        for ev in results:
            if not isinstance(ev, dict):
                continue
            subject = ev.get("subject") or ev.get("title") or "(no subject)"
            sender  = ev.get("from") or ev.get("sender") or ev.get("from_name") or ev.get("from_email") or ""
            parts = [subject]
            if sender:
                parts.append(f"From: {sender}")
            lines.append("• " + " | ".join(parts))
            if want_body:
                body = (ev.get("body") or ev.get("body_plain") or
                        ev.get("snippet") or ev.get("message") or "")
                if body:
                    lines.append(f"  {body.strip()[:400]}")

        count = len(results)
        return f"{count} email(s):\n" + "\n".join(lines)

    except Exception as e:
        print(f"Zapier Gmail error: {e}")
        return fetch_amazon_emails()

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
        # The JQ filter transforms fields: summary→title, start.dateTime→start_time, etc.
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


def delete_calendar_event_zapier(query):
    """Delete a Google Calendar event using natural language instructions (single-step)."""
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
        # Initialize
        init_r = zapier_rpc("initialize", {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "jarvis", "version": "1.0"},
        }, req_id=1)
        if not init_r:
            return None
        try:
            zapier_rpc("notifications/initialized", {})
        except Exception:
            pass

        # List tools
        list_r = zapier_rpc("tools/list", {}, req_id=2)
        if not list_r:
            return None
        tools = list_r.get("result", {}).get("tools", [])

        find_tool = next((t for t in tools if "find" in t.get("name","").lower() and "event" in t.get("name","").lower()), None)
        del_tool  = next((t for t in tools if "delete" in t.get("name","").lower() and "calendar" in t.get("name","").lower()), None)
        if not del_tool:
            print("No calendar delete tool found")
            return None

        # Build date window from query
        from datetime import datetime as _dt_local, timedelta as _td
        now = _dt_local.now()
        today_human = now.strftime("%B %d, %Y")
        tl = query.lower()
        if "tomorrow" in tl:
            target = now + _td(days=1)
        elif "yesterday" in tl:
            target = now - _td(days=1)
        else:
            target = now
        target_human = target.strftime("%B %d, %Y")
        sod = target.replace(hour=0,  minute=0,  second=0,  microsecond=0)
        eod = target.replace(hour=23, minute=59, second=59, microsecond=0)

        # Step 1 — find the event to get exact title + time
        if not find_tool:
            print("No find tool — cannot delete")
            return None
        find_props = find_tool.get("inputSchema", {}).get("properties", {})
        find_args = {}
        for key in find_props:
            kl = key.lower()
            if kl == "instructions":
                find_args[key] = f"Today is {today_human}. Find this event: {query}. Date: {target_human}. Return title and exact start time."
            elif kl == "output_hint":
                find_args[key] = "event title, start time"
            elif kl == "start_time":
                find_args[key] = eod.isoformat()
            elif kl == "end_time":
                find_args[key] = sod.isoformat()
        print(f"Delete: finding event for '{query}'")
        find_r = zapier_rpc("tools/call", {"name": find_tool["name"], "arguments": find_args}, req_id=3)
        raw_find = next((i["text"] for i in find_r.get("result",{}).get("content",[]) if isinstance(i,dict) and i.get("type")=="text"), None) if find_r else None
        if not raw_find:
            return None

        # Parse exact title + time from find result
        try:
            fp = json.loads(raw_find)
            if isinstance(fp, dict) and "results" in fp:
                fp = fp["results"]
            if isinstance(fp, list) and fp:
                fp = fp[0]
            title = next((fp[k] for k in ("event_title","title","summary","event_name","name","label") if fp.get(k)), "")
            start = ""
            for k in ("start_time","start","startTime","start_datetime","dateTime"):
                v = fp.get(k)
                if v:
                    try:
                        from datetime import datetime as _dt2
                        dt = _dt2.fromisoformat(str(v).replace("Z","+00:00"))
                        start = dt.strftime("%I:%M %p on %B %d")
                    except Exception:
                        start = str(v)
                    break
        except Exception:
            title, start = "", ""

        if not title:
            print(f"Find returned no matching event: {raw_find[:120]}")
            return None
        print(f"Found: '{title}' at {start}")

        # Step 2 — delete with exact details
        del_props = del_tool.get("inputSchema", {}).get("properties", {})
        del_args = {}
        for key in del_props:
            kl = key.lower()
            if kl == "instructions":
                del_args[key] = (
                    f"Today is {today_human}. "
                    f"Delete this Google Calendar event: exact title: '{title}'"
                    + (f", start time: {start}" if start else "")
                    + f" on {target_human}. "
                    "Do not notify attendees. Do not ask follow-up questions. Delete it immediately."
                )
            elif kl == "output_hint":
                del_args[key] = "confirmation that the event was deleted"
        if not del_args and del_props:
            del_args[next(iter(del_props))] = title

        print(f"Deleting: '{title}'")
        del_r = zapier_rpc("tools/call", {"name": del_tool["name"], "arguments": del_args}, req_id=4)
        raw = next((i["text"] for i in del_r.get("result",{}).get("content",[]) if isinstance(i,dict) and i.get("type")=="text"), None) if del_r else None
        print(f"Delete result: {raw}")

        if not raw:
            return None
        try:
            parsed = json.loads(raw)
            if parsed.get("followUpQuestion"):
                return None
            if parsed.get("execution", {}).get("status") == "SUCCESS":
                return title
        except Exception:
            pass
        low = raw.lower()
        if any(w in low for w in ("not found","couldn't find","no event","unable","could not")):
            return None
        return title

    except Exception as e:
        print(f"Zapier delete calendar error: {e}")
        return None


def extract_location(text):
    """Extract a location from text like 'weather in Chicago' or 'time in Frankfurt, Germany'."""
    import re
    # Allow optional ', Country/State' suffix (e.g. "Frankfurt, Germany", "Seattle, WA")
    m = re.search(
        r'\b(?:in|for|at)\s+([A-Za-z0-9][A-Za-z0-9\s]{0,29}?(?:,\s*[A-Za-z]{2,15})?)(?:\s*[?!.]|$)',
        text, re.IGNORECASE
    )
    if m:
        loc = m.group(1).strip()
        # Strip trailing temporal/filler words and time references
        loc = re.sub(r'\s+(?:now|today|tonight|tomorrow|currently|right\s+now|at\s+the\s+moment)$', '', loc, flags=re.IGNORECASE).strip()
        loc = re.sub(r'\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?$', '', loc, flags=re.IGNORECASE).strip()
        return loc if loc else None
    return None

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

        # Fetch current conditions + hourly precipitation for today
        wx_url = (f"https://api.open-meteo.com/v1/forecast"
                  f"?latitude={lat}&longitude={lon}"
                  f"&current_weather=true&temperature_unit=fahrenheit&windspeed_unit=mph"
                  f"&hourly=precipitation_probability&forecast_days=1"
                  f"&timezone=America%2FLos_Angeles")
        wx = json.loads(urllib.request.urlopen(wx_url, timeout=8).read())
        cw = wx["current_weather"]
        desc = WEATHER_CODES.get(int(cw["weathercode"]), "Unknown")
        current_line = f"{loc_name}: {desc}, {cw['temperature']}°F, wind {cw['windspeed']} mph"

        # Build hourly rain chance string (every 2 hours, 8am–8pm)
        hourly = wx.get("hourly", {})
        times = hourly.get("time", [])
        probs = hourly.get("precipitation_probability", [])
        slots = []
        for t, p in zip(times, probs):
            if p is None:
                continue
            hour_str = t[11:16]  # "HH:MM"
            h = int(hour_str[:2])
            if 8 <= h <= 20 and h % 2 == 0:
                label = f"{h if h <= 12 else h - 12}{'am' if h < 12 else 'pm'}"
                slots.append(f"{label} {p}%")
        if slots:
            return current_line + "\nHourly rain chance: " + " | ".join(slots)
        return current_line
    except Exception as e:
        print(f"Weather fetch error: {e}")
        return None

# Fix stdout for unicode
if sys.stdout.encoding != 'utf-8':
    sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', closefd=False)

def acquire_lock():
    """Returns True if lock acquired, False if another instance is already running."""
    if LOCK_FILE.exists():
        age = time.time() - LOCK_FILE.stat().st_mtime
        if age < 300:  # 5 min timeout — stale lock protection
            print(f"Lock held by another instance ({age:.0f}s old), skipping.")
            return False
        print("Stale lock found, removing.")
    LOCK_FILE.write_text(str(os.getpid()))
    return True

def release_lock():
    try:
        LOCK_FILE.unlink()
    except FileNotFoundError:
        pass

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"processed": []}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")  # Get from console.groq.com
GROQ_MODEL   = "llama-3.3-70b-versatile"
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

_INTENT_CATEGORIES = {
    "reminder", "weather", "time", "email",
    "calendar_find", "calendar_create", "calendar_delete", "general"
}

def _keyword_fallback(text):
    """Safety net if Groq classification fails."""
    if is_reminder_question(text):        return "reminder"
    if is_weather_question(text):         return "weather"
    if is_time_question(text):            return "time"
    if is_email_question(text):           return "email"
    if is_calendar_delete_question(text): return "calendar_delete"
    if is_calendar_create_question(text): return "calendar_create"
    if is_calendar_question(text):        return "calendar_find"
    return "general"

def classify_intent(text):
    """Classify user intent via Groq (llama-3.1-8b-instant, temp=0). Falls back to keyword matching."""
    import urllib.request, urllib.error, json as _json
    system = (
        "Classify the message into exactly one category. Reply with ONLY the category name, nothing else.\n\n"
        "reminder — setting or asking about a reminder\n"
        "weather — weather, temperature, rain, umbrella, jacket, outdoor conditions, should I bring a jacket/umbrella, will it rain, is it cold, what to wear outside\n"
        "time — current time in a specific location\n"
        "email — checking, reading, or searching emails or inbox\n"
        "calendar_find — asking about existing events, schedule, meetings, or availability\n"
        "calendar_create — creating, adding, booking, or scheduling a new event\n"
        "calendar_delete — removing, deleting, or cancelling an existing event\n"
        "general — anything else"
    )
    payload = _json.dumps({
        "model": "llama-3.1-8b-instant",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": text},
        ],
        "max_tokens": 10,
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
        label = _json.loads(resp.read())["choices"][0]["message"]["content"].strip().lower()
        print(f"classify_intent: '{text[:60]}' → {label}")
        return label if label in _INTENT_CATEGORIES else _keyword_fallback(text)
    except Exception as e:
        print(f"classify_intent error: {e} — using keyword fallback")
        return _keyword_fallback(text)

def _strip_emoji(text):
    """Remove emoji characters so TTS doesn't read them aloud."""
    import re
    return re.sub(r'[^\w\s,.()\[\]:°%\-/]', '', text).strip()

def _mp3_to_ogg(mp3_path, ogg_path):
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
    """Generate TTS audio via edge-tts and send as WhatsApp voice note."""
    import edge_tts, asyncio
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
        return result.returncode == 0
    except Exception as e:
        print(f"TTS error: {e}")
        return False
    finally:
        mp3.unlink(missing_ok=True)
        ogg.unlink(missing_ok=True)

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

def transcribe_audio(audio_path):
    """Transcribe audio file using transcribe.py."""
    script_dir = Path(__file__).parent
    cmd = [sys.executable, str(script_dir / "transcribe.py"), str(audio_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    # Extract transcript (skip the first line which has model info)
    lines = result.stdout.strip().split('\n')
    return '\n'.join(lines[1:]) if len(lines) > 1 else result.stdout.strip()

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

def main():
    if not acquire_lock():
        return

    try:
        state = load_state()
        processed = set(state["processed"])

        audio_extensions = {".mp3", ".ogg", ".m4a", ".wav", ".opus", ".oga"}
        audio_files = [
            f for f in MEDIA_DIR.iterdir()
            if f.is_file() and f.suffix.lower() in audio_extensions
        ]

        for audio_file in sorted(audio_files, key=lambda x: x.stat().st_mtime):
            if str(audio_file) in processed:
                continue

            print(f"New audio: {audio_file.name}")
            transcript = transcribe_audio(audio_file)

            if transcript:
                print(f"Transcript: {transcript}")

                spoken = None   # text to convert to audio
                fallback = None  # text fallback if TTS fails

                intent = classify_intent(transcript)

                if intent == "reminder":
                    result = parse_reminder_groq(transcript)
                    if result:
                        task, remind_at = result
                        save_reminder(task, remind_at)
                        from datetime import datetime as _dtr
                        try:
                            dt = _dtr.fromisoformat(remind_at)
                            time_str = dt.strftime("%I:%M %p").lstrip("0")
                            date_str = "today" if dt.date() == _dtr.now().date() else dt.strftime("%A")
                            confirm = f"Reminder set for {task} at {time_str} {date_str}."
                        except Exception:
                            confirm = f"Reminder set: {task}."
                        spoken = get_groq_response(
                            f"Confirm this reminder was just saved: {confirm}."
                        ) or confirm
                        fallback = f"🔔 {confirm}"
                    else:
                        spoken = None
                        fallback = "⚠️ Couldn't parse that reminder. Try: 'remind me to call mom at 8:30 PM'."
                elif intent == "weather":
                    location = extract_location(transcript)
                    response = fetch_weather(location)
                    print(f"Weather response: {response}")
                    if response:
                        spoken = get_groq_response(
                            f"The user asked: \"{transcript}\"\nCurrent weather data: {_strip_emoji(response)}\n"
                            "Answer their specific question using only this data. One concise sentence."
                        ) or _strip_emoji(response)
                        fallback = f"🎙️ {response}"
                    else:
                        fallback = f"⚠️ Couldn't fetch weather for '{location}'. You said: {transcript}"
                elif intent == "time":
                    location = extract_location(transcript)
                    response = fetch_time(location)
                    print(f"Time response: {response}")
                    if response:
                        spoken = get_groq_response(
                            f"The user asked: \"{transcript}\"\nHere is the data: {_strip_emoji(response)}\n"
                            "Rephrase this as a natural spoken sentence."
                        ) or _strip_emoji(response)
                        fallback = f"🎙️ {response}"
                    else:
                        fallback = f"⚠️ Couldn't fetch time for '{location}'. You said: {transcript}"
                elif intent == "email":
                    _today_h = __import__("datetime").datetime.now().strftime("%B %d, %Y")
                    _email_instr = (
                        f"Today is {_today_h}. User request: \"{transcript}\". "
                        "Search Gmail accordingly. Include emails from any date if the user asks about older emails. "
                        "Return up to 5 results, most recent first."
                    )
                    _read_words = {"read", "reads", "reading", "content", "body", "say", "says", "said"}
                    _want_body = bool(set(transcript.lower().split()) & _read_words)
                    response = fetch_gmail_zapier(_email_instr, want_body=_want_body)
                    print(f"Email response: {response}")
                    if response:
                        spoken = get_groq_response(
                            f"The user asked: \"{transcript}\"\nHere is the data: {response}\n"
                            "Rephrase this as a natural spoken sentence."
                        ) or response
                        fallback = "🎙️ " + "  ".join(l.strip() for l in response.split('\n') if l.strip())
                    else:
                        fallback = f"⚠️ Couldn't check Gmail. You said: {transcript}"
                elif intent == "calendar_delete":
                    response = delete_calendar_event_zapier(transcript)
                    print(f"Calendar delete response: {response}")
                    if response:
                        spoken = get_groq_response(
                            f"The user asked: \"{transcript}\"\nResult: {response}\n"
                            "Confirm the event was deleted in one natural sentence."
                        ) or response
                        fallback = f"🗑️ {response}"
                    else:
                        spoken = get_groq_response(
                            f"The user asked: \"{transcript}\"\n"
                            "The event could not be found in the calendar. "
                            "Say sorry briefly and suggest the user double-check the event name or time."
                        ) or "I'm afraid I couldn't locate that event in your calendar, sir."
                        fallback = f"⚠️ {spoken}"
                elif intent == "calendar_create":
                    response = create_calendar_event_zapier(transcript)
                    print(f"Calendar create response: {response}")
                    if response:
                        spoken = get_groq_response(
                            f"The user asked: \"{transcript}\"\nResult: {response}\n"
                            "Confirm the event was created in one natural sentence."
                        ) or response
                        fallback = f"📅 {response}"
                    else:
                        fallback = "⚠️ Couldn't create the event. Try: 'create lunch tomorrow at 12pm'."
                elif intent == "calendar_find":
                    response = fetch_calendar_zapier(query=transcript)
                    print(f"Calendar response: {response}")
                    if response:
                        spoken = get_groq_response(
                            f"The user asked: \"{transcript}\"\nHere is the data: {_strip_emoji(response)}\n"
                            "Rephrase this as a natural spoken sentence."
                        ) or _strip_emoji(response)
                        # Flatten to one line for CLI safety — TTS path handles multi-line via Groq
                        fallback = "🎙️ " + "  ".join(l.strip() for l in response.split('\n') if l.strip())
                    else:
                        fallback = "⚠️ No calendar events found. Make sure Google Calendar is added to your Zapier AI Actions at zapier.com/ai-actions."
                else:
                    # General question — call Groq as Jarvis and reply as audio
                    print("General audio query — calling Groq.")
                    llm_reply = get_groq_response(transcript)
                    if llm_reply:
                        spoken = llm_reply
                        fallback = llm_reply
                    else:
                        fallback = f"⚠️ Couldn't get a response. You said: {transcript}"

                # Mark processed BEFORE sending
                processed.add(str(audio_file))
                state["processed"] = list(processed)
                save_state(state)

                if spoken:
                    print(f"Sending audio reply: {spoken[:80]}")
                    if not send_whatsapp_audio(spoken):
                        if fallback:
                            send_whatsapp(fallback)
                elif fallback:
                    send_whatsapp(fallback)
                    print("Sent text fallback to WhatsApp")
    finally:
        release_lock()

if __name__ == "__main__":
    main()
