import json
import os
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, asdict, field
import subprocess
import datetime

# --- Data Class for Running Bot Info ---
@dataclass
class BotProcess:
    bot_name: str
    container_id: str
    bot_mode: str
    start_time: str

# --- Constants ---
PID_FILE_PATH = ".running_bots.json"

# --- Core Functions ---

def get_running_bots() -> List[BotProcess]:
    """
    Reads the process file and returns a list of BotProcess objects.
    Returns an empty list if the file doesn't exist or is empty.
    """
    if not os.path.exists(PID_FILE_PATH):
        return []
    try:
        with open(PID_FILE_PATH, "r") as f:
            data = json.load(f)
            return [BotProcess(**item) for item in data]
    except (json.JSONDecodeError, TypeError):
        # If file is empty or malformed, treat as no running bots
        return []

def save_running_bots(bots: List[BotProcess]):
    """
    Saves a list of BotProcess objects to the process file.
    """
    with open(PID_FILE_PATH, "w") as f:
        # Convert list of BotProcess objects to list of dicts
        json.dump([asdict(bot) for bot in bots], f, indent=4)

def add_running_bot(bot_name: str, container_id: str, bot_mode: str):
    """
    Adds a new running bot to the tracking file.
    """
    bots = get_running_bots()
    # Remove existing entry for the same bot name, if any
    bots = [b for b in bots if b.bot_name != bot_name]

    new_bot = BotProcess(
        bot_name=bot_name,
        container_id=container_id,
        bot_mode=bot_mode,
        start_time=datetime.datetime.utcnow().isoformat()
    )
    bots.append(new_bot)
    save_running_bots(bots)

def remove_running_bot(bot_name: str):
    """
    Removes a bot from the tracking file by its name.
    """
    bots = get_running_bots()
    bots_to_keep = [b for b in bots if b.bot_name != bot_name]
    save_running_bots(bots_to_keep)

def get_bot_by_name(bot_name: str) -> Optional[BotProcess]:
    """
    Finds a running bot by its name.
    """
    for bot in get_running_bots():
        if bot.bot_name == bot_name:
            return bot
    return None

def get_active_docker_container_ids() -> List[str]:
    """
    Returns a list of all currently running Docker container IDs.
    """
    try:
        result = subprocess.run(
            ["docker", "ps", "-q"],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip().splitlines()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []

def clear_all_running_bots():
    """
    Clears all bots from the tracking file by saving an empty list.
    """
    save_running_bots([])

def sync_and_get_running_bots() -> List[BotProcess]:
    """
    Reads the list of bots, checks which ones are still running in Docker,
    and cleans up stale entries from the file.
    """
    tracked_bots = get_running_bots()
    active_container_ids = get_active_docker_container_ids()

    live_bots = []
    stale_bots_found = False

    for bot in tracked_bots:
        # Check if the container ID is in the list of active containers
        # We check with startswith because 'docker ps' returns short IDs, but
        # 'docker exec' returns long IDs.
        is_alive = any(bot.container_id.startswith(short_id) for short_id in active_container_ids)
        if is_alive:
            live_bots.append(bot)
        else:
            stale_bots_found = True

    # If we found any stale entries, rewrite the file with only the live ones
    if stale_bots_found:
        save_running_bots(live_bots)

    return live_bots
