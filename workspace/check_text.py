#!/usr/bin/env python3
"""Handle incoming WhatsApp text messages — bypass LLM for time/weather/email."""

import sys
import os
import asyncio
import subprocess
from pathlib import Path

# Reuse all logic from check_audio.py
sys.path.insert(0, str(Path(__file__).parent))
from check_audio import (
    classify_intent, fetch_weather, fetch_time, fetch_amazon_emails,
    fetch_gmail_zapier, fetch_calendar_zapier, create_calendar_event_zapier,
    parse_reminder_groq, save_reminder,
    get_groq_response, send_whatsapp, WHATSAPP_TARGET, get_ai_response
)

# Fix stdout for unicode
if sys.stdout.encoding != 'utf-8':
    sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', closefd=False)

AUDIO_KEYWORDS = {"audio", "voice", "speak", "spoken", "aloud"}


def strip_name_prefix(text):
    """Strip 'Jarvis' or 'jarvis' from the start so keyword detection works."""
    import re
    return re.sub(r'^[Jj]arvis[,\s]+', '', text).strip()

def wants_audio(text):
    words = set(text.lower().split())
    return bool(words & AUDIO_KEYWORDS)

def jarvis_speak_parts(parts):
    """Convert raw API data strings into natural Jarvis-style spoken sentences."""
    import re
    sentences = []
    for part in parts:
        # Time: "City, State: H:MM AM (Day, Mon DD) [TZ]"
        m = re.match(r'^(.+?):\s+(\d+:\d+\s+[AP]M)\s+\(.+?\)\s+\[.+?\]$', part)
        if m:
            city = m.group(1).split(',')[0].strip()
            sentences.append(f"The time in {city} is {m.group(2)}, sir.")
            continue
        # Weather: "City, State: Description emoji, XX.X°F, wind X.X mph"
        m = re.match(r'^(.+?):\s+(.+?),\s+([\d.]+)°F,\s+wind\s+([\d.]+)\s+mph$', part)
        if m:
            city = m.group(1).split(',')[0].strip()
            desc = re.sub(r'[^\w\s]', '', m.group(2)).strip()  # strip emoji
            temp = int(float(m.group(3)))
            wind = m.group(4)
            sentences.append(
                f"In {city}, the weather is {desc}, {temp} degrees Fahrenheit,"
                f" with winds at {wind} miles per hour, sir."
            )
            continue
        # Email or anything else — just prefix politely
        sentences.append(f"Regarding your request, sir: {part}")
    return " ".join(sentences)

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
    """Generate TTS audio via edge-tts, convert to OGG, send as WhatsApp audio."""
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

def main():
    if len(sys.argv) < 2:
        sys.exit(0)

    raw = sys.argv[1].strip()
    text = strip_name_prefix(raw)

    print(f"Text message: {raw!r} → stripped: {text!r}")

    audio = wants_audio(text)

    # Strip audio request phrases before location/keyword detection
    # e.g. "time in prague as audio" → "time in prague"
    import re
    clean = re.sub(r'\b(as\s+)?(audio|voice|spoken|speak|aloud)\b', '', text, flags=re.IGNORECASE)
    clean = re.sub(r'\s+', ' ', clean).strip()

    parts = []

    intent, location = classify_intent(clean)
    print(f"Intent: {intent}")

    if intent == "reminder":
        result = parse_reminder_groq(clean)
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
            spoken_confirm = get_groq_response(
                f"Confirm this reminder was just saved: {confirm}."
            ) or confirm
            parts.append(f"🔔 {spoken_confirm}")
        else:
            parts.append("⚠️ Couldn't parse that reminder. Try: 'remind me to call mom at 8:30 PM'.")
        print(f"Reminder: {result}")

    elif intent == "time":
        resp = fetch_time(location)
        if resp:
            parts.append(resp)
        print(f"Time: {resp}")

    elif intent == "weather":
        resp = fetch_weather(location)
        if resp:
            answer = get_groq_response(
                f"The user asked: \"{clean}\"\n"
                f"Current weather data: {resp}\n"
                "Answer their specific question using only this data. One concise sentence."
            ) or resp
            parts.append(answer)
        print(f"Weather: {resp}")

    elif intent == "email":
        _today_h = __import__("datetime").datetime.now().strftime("%B %d, %Y")
        _email_instr = (
            f"Today is {_today_h}. User request: \"{clean}\". "
            "Search Gmail accordingly. Include emails from any date if the user asks about older emails. "
            "Return up to 5 results, most recent first."
        )
        _read_words = {"read", "reads", "reading", "content", "body", "say", "says", "said"}
        _want_body = bool(set(clean.lower().split()) & _read_words)
        resp = fetch_gmail_zapier(_email_instr, want_body=_want_body)
        if resp:
            for line in resp.split("\n"):
                line = line.strip()
                if line:
                    parts.append(line)
        print(f"Email: {resp}")

    elif intent == "calendar_create":
        resp = create_calendar_event_zapier(clean)
        if resp:
            spoken_resp = get_groq_response(
                f"The user asked: \"{clean}\"\nResult: {resp}\n"
                "Confirm the event was created in one natural sentence."
            ) or resp
            parts.append(spoken_resp)
        else:
            parts.append("⚠️ Couldn't create the event. Try: 'create lunch tomorrow at 12pm'.")
        print(f"Calendar create: {resp}")

    elif intent == "calendar_find":
        resp = fetch_calendar_zapier(query=clean)
        print(f"Calendar: {resp}")
        if resp:
            # Pass raw events + original question to Groq — it answers the specific question
            # in one natural sentence (handles "at 3:30pm", "dinner only", "all events", etc.)
            answer = get_groq_response(
                f"The user asked: \"{clean}\"\n"
                f"Their calendar events: {resp}\n"
                "Answer their specific question based only on these events. One concise sentence."
            ) or resp
            parts.append(answer)
        else:
            parts.append("⚠️ No calendar events found. Make sure Google Calendar is added at zapier.com/ai-actions.")

    if not parts:
        if audio:
            # User wants audio but it's not a structured query — call LLM and speak the reply
            print("Not structured, but audio requested — calling LLM.")
            llm_reply = get_groq_response(clean)
            if llm_reply:
                print(f"LLM reply: {llm_reply[:80]}")
                send_whatsapp_audio(llm_reply)
                sys.exit(0)
            else:
                send_whatsapp("⚠️ Could not get a response. Please try again.")
                sys.exit(1)
        # General query — call Groq as Jarvis and reply as text
        print("Not structured, calling Groq for text reply.")
        llm_reply = get_groq_response(clean)
        if llm_reply:
            print(f"LLM text reply: {llm_reply[:80]}")
            send_whatsapp(llm_reply)
            sys.exit(0)
        else:
            send_whatsapp("⚠️ Could not get a response. Please try again.")
            sys.exit(1)

    if audio:
        combined = ". ".join(parts)
        spoken = jarvis_speak_parts(parts)
        print(f"Sending as audio: {spoken}")
        if not send_whatsapp_audio(spoken):
            send_whatsapp(f"⚠️ Audio failed. Here it is as text: {combined}")
    else:
        for part in parts:
            if send_whatsapp(part):
                print(f"Sent: {part}")

if __name__ == "__main__":
    main()
