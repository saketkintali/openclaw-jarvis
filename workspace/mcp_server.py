#!/usr/bin/env python3
"""Jarvis MCP tool server — exposes data-fetching tools to Claude via stdio MCP."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

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


if __name__ == "__main__":
    mcp.run(transport="stdio")
