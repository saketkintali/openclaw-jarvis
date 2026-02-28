# HEARTBEAT.md

## Every ~30 min (Windows Task Scheduler):
- Run: `python %USERPROFILE%\.openclaw\workspace\check_amazon.py`
- Fires any reminders whose time has passed

## Weekly cleanup:
Delete these if they exist — safe to remove, regenerated automatically:
- `%USERPROFILE%\.openclaw\workspace\__pycache__\` (entire folder)
- `%USERPROFILE%\.openclaw\workspace\proxy.log`
- `%USERPROFILE%\.openclaw\workspace\text-handler.log`
- Any `.pyc` files in the workspace
