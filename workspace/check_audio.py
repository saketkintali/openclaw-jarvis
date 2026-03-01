#!/usr/bin/env python3
"""Audio pipeline — scans for new voice notes, transcribes, routes through Jarvis."""

import os
import sys
import json
import time
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from jarvis import (
    classify_intent, fetch_weather, fetch_time, fetch_nearby,
    fetch_gmail_zapier, fetch_calendar_zapier, create_calendar_event_zapier,
    parse_reminder_groq, save_reminder, fetch_movies_tmdb,
    get_groq_response, send_whatsapp, send_whatsapp_audio,
    _strip_emoji, WHATSAPP_TARGET, get_ai_response,
    check_due_reminders,
)

MEDIA_DIR  = Path(os.environ.get("USERPROFILE", ".")) / ".openclaw" / "media" / "inbound"
STATE_FILE = Path(__file__).parent / "audio_state.json"
LOCK_FILE  = Path(__file__).parent / "check_audio.lock"


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

                intent, location = classify_intent(transcript)

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
                    response = fetch_gmail_zapier(_email_instr)
                    print(f"Email response: {response}")
                    if response == "no_emails_found":
                        spoken = get_groq_response(
                            f"The user asked: \"{transcript}\"\n"
                            "Gmail returned no matching emails. Tell them there are none, in one natural sentence as Jarvis."
                        ) or "No matching emails found, sir."
                        fallback = "🎙️ " + spoken
                    elif response:
                        spoken = get_groq_response(
                            f"The user asked: \"{transcript}\"\nHere is the data: {response}\n"
                            "Rephrase this as a natural spoken sentence."
                        ) or response
                        fallback = "🎙️ " + "  ".join(l.strip() for l in response.split('\n') if l.strip())
                    else:
                        fallback = f"⚠️ Couldn't check Gmail. You said: {transcript}"
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
                elif intent == "nearby":
                    response = fetch_nearby(transcript, location)
                    print(f"Nearby response: {response}")
                    if response == "no_places_found":
                        spoken = get_groq_response(
                            f"The user asked: \"{transcript}\"\n"
                            "No matching places were found within 5km. Tell them in one natural sentence as Jarvis."
                        ) or "No matching places found nearby, sir."
                        fallback = "🎙️ " + spoken
                    elif response:
                        spoken = get_groq_response(
                            f"The user asked: \"{transcript}\"\nResults:\n{response}\n"
                            "Read just the place names. Skip addresses and opening hours. No intro, no filler. Be concise."
                        ) or response
                        fallback = "🎙️ " + "  ".join(l.strip() for l in response.split('\n') if l.strip().startswith("•"))
                    else:
                        fallback = "⚠️ Couldn't search nearby places right now."
                elif intent == "nutrition":
                    spoken = get_groq_response(
                        f"Nutrition question: {transcript}\n"
                        "Give specific calorie numbers. If multiple foods, read each item's calories then total. "
                        "No intro. Be concise.",
                        allow_knowledge=True,
                    )
                    if spoken:
                        fallback = spoken
                    else:
                        spoken = None
                        fallback = "⚠️ Couldn't get nutrition info right now."
                    print(f"Nutrition: {spoken}")
                elif intent == "movies":
                    response = fetch_movies_tmdb(transcript)
                    print(f"Movies response: {response}")
                    if response and (response.startswith("•") or "Recent movies" in response):
                        spoken = get_groq_response(
                            f"The user asked: \"{transcript}\"\nMovie data from TMDB:\n{response}\n"
                            "Answer their specific question directly. No caveats, no explanation. "
                            "If they used a singular word (last, latest, recent movie), say ONLY the title and year, e.g. 'Here, 2024, sir.' Nothing else. "
                            "If they used a plural word (recent movies, films, filmography), read only the titles and years."
                        ) or response
                        fallback = response
                    elif response:
                        spoken = response  # error message — speak as-is
                        fallback = response
                    else:
                        fallback = "⚠️ Couldn't find movie info right now."
                else:
                    # General question — call Groq as Jarvis and reply as audio
                    print("General audio query — calling Groq.")
                    llm_reply = get_groq_response(transcript, allow_knowledge=True)
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
