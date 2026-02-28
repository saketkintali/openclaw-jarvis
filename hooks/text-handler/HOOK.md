---
name: text-handler
description: "Intercepts WhatsApp text messages for time/weather/email and replies instantly via API — no LLM needed"
metadata: { "openclaw": { "emoji": "⚡", "events": ["message:received"], "requires": { "bins": ["python"] } } }
---

# Text Handler Hook

Fires on every incoming WhatsApp text message.
Passes the message content to check_text.py.
If the message is about time/weather/email, replies directly via API and exits.
Otherwise does nothing — the LLM handles it as normal.
