#!/usr/bin/env python3
"""Audio pipeline — scans for new voice notes, transcribes, passes to Claude via OpenClaw gateway."""

import os
import sys
import json
import time
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from jarvis import (
    send_whatsapp, get_ai_response,
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

                # Pass transcript to Claude via OpenClaw gateway — Claude handles intent + MCP tools
                response = get_ai_response(transcript)
                print(f"Claude response: {response[:120] if response else None}")

                # Mark processed before sending
                processed.add(str(audio_file))
                state["processed"] = list(processed)
                save_state(state)

                if response and response.strip().upper() != "NO_REPLY":
                    # Always reply with text — audio replies are only for explicit "aloud/speak" requests
                    send_whatsapp(response)
                elif not response:
                    send_whatsapp("Sorry, I couldn't process that audio message.")
            else:
                print(f"Transcription failed for {audio_file.name}")
                processed.add(str(audio_file))
                state["processed"] = list(processed)
                save_state(state)
    finally:
        release_lock()

if __name__ == "__main__":
    main()
