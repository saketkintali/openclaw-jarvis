# OpenClaw Jarvis

A WhatsApp AI assistant (Jarvis) that runs on [OpenClaw](https://openclaw.ai), using Groq for fast LLM responses, Zapier for Google Calendar and Gmail, and local speech-to-text for voice messages.

---

## What it does

Send a WhatsApp message (text or voice) to your OpenClaw number. Jarvis routes it to the right handler and replies — as audio for voice messages, as text for text messages.

| Intent | What you say | What happens |
|--------|-------------|-------------|
| Weather | "weather in Chicago" / "should I bring a jacket?" | open-meteo → Groq answer |
| Time | "time in Tokyo" | open-meteo timezone → formatted reply |
| Email | "any emails today?" / "read my last email" | Zapier Gmail Find |
| Calendar find | "what's on my calendar today?" | Zapier Google Calendar Find |
| Calendar create | "lunch with John tomorrow at noon" | Zapier Google Calendar Quick Add |
| Calendar delete | "delete breakfast tomorrow" | Zapier Google Calendar Delete |
| Reminder | "remind me to call mom at 8pm" | saved locally, fires at that time |
| General | anything else | Groq llama-3.3-70b as Jarvis |

See `workspace/DIAGRAM.txt` for the full architecture.

---

## Requirements

- [OpenClaw](https://openclaw.ai) — handles WhatsApp, Twilio, and the gateway
- Python 3.10+
- `pip install faster-whisper edge-tts av`
- Groq account — [console.groq.com](https://console.groq.com) (free tier works)
- Zapier account — for Google Calendar and Gmail actions
- ngrok (or any tunnel) — to expose the OpenClaw gateway to Twilio

> **Windows only** — requires OpenClaw, Windows Task Scheduler, and Python 3.10+.

---

## Setup

**1. Install Python dependencies**
```
pip install faster-whisper edge-tts av
```

**2. Copy workspace files**

Place all files from `workspace/` into:
```
%USERPROFILE%\.openclaw\workspace\
```
Create the directory if it doesn't exist. OpenClaw expects its scripts here.

**3. Set environment variables**

Open **System Properties → Environment Variables** (or search "Edit the system environment variables" in Start). Add each variable from `.env.example` as a User variable. Alternatively, set them in your shell before launching.

**4. Configure Zapier MCP**

- Go to [zapier.com/ai-actions](https://zapier.com/ai-actions)
- Add these AI Actions: **Gmail Find Email**, **Google Calendar Find Events**, **Google Calendar Quick Add Event**, **Google Calendar Delete Event**
- Open the **MCP** tab, copy the connection URL
- Edit `workspace/config/mcporter.json` and replace `YOUR_ZAPIER_MCP_TOKEN` with that URL

**5. Install OpenClaw hooks**

Copy `hooks/audio-transcribe/` and `hooks/text-handler/` into:
```
%USERPROFILE%\.openclaw\hooks\
```
Then restart the OpenClaw gateway.

**6. Set up reminder heartbeat**

Open **Task Scheduler** → Create Basic Task:
- Trigger: Daily, repeat every 30 minutes
- Action: Start a program → `python` → Arguments: `%USERPROFILE%\.openclaw\workspace\check_amazon.py`

This fires any reminders whose time has passed.

---

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `WHATSAPP_TARGET` | Yes | Your WhatsApp number, e.g. `+15551234567` |
| `GATEWAY_TOKEN` | Yes | From `openclaw.json` → `gateway.token` |
| `GROQ_API_KEY` | Yes | From [console.groq.com](https://console.groq.com) |
| `GMAIL_EMAIL` | Yes | Gmail address (for Zapier Gmail fallback via IMAP) |
| `GMAIL_PASSWORD` | Yes | Gmail App Password — NOT your login password |
| `DEFAULT_LOCATION` | No | ZIP code or city for weather/time fallback (default: `10001`) |
| `DEFAULT_LOCATION_NAME` | No | Human-readable city name (default: `New York`) |

---

## How it works

Every incoming WhatsApp message triggers one of two OpenClaw hooks:

- **text-handler** fires on text messages → runs `check_text.py`
- **audio-transcribe** fires on voice notes → runs `check_audio.py`, which calls `transcribe.py` (faster-whisper, tiny model, CPU)

Both scripts call `classify_intent()` (Groq llama-3.1-8b-instant, temp=0) to route the message, then fetch data from the appropriate source (open-meteo, Gmail IMAP, or Zapier MCP) and pass it to `get_groq_response()` (llama-3.3-70b-versatile) for a Jarvis-style answer.

`groq_proxy.py` runs on port 11435 and returns empty responses to OpenClaw's own LLM calls — this prevents the main agent from also replying to WhatsApp on top of the custom handlers.

`check_amazon.py` runs every ~30 minutes via Windows Task Scheduler to fire due reminders.

See `workspace/DIAGRAM.txt` for the complete flow.
