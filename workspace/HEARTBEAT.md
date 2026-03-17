# HEARTBEAT.md

## Every ~30 min (Windows Task Scheduler):
- Run: `python %USERPROFILE%\.openclaw\workspace\heartbeat.py`
- Fires any reminders whose time has passed

## Weekly (once a week):
- Check calendar for upcoming events and send WhatsApp summary

## Weekly cleanup (once a week):
Delete these if they exist — they are safe to remove and regenerate automatically:
- `%USERPROFILE%\.openclaw\workspace\__pycache__\` (entire folder)
- `%USERPROFILE%\.openclaw\workspace\proxy.log`
- `%USERPROFILE%\.openclaw\workspace\text-handler.log`
- Any `.pyc` files in the workspace
- Any files matching `*.tmp` or `*.bak` in the workspace
