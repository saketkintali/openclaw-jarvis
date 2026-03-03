#!/usr/bin/env python3
"""Handles text messages that request audio output — detects 'aloud/speak/say' and sends a voice message."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

AUDIO_KEYWORDS = [
    "aloud", "out loud", "say it", "read to me", "read it to me",
    "speak it", "say out loud", "tell me out loud",
]

# Regex to strip audio-trigger phrases before forwarding to Claude,
# so Claude doesn't see "aloud" and reply NO_REPLY.
_KW_RE = re.compile(
    r"\b(?:aloud|out\s+loud|say\s+it|read\s+(?:it\s+)?to\s+me|speak\s+it|say\s+out\s+loud|tell\s+me\s+out\s+loud)\b",
    re.IGNORECASE,
)


def is_audio_request(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in AUDIO_KEYWORDS)


def strip_audio_keywords(text: str) -> str:
    """Remove audio-trigger phrases so the cleaned message goes to Claude without triggering NO_REPLY."""
    cleaned = _KW_RE.sub("", text)
    return " ".join(cleaned.split()).strip()


def main():
    if len(sys.argv) < 2:
        return

    message = " ".join(sys.argv[1:])

    if not is_audio_request(message):
        return

    from jarvis import get_ai_response, send_whatsapp_audio, send_whatsapp

    # Strip audio keywords so Claude answers normally instead of replying NO_REPLY.
    clean_message = strip_audio_keywords(message)
    if not clean_message:
        clean_message = message  # fallback: use original if nothing left

    response = get_ai_response(clean_message)
    if not response or response.strip().upper() == "NO_REPLY":
        return

    if not send_whatsapp_audio(response):
        send_whatsapp(response)


if __name__ == "__main__":
    main()
