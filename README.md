# OpenClaw Jarvis

A personal WhatsApp AI assistant (Jarvis) powered by [OpenClaw](https://openclaw.ai) and Claude (Anthropic). Talk to it by text or voice and it handles your day — checking weather and time worldwide, reading Gmail, managing Google Calendar, finding places nearby, looking up movies and actors, answering nutrition questions, setting reminders, and answering general questions. Also ships a multi-agent dev team you can invoke from WhatsApp (`em:`, `arch:`, `dev:`, `jr:`). Uses Claude Sonnet as the native agent, Zapier MCP for Gmail and Google Calendar, OpenStreetMap for nearby search, TMDB for movie data, and local speech-to-text for voice messages.

---

## What it does

Send a WhatsApp message (text or voice) to your OpenClaw number. Claude classifies the intent, calls the right tool, and replies as Jarvis — as audio for voice messages, as text for text messages.

| Intent | What you say | What happens |
|--------|-------------|-------------|
| Weather | "weather in Chicago" / "should I bring a jacket?" | open-meteo → Claude answer |
| Time | "time in Tokyo" | worldtime API → formatted reply |
| Email | "any emails today?" / "read my last email" | Zapier Gmail → Claude summary |
| Calendar find | "what's on my calendar today?" | Zapier Google Calendar Find |
| Calendar create | "lunch with John tomorrow at noon" | Zapier Google Calendar Quick Add |
| Reminder | "remind me to call mom at 8pm" | saved locally, fires at that time |
| Nearby | "find me a good Italian restaurant" / "any pharmacies close by?" | Overpass API (OpenStreetMap) → up to 3 results with distance |
| Nutrition | "how many calories in a banana?" / "macros in chicken breast" | Claude from knowledge |
| Movies | "latest movies of Tom Hanks" / "films directed by Nolan" | TMDB API → formatted list |
| General | anything else | Claude answers directly |
| Voice reply | "tell me a joke aloud" | `check_speak.py` strips keyword → Claude answers → edge-tts voice note |
| Agent: EM | `em: design a habit tracker` | Engineering Manager decomposes into task packets |
| Agent: Architect | `arch: design a notifications system` | Architect produces DESIGN.md + data models |
| Agent: Senior Dev | `dev: add a delete endpoint` | Senior Dev implements the feature |
| Agent: Junior Dev | `jr: write tests for the storage module` | Junior Dev writes tests + docs |

See `workspace/DIAGRAM.txt` for the full architecture.

---

## Requirements

- [OpenClaw](https://openclaw.ai) — handles WhatsApp and the gateway
- Python 3.10+
- `pip install faster-whisper edge-tts av mcp`
- Anthropic account — [claude.ai/api](https://claude.ai/api) (API key required)
- Zapier account — for Gmail and Google Calendar
- TMDB account — free API key for movie queries

> **Windows only** — requires OpenClaw, Windows Task Scheduler, and Python 3.10+.

---

## Setup

**1. Install Python dependencies**
```
pip install faster-whisper edge-tts av mcp
```

**2. Copy workspace files**

Place all files from `workspace/` into:
```
%USERPROFILE%\.openclaw\workspace\
```
Create the directory if it doesn't exist. OpenClaw expects its scripts here.

**3. Set environment variables**

Open **System Properties → Environment Variables** (search "Edit the system environment variables" in Start). Add each variable from `.env.example` as a User variable.

**4. Configure Anthropic in OpenClaw**

OpenClaw supports Claude natively. In the OpenClaw setup wizard, select Anthropic as your provider and paste your API key. It will be saved to `~/.openclaw/agents/main/agent/auth.json`.

**5. Configure Zapier MCP (Gmail + Google Calendar)**

- Go to [mcp.zapier.com](https://mcp.zapier.com)
- Add these AI Actions: **Gmail: Find Email**, **Google Calendar Find Events**, **Google Calendar Quick Add Event**
- Copy your MCP connection URL from the dashboard
- Edit `workspace/config/mcporter.json` and replace `YOUR_ZAPIER_MCP_TOKEN` with that URL

**6. Install the audio hook**

Copy `hooks/audio-transcribe/` into:
```
%USERPROFILE%\.openclaw\hooks\
```
Then restart the OpenClaw gateway.

**7. Set up reminder heartbeat**

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
| `DEFAULT_LOCATION` | No | ZIP code or city for weather/time default (e.g. `10001`) |
| `DEFAULT_LOCATION_NAME` | No | Human-readable city name for that default (e.g. `New York`) |
| `TMDB_API_KEY` | No* | From [themoviedb.org/settings/api](https://www.themoviedb.org/settings/api) — required for movie queries |

> **Note:** The Anthropic API key is stored by OpenClaw in `auth.json`, not as an environment variable.

---

## How it works

OpenClaw runs Claude (claude-sonnet-4-6) as its native agent. When a WhatsApp message arrives, Claude reads it and decides whether to call a tool or answer from knowledge directly.

**Two MCP tool servers give Claude real-world data:**

- **jarvis-tools** (`mcp_server.py`, runs locally via stdio) — weather, time, movies, nearby places, reminders, voice output, and agent role invocation
- **Zapier MCP** — Gmail and Google Calendar (configured in `config/mcporter.json`)

**The Jarvis persona** comes from the workspace markdown files (`SOUL.md`, `AGENTS.md`, `IDENTITY.md`, etc.) that OpenClaw loads as the agent's system prompt automatically.

**Voice messages** go through a separate path: the `audio-transcribe` hook calls `check_audio.py`, which transcribes the audio using faster-whisper, then sends the transcript to Claude via the OpenClaw gateway API. Claude responds with text, which `check_audio.py` converts to an audio reply via edge-tts.

**Audio-on-demand** — when a text message contains "aloud", "out loud", "say it", etc., `check_speak.py` strips the keyword, gets Claude's response, and sends it back as a voice note via edge-tts. Claude itself replies `NO_REPLY` to avoid a duplicate text bubble.

**Multi-agent dev team** — `workspace/ai-learning/agent-roles/` contains system prompts for four roles: Engineering Manager, Architect, Senior Dev, Junior Dev. Each is exposed as an MCP tool (`run_engineering_manager`, `run_architect`, etc.) and triggered from WhatsApp via short prefixes (`em:`, `arch:`, `dev:`, `jr:`).

`heartbeat.py` runs every ~30 minutes via Windows Task Scheduler to fire due reminders.

See `workspace/DIAGRAM.txt` for the complete flow.
