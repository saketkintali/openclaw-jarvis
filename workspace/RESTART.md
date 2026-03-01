# After Restart Checklist

## Auto-starts (nothing to do)
These start automatically when Windows logs in:
- **Groq Proxy** — silences OpenClaw's own reply so custom handlers control output (`start_groq_proxy.vbs` in Startup)

---

## Manual starts (run in this order)

### 1. Start OpenClaw Gateway
Open a terminal and run:
```
openclaw gateway
```
Keep this terminal open (or run it from a bat file / Windows Terminal).

### 2. Start ngrok
In a second terminal:
```
ngrok http 18789
```
Or if you have a reserved domain:
```
ngrok http --domain=YOUR_NGROK_DOMAIN 18789
```

---

## Verify everything is working
Send a WhatsApp message to your bot number and check:
- **"weather in seattle"** → should reply with weather text
- **"speak something funny"** → should reply with a Jarvis audio message
- **"who is Iron Man"** → should reply with a Jarvis text response

---

## Key files & ports
| Component       | Location / Port                                      |
|----------------|------------------------------------------------------|
| OpenClaw config | `%USERPROFILE%\.openclaw\openclaw.json`             |
| OpenClaw gateway| `http://127.0.0.1:18789`                            |
| Groq proxy      | `http://127.0.0.1:11435` → `https://api.groq.com`  |
| Workspace       | `%USERPROFILE%\.openclaw\workspace\`                |
| Bot scripts     | `check_text.py`, `check_audio.py`, `groq_proxy.py`  |

---

## If something breaks

**Bot not responding at all** → OpenClaw gateway is not running. Run `openclaw gateway`.

**"API rate limit reached" error** → Groq proxy is not running. Run:
```
pythonw %USERPROFILE%\.openclaw\workspace\groq_proxy.py
```

**Audio not playing inline** → Check that OGG conversion (PyAV) is installed:
```
pip install av
```

**Weather/time wrong city** → The bot uses geocoding. Say "weather in New York, US" to be specific.
