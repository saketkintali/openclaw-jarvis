"""Heartbeat script — fires due reminders. Run via Windows Task Scheduler every ~30 min."""
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

try:
    from jarvis import check_due_reminders
    check_due_reminders()
except Exception as _e:
    print(f"Reminder check error: {_e}")
