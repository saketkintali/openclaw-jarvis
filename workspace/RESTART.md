# After Restart Checklist

## Manual starts

### 1. Start OpenClaw Gateway
Open a terminal and run:
```
openclaw gateway --force
```
Keep this terminal open (or run it from a bat file / Windows Terminal).

### 2. Start ngrok
In a second terminal:
```
ngrok http 18789
```
This automatically uses your registered static domain (set up once at dashboard.ngrok.com → Domains).

---

## Verify everything is working
Send a WhatsApp message from your number and check:
- **"weather in seattle"** → should reply with weather text
- **"tell me a joke aloud"** → should reply with a voice message (audio bubble)
- **"who is Iron Man"** → should reply with a Jarvis text response

---

## Key files & ports
| Component        | Location / Port                                      |
|-----------------|------------------------------------------------------|
| OpenClaw config  | `%USERPROFILE%\.openclaw\openclaw.json`     |
| OpenClaw gateway | `http://127.0.0.1:18789`                            |
| Workspace        | `%USERPROFILE%\.openclaw\workspace\`        |
| Audio pipeline   | `check_audio.py` (polls media/inbound/, transcribes) |
| Speak pipeline   | `check_speak.py` (fires on "aloud" text messages)   |

---

## If something breaks

**Bot not responding at all** → OpenClaw gateway is not running. Run `openclaw gateway --force`.

**Audio messages not coming through** → Gateway probably needs restart. Run `openclaw gateway --force`.

**"tell me a joke aloud" not sending voice** → Gateway restart needed (recompiles hooks).

**Weather/time wrong city** → The bot uses geocoding. Say "weather in New York, US" to be specific.
