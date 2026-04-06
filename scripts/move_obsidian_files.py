"""
One-time script: Move Obsidian files to consolidated folder.

Old:
  98. 数据库/01. Vocabulary/Vocabulary_*.md
  98. 数据库/02. Review Stats/Review_Stats.md
New:
  98. 数据库/Vocabulary Telegram/Vocabulary_*.md
  98. 数据库/Vocabulary Telegram/Review_Stats.md
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import base64
import aiohttp
from dotenv import load_dotenv

load_dotenv()

GITHUB_API = "https://api.github.com"
REPO = "NotebookOfCCC/Obsidian"
TOKEN = os.getenv("OBSIDIAN_GITHUB_TOKEN")
HEADERS = {
    "Authorization": f"token {TOKEN}",
    "Accept": "application/vnd.github.v3+json",
}

OLD_VOCAB_PATH = "98. 数据库/01. Vocabulary"
OLD_STATS_PATH = "98. 数据库/02. Review Stats"
NEW_PATH = "98. 数据库/01. Vocabulary Telegram"


async def get_file(filepath):
    url = f"{GITHUB_API}/repos/{REPO}/contents/{filepath}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=HEADERS) as resp:
            if resp.status == 404:
                return None, None
            data = await resp.json()
            content = base64.b64decode(data["content"]).decode("utf-8")
            return content, data["sha"]


async def put_file(filepath, content, message):
    url = f"{GITHUB_API}/repos/{REPO}/contents/{filepath}"
    # Check if file already exists
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=HEADERS) as resp:
            sha = None
            if resp.status == 200:
                data = await resp.json()
                sha = data["sha"]

    encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
    payload = {"message": message, "content": encoded}
    if sha:
        payload["sha"] = sha

    async with aiohttp.ClientSession() as session:
        async with session.put(url, headers=HEADERS, json=payload) as resp:
            if resp.status in (200, 201):
                print(f"  Created: {filepath}")
            else:
                text = await resp.text()
                print(f"  ERROR creating {filepath}: {resp.status} {text}")


async def delete_file(filepath, sha, message):
    url = f"{GITHUB_API}/repos/{REPO}/contents/{filepath}"
    payload = {"message": message, "sha": sha}
    async with aiohttp.ClientSession() as session:
        async with session.delete(url, headers=HEADERS, json=payload) as resp:
            if resp.status == 200:
                print(f"  Deleted: {filepath}")
            else:
                text = await resp.text()
                print(f"  ERROR deleting {filepath}: {resp.status} {text}")


async def list_files(folder_path):
    url = f"{GITHUB_API}/repos/{REPO}/contents/{folder_path}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=HEADERS) as resp:
            if resp.status == 404:
                return []
            data = await resp.json()
            return [(item["name"], item["path"]) for item in data if item["type"] == "file"]


async def main():
    # 1. List vocab files
    print(f"Listing files in {OLD_VOCAB_PATH}...")
    vocab_files = await list_files(OLD_VOCAB_PATH)
    print(f"Found {len(vocab_files)} vocab files")

    # 2. List stats files
    print(f"Listing files in {OLD_STATS_PATH}...")
    stats_files = await list_files(OLD_STATS_PATH)
    print(f"Found {len(stats_files)} stats files")

    all_files = [(OLD_VOCAB_PATH, name, path) for name, path in vocab_files] + \
                [(OLD_STATS_PATH, name, path) for name, path in stats_files]

    if not all_files:
        print("No files to move.")
        return

    # 3. Move each file: read → create at new path → delete old
    for old_folder, name, old_path in all_files:
        print(f"\nMoving {name}...")
        content, sha = await get_file(old_path)
        if content is None:
            print(f"  Skipped (not found)")
            continue

        new_filepath = f"{NEW_PATH}/{name}"
        await put_file(new_filepath, content, f"move: {name} to 01. Vocabulary Telegram folder")
        await delete_file(old_path, sha, f"move: {name} from {old_folder}")

    print(f"\nDone! All files moved to {NEW_PATH}/")


if __name__ == "__main__":
    asyncio.run(main())
