# OpenClaw Jarvis

A WhatsApp AI assistant (Jarvis) that runs on [OpenClaw](https://openclaw.ai), using Groq for fast LLM responses, Zapier for Gmail and Google Calendar, and local speech-to-text for voice messages.

---

## What it does

Send a WhatsApp message (text or voice) to your OpenClaw number. Groq classifies the intent and Jarvis replies — as audio for voice messages, as text for text messages.

| Intent | What you say | What happens |
|--------|-------------|-------------|
| Weather | "weather in Chicago" / "should I bring a jacket?" | open-meteo → Groq answer |
| Time | "time in Tokyo" | open-meteo timezone → formatted reply |
| Email | "any emails today?" / "read my last email" | Zapier Gmail → Groq summary |
| Calendar find | "what's on my calendar today?" | Zapier Google Calendar Find |
| Calendar create | "lunch with John tomorrow at noon" | Zapier Google Calendar Quick Add |
| Reminder | "remind me to call mom at 8pm" | saved locally, fires at that time |
| Nearby | "find me a good Italian restaurant" / "any pharmacies close by?" | Overpass API (OpenStreetMap) → up to 3 results with distance |
| Nutrition | "how many calories in a banana?" / "macros in chicken breast" | Groq llama-3.3-70b |
| General | anything else | Groq llama-3.3-70b as Jarvis |

See `workspace/DIAGRAM.txt` for the full architecture.

---

## Requirements

- [OpenClaw](https://openclaw.ai) — handles WhatsApp, Twilio, and the gateway
- Python 3.10+
- `pip install faster-whisper edge-tts av`
- Groq account — [console.groq.com](https://console.groq.com) (free tier works)
- Zapier account — for Gmail and Google Calendar
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

Open **System Properties → Environment Variables** (search "Edit the system environment variables" in Start). Add each variable from `.env.example` as a User variable.

**4. Configure Zapier MCP (Gmail + Google Calendar)**

- Go to [mcp.zapier.com](https://mcp.zapier.com)
- Add these AI Actions: **Gmail: Find Email**, **Google Calendar Find Events**, **Google Calendar Quick Add Event**
- Copy your MCP connection URL from the dashboard
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
- Action: Start a program → `python` → Arguments: `%USERPROFILE%\.openclaw\workspace\heartbeat.py`

This fires any reminders whose time has passed.

---

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `WHATSAPP_TARGET` | Yes | Your WhatsApp number, e.g. `+15551234567` |
| `GATEWAY_TOKEN` | Yes | From `openclaw.json` → `gateway.token` |
| `GROQ_API_KEY` | Yes | From [console.groq.com](https://console.groq.com) |
| `DEFAULT_LOCATION` | No | ZIP code or city for weather/time default (e.g. `10001`) |
| `DEFAULT_LOCATION_NAME` | No | Human-readable city name for that default (e.g. `New York`) |
| `USDA_API_KEY` | No | From [fdc.nal.usda.gov](https://fdc.nal.usda.gov/api-key-signup) — free, needed for nutrition lookups |

---

## How it works

OpenClaw's built-in agent is a generic chatbot — it has no access to weather APIs, Google Calendar, or Gmail. Python hooks are OpenClaw's extension mechanism: they intercept each message, classify intent using Groq (llama-3.1-8b-instant), fetch real data from the appropriate source, then generate a Jarvis-style reply via Groq (llama-3.3-70b-versatile). `groq_proxy.py` silences the built-in agent so only the hook's reply is sent — without it, both would fire and you'd get two WhatsApp messages every time.

Every incoming WhatsApp message triggers one of two OpenClaw hooks:

- **text-handler** fires on text messages → runs `check_text.py`
- **audio-transcribe** fires on voice notes → runs `check_audio.py`, which calls `transcribe.py` (faster-whisper, tiny model, CPU)

Both scripts call `classify_intent()` (Groq llama-3.1-8b-instant, temp=0) to route the message and extract the location (if any). The handler fetches real data — open-meteo for weather/time, Zapier MCP for Gmail and calendar, Overpass API (OpenStreetMap) for nearby places — then passes it to `get_groq_response()` (llama-3.3-70b-versatile) for a Jarvis-style answer.

Shared logic (intent classification, fetch functions, Groq calls, TTS) lives in `jarvis.py` and is imported by both pipelines.

`groq_proxy.py` runs on port 11435 and returns empty responses to OpenClaw's own LLM calls — this prevents the main agent from also replying to WhatsApp on top of the custom handlers.

`heartbeat.py` runs every ~30 minutes via Windows Task Scheduler to fire due reminders.

See `workspace/DIAGRAM.txt` for the complete flow.

> **Why not use OpenClaw's agent with tool calling?**
> Modern LLMs (including Groq's Llama 3.1+) support function/tool calling — where the LLM decides which tool to invoke and the framework executes it. This would eliminate hooks and `groq_proxy` entirely. Whether OpenClaw's agent loop supports the full cycle (define tools → LLM calls tool → execute → return result → final answer) is unclear. Python hooks implement that loop manually with full control in the meantime.
