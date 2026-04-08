"""
Obsidian Vocabulary Sync Handler

Daily sync: Notion → Obsidian markdown files via GitHub API.
Each Notion database maps to one Vocabulary_NNN.md file.
Runs at 3:00 AM, full overwrite (not incremental).

SHA is fetched from directory listing (not file content) to avoid
the GitHub Contents API 1MB GET limit for large files.
"""

import os
import re
import base64
import logging
import aiohttp
from datetime import datetime

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
REPO = "NotebookOfCCC/Obsidian-Database"
BASE_PATH = "02. 数据库/01. Vocabulary Telegram"
MAX_RETRIES = 3


def _file_header(part: int) -> str:
    return f"""# Vocabulary Database - Part {part}

> Auto-synced from Notion daily at 3:00 AM.

| # | English | Chinese | Explanation | Example EN | Example ZH | Category | Date |
|---|---------|---------|-------------|------------|------------|----------|------|
"""


def _escape_cell(text: str) -> str:
    """Escape pipe and newline characters for markdown table cells."""
    if not text:
        return ""
    return text.replace("|", "\\|").replace("\n", " <br> ")


def _entry_to_row(entry: dict, row_num: int) -> str:
    """Convert a vocab entry dict to a markdown table row."""
    english = _escape_cell(entry.get("english", ""))
    chinese = _escape_cell(entry.get("chinese", ""))
    explanation = _escape_cell(entry.get("explanation", ""))
    example_en = _escape_cell(entry.get("example_en", ""))
    example_zh = _escape_cell(entry.get("example_zh", ""))
    category = _escape_cell(entry.get("category", "其他"))
    date_str = entry.get("date", "")
    return f"| {row_num} | {english} | {chinese} | {explanation} | {example_en} | {example_zh} | {category} | {date_str} |"


def build_file_content(entries: list[dict], part: int) -> str:
    """Build full markdown file content from a list of vocab entries."""
    rows = []
    for i, entry in enumerate(entries, 1):
        rows.append(_entry_to_row(entry, i))
    return _file_header(part) + "\n".join(rows) + "\n"


class ObsidianVocabSync:
    def __init__(self):
        self.token = os.getenv("OBSIDIAN_GITHUB_TOKEN")
        if not self.token:
            raise ValueError("OBSIDIAN_GITHUB_TOKEN not set")
        self.headers = {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json",
        }

    async def _get_dir_sha_map(self) -> dict[str, str]:
        """List directory and return {filename: sha} for all Vocabulary_NNN.md files.

        This avoids reading file content (which hits the 1MB GET limit).
        """
        url = f"{GITHUB_API}/repos/{REPO}/contents/{BASE_PATH}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self.headers) as resp:
                if resp.status == 404:
                    return {}
                if resp.status != 200:
                    return {}
                data = await resp.json()
                return {
                    item["name"]: item["sha"]
                    for item in data
                    if item["type"] == "file" and re.match(r"Vocabulary_\d+\.md$", item["name"])
                }

    async def _put_file(self, filepath: str, content: str, message: str, sha: str = None):
        """Write file content to GitHub."""
        for attempt in range(MAX_RETRIES):
            url = f"{GITHUB_API}/repos/{REPO}/contents/{filepath}"
            encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
            payload = {"message": message, "content": encoded}
            if sha:
                payload["sha"] = sha

            async with aiohttp.ClientSession() as session:
                async with session.put(url, headers=self.headers, json=payload) as resp:
                    if resp.status in (200, 201):
                        logger.info(f"Wrote {filepath} to GitHub")
                        return
                    elif resp.status == 409 and attempt < MAX_RETRIES - 1:
                        logger.warning(f"Conflict on {filepath}, retrying (attempt {attempt + 1})")
                        sha = None  # Force GitHub to resolve
                        continue
                    else:
                        text = await resp.text()
                        raise Exception(f"GitHub write error {resp.status}: {text}")

    async def sync_databases(self, database_entries: list[tuple[str, list[dict]]]):
        """Sync all Notion databases to Obsidian markdown files.

        Args:
            database_entries: list of (db_id, entries) tuples, in order.
                              Index determines file number: 0→001, 1→002, etc.
        """
        # Get existing file SHAs from directory listing (no content read)
        sha_map = await self._get_dir_sha_map()

        for i, (db_id, entries) in enumerate(database_entries):
            part = i + 1
            filename = f"Vocabulary_{part:03d}.md"
            filepath = f"{BASE_PATH}/{filename}"
            sha = sha_map.get(filename)

            if not entries:
                logger.info(f"Skipping {filename}: no entries in database {db_id[:8]}")
                continue

            content = build_file_content(entries, part)
            ts = datetime.now().strftime("%Y-%m-%d %H:%M")
            await self._put_file(
                filepath, content,
                f"daily-sync: {len(entries)} entries → {filename} ({ts})",
                sha=sha,
            )
            logger.info(f"Synced {filename}: {len(entries)} entries from DB {db_id[:8]}")
