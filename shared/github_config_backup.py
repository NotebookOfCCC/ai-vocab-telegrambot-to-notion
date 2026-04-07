"""
GitHub Config Backup — best-effort backup of bot configs to Obsidian via GitHub API.

All configs stored under 02. 数据库/02. Bot Config/ in the Obsidian-Database repo.
"""

import os
import json
import base64
import logging
import aiohttp
from datetime import datetime

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
GITHUB_REPO = "NotebookOfCCC/Obsidian-Database"
GITHUB_TOKEN = os.getenv("OBSIDIAN_GITHUB_TOKEN")
BASE_CONFIG_PATH = "02. 数据库/01. Vocabulary Telegram"


async def save_config_to_github(config: dict, filename: str, bot_name: str) -> bool:
    """Best-effort backup config to GitHub.

    Args:
        config: Config dict to save
        filename: File name (e.g. '.news_bot_config.json')
        bot_name: Bot name for commit message (e.g. 'news-bot')
    """
    if not GITHUB_TOKEN:
        return False
    try:
        headers = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json",
        }
        file_path = f"{BASE_CONFIG_PATH}/{filename}"
        url = f"{GITHUB_API}/repos/{GITHUB_REPO}/contents/{file_path}"
        content_json = json.dumps(config, indent=2, ensure_ascii=False) + "\n"
        encoded = base64.b64encode(content_json.encode()).decode()

        async with aiohttp.ClientSession() as session:
            # Check if file exists (get SHA)
            sha = None
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    sha = data.get("sha")

            # Create or update
            payload = {
                "message": f"{bot_name} config: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                "content": encoded,
            }
            if sha:
                payload["sha"] = sha

            async with session.put(url, headers=headers, json=payload) as resp:
                if resp.status in (200, 201):
                    logger.info(f"{bot_name} config backed up to GitHub")
                    return True
                else:
                    logger.warning(f"{bot_name} GitHub config backup failed: {resp.status}")
                    return False
    except Exception as e:
        logger.error(f"{bot_name} GitHub config backup error: {e}")
        return False
