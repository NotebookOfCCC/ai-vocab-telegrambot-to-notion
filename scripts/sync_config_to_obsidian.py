"""
One-time script: Sync all bot configs from Notion to Obsidian (GitHub).

Reads config from central CONFIG_DB_ID and writes to:
  02. 数据库/01. Vocabulary Telegram/.{bot}_bot_config.json

Usage:
  python scripts/sync_config_to_obsidian.py
"""

import os
import sys
import json
import asyncio
import base64
import aiohttp
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

from shared.config_handler import ConfigHandler

NOTION_KEY = os.getenv("NOTION_API_KEY")
CONFIG_DB_ID = os.getenv("CONFIG_DB_ID")
GITHUB_TOKEN = os.getenv("OBSIDIAN_GITHUB_TOKEN")

GITHUB_API = "https://api.github.com"
GITHUB_REPO = "NotebookOfCCC/Obsidian-Database"
BASE_PATH = "02. 数据库/01. Vocabulary Telegram"

# Config keys and their GitHub filenames
CONFIGS = {
    "__CONFIG_review_schedule__": ".review_bot_config.json",
    "__CONFIG_task_settings__": ".habit_bot_config.json",
    "__CONFIG_news_settings__": ".news_bot_config.json",
}


async def upload_to_github(session, headers, filename, data):
    """Upload a config file to GitHub."""
    file_path = f"{BASE_PATH}/{filename}"
    url = f"{GITHUB_API}/repos/{GITHUB_REPO}/contents/{file_path}"
    content_json = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    encoded = base64.b64encode(content_json.encode()).decode()

    # Check if file exists
    sha = None
    async with session.get(url, headers=headers) as resp:
        if resp.status == 200:
            result = await resp.json()
            sha = result.get("sha")

    payload = {
        "message": f"sync config from Notion: {filename}",
        "content": encoded,
    }
    if sha:
        payload["sha"] = sha

    async with session.put(url, headers=headers, json=payload) as resp:
        if resp.status in (200, 201):
            print(f"  OK {filename} uploaded")
            return True
        else:
            text = await resp.text()
            print(f"  FAIL {filename} failed ({resp.status}): {text[:200]}")
            return False


async def main():
    if not CONFIG_DB_ID:
        print("ERROR: CONFIG_DB_ID not set")
        return
    if not GITHUB_TOKEN:
        print("ERROR: OBSIDIAN_GITHUB_TOKEN not set")
        return

    handler = ConfigHandler(NOTION_KEY, CONFIG_DB_ID)

    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }

    print("Reading configs from Notion...")
    configs_to_upload = {}
    for config_key, filename in CONFIGS.items():
        data = handler.load(config_key)
        if data:
            print(f"  Found: {config_key} → {json.dumps(data, ensure_ascii=False)}")
            configs_to_upload[filename] = data
        else:
            print(f"  Not found: {config_key}")

    if not configs_to_upload:
        print("No configs to sync.")
        return

    print(f"\nUploading {len(configs_to_upload)} config(s) to GitHub...")
    async with aiohttp.ClientSession() as session:
        for filename, data in configs_to_upload.items():
            await upload_to_github(session, headers, filename, data)

    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
