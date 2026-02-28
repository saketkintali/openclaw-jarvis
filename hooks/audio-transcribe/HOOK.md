---
name: audio-transcribe
description: "Transcribes WhatsApp voice messages immediately on receipt and sends AI response"
metadata: { "openclaw": { "emoji": "🎙️", "events": ["message:received"], "requires": { "bins": ["python"] } } }
---

# Audio Transcribe Hook

Fires instantly when a WhatsApp audio/voice message is received.
Runs check_audio.py to transcribe and get an AI response, then sends it back via WhatsApp.
