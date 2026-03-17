#!/usr/bin/env python3
"""Jarvis MCP tool server — exposes data-fetching tools to Claude via stdio MCP."""
import os
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

_WORKSPACE = Path(__file__).parent

from mcp.server.fastmcp import FastMCP
from jarvis import (
    fetch_time, fetch_nearby, fetch_movies_tmdb,
    save_reminder, check_due_reminders, DEFAULT_LOCATION_NAME,
)

mcp = FastMCP("jarvis-tools")


@mcp.tool()
def get_time(location: str = "") -> str:
    """Get the current local time for a city. Leave blank for the user's local time."""
    result = fetch_time(location or DEFAULT_LOCATION_NAME)
    return result or "Could not retrieve time."


@mcp.tool()
def get_movies(query: str) -> str:
    """Get the latest or recent movies for an actor or director. E.g. 'latest movie of Matt Damon' or 'films by James Cameron'."""
    result = fetch_movies_tmdb(query)
    return result or "Could not retrieve movie info from TMDB."


@mcp.tool()
def find_nearby(query: str, location: str = "") -> str:
    """Find nearby places such as restaurants, cafes, pharmacies, hospitals, bars, etc. Location defaults to the user's area."""
    result = fetch_nearby(query, location or None)
    return result or "Could not find nearby places."


@mcp.tool()
def set_reminder(task: str, remind_at: str) -> str:
    """Save a reminder for the user. remind_at must be ISO 8601 format: YYYY-MM-DDTHH:MM:00"""
    success = save_reminder(task, remind_at)
    return "Reminder saved." if success else "Failed to save reminder."


@mcp.tool()
def get_due_reminders() -> str:
    """Check if any reminders are currently due. Call this proactively when the user asks what's coming up."""
    result = check_due_reminders()
    return result or "No reminders are due right now."


@mcp.tool()
def speak(text: str) -> str:
    """Send a voice message to the user on WhatsApp. Call this when the user asks you to speak, say, read aloud, or wants an audio response."""
    from jarvis import send_whatsapp_audio
    success = send_whatsapp_audio(text)
    return "Voice message sent." if success else "Could not send voice message — replied as text instead."


_AGENT_ROLES_DIR = Path(os.environ.get("AGENT_ROLES_DIR", str(_WORKSPACE / "ai-learning" / "agent-roles")))


# ── File system tools (for agent roles to read/write/run) ─────────────────────

@mcp.tool()
def read_file(path: str) -> str:
    """Read a file. Path can be absolute or relative to the workspace directory."""
    p = Path(path) if Path(path).is_absolute() else _WORKSPACE / path
    if not p.exists():
        return f"File not found: {p}"
    try:
        return p.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading file: {e}"


@mcp.tool()
def write_file(path: str, content: str) -> str:
    """Write content to a file. Path can be absolute or relative to the workspace directory. Creates parent directories as needed."""
    p = Path(path) if Path(path).is_absolute() else _WORKSPACE / path
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Written: {p}"
    except Exception as e:
        return f"Error writing file: {e}"


@mcp.tool()
def run_command(command: str, cwd: str = "") -> str:
    """Run a shell command and return its output. Runs in the workspace directory by default. Use cwd to override."""
    working_dir = Path(cwd) if cwd else _WORKSPACE
    try:
        result = subprocess.run(
            command, shell=True, cwd=working_dir,
            capture_output=True, text=True, timeout=60
        )
        out = result.stdout.strip()
        err = result.stderr.strip()
        if result.returncode != 0:
            return f"Exit {result.returncode}\n{err or out}"
        return out or "(no output)"
    except subprocess.TimeoutExpired:
        return "Command timed out after 60 seconds."
    except Exception as e:
        return f"Error: {e}"


def _run_role(role_file: str, task: str) -> str:
    from jarvis import get_ai_response
    prompt_path = _AGENT_ROLES_DIR / role_file
    if not prompt_path.exists():
        return f"Role file not found: {role_file}"
    instructions = prompt_path.read_text(encoding="utf-8")
    result = get_ai_response(task, instructions=instructions)
    return result or "No response from agent."


@mcp.tool()
def run_engineering_manager(requirement: str) -> str:
    """Invoke the Engineering Manager (Alex) to decompose a product requirement into task packets for the team. Pass the full feature or project requirement."""
    return _run_role("engineering-manager.prompt.md", requirement)


@mcp.tool()
def run_architect(task: str) -> str:
    """Invoke the Architect to design a system — data models, API contracts, component structure — before any code is written. Pass the feature or system to design."""
    return _run_role("architect.prompt.md", task)


@mcp.tool()
def run_senior_dev(task: str) -> str:
    """Invoke the Senior Developer to implement a feature or API. Pass the task description and any relevant context (file paths, acceptance criteria)."""
    return _run_role("senior-dev.prompt.md", task)


@mcp.tool()
def run_junior_dev(task: str) -> str:
    """Invoke the Junior Developer for tests, docs, small bug fixes, or well-defined tasks. Pass the specific task."""
    return _run_role("junior-dev.prompt.md", task)


if __name__ == "__main__":
    mcp.run(transport="stdio")
