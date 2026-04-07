"""
GitHub Handler for Grammar Drill Bot

Reads Obsidian markdown files from a private GitHub repo.
Writes status updates back to .md files (daily sync).
Uses a temporary JSON buffer for intra-day tracking.

Two card table formats:
  - Grammar cards (01-07): fill-in-the-blank with Question/Answer/Wrong/Rule
  - Top Phrases (08): Chinese-to-English with Chinese Prompt/Keyword Hint/Answer/Example
"""

import os
import re
import json
import base64
import logging
import aiohttp
from datetime import datetime, date

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
REPO = "NotebookOfCCC/Obsidian-Database"
BASE_PATH = "01. Daily Reflection/05. Grammar Practice"

CATEGORY_FILES = {
    0: "01. Articles.md",
    1: "02. Tenses.md",
    2: "03. Prepositions.md",
    3: "04. Verb Forms.md",
    4: "05. Word Choice.md",
    5: "06. Sentence Structure.md",
    6: "07. Spelling.md",
    7: "08. Top Phrases.md",
}

CATEGORY_NAMES = {
    0: "Articles",
    1: "Tenses",
    2: "Prepositions",
    3: "Verb Forms",
    4: "Word Choice",
    5: "Sentence Structure",
    6: "Spelling",
    7: "Top Phrases",
}

BUFFER_FILE = f"{BASE_PATH}/.grammar_bot_buffer.json"
CONFIG_FILE = f"{BASE_PATH}/.grammar_bot_config.json"

MAX_RETRIES = 3

# Known status values — used to detect old vs new table format (with/without Chinese column)
_KNOWN_STATUSES = {"new", "active", "again", "good", "easy", "retired", ""}


class GitHubHandler:
    def __init__(self):
        self.token = os.getenv("OBSIDIAN_GITHUB_TOKEN")
        if not self.token:
            raise ValueError("OBSIDIAN_GITHUB_TOKEN not set")
        self.headers = {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json",
        }
        self._sha_cache = {}

    async def _get_file(self, filepath: str) -> tuple[str, str]:
        """Fetch file content and SHA from GitHub. Returns (content, sha)."""
        url = f"{GITHUB_API}/repos/{REPO}/contents/{filepath}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self.headers) as resp:
                if resp.status == 404:
                    raise FileNotFoundError(f"File not found: {filepath}")
                if resp.status != 200:
                    text = await resp.text()
                    raise Exception(f"GitHub API error {resp.status}: {text}")
                data = await resp.json()
                content = base64.b64decode(data["content"]).decode("utf-8")
                sha = data["sha"]
                self._sha_cache[filepath] = sha
                return content, sha

    async def _put_file(self, filepath: str, content: str, message: str):
        """Write file content back to GitHub with conflict retry."""
        for attempt in range(MAX_RETRIES):
            url = f"{GITHUB_API}/repos/{REPO}/contents/{filepath}"
            sha = self._sha_cache.get(filepath)
            if not sha:
                try:
                    _, sha = await self._get_file(filepath)
                except FileNotFoundError:
                    sha = None  # New file, no SHA needed

            encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
            payload = {
                "message": message,
                "content": encoded,
            }
            if sha:
                payload["sha"] = sha

            async with aiohttp.ClientSession() as session:
                async with session.put(url, headers=self.headers, json=payload) as resp:
                    if resp.status in (200, 201):
                        data = await resp.json()
                        self._sha_cache[filepath] = data["content"]["sha"]
                        logger.info(f"Updated {filepath} on GitHub")
                        return
                    elif resp.status == 409 and attempt < MAX_RETRIES - 1:
                        # Conflict — refresh SHA and retry
                        logger.warning(f"Conflict on {filepath}, retrying (attempt {attempt + 1})")
                        self._sha_cache.pop(filepath, None)
                        continue
                    else:
                        text = await resp.text()
                        raise Exception(f"GitHub write error {resp.status}: {text}")

    def _parse_table_row(self, row: str) -> list[str]:
        """Parse a markdown table row into cells."""
        cells = row.strip().strip("|").split("|")
        return [c.strip() for c in cells]

    def _is_separator_row(self, row: str) -> bool:
        """Check if a row is a table separator (|---|---|...)."""
        return bool(re.match(r"^\s*\|[\s\-:|]+\|", row))

    def parse_cards(self, content: str, is_phrases: bool = False) -> tuple[list[dict], str, str]:
        """
        Parse markdown file content into card dicts.
        Returns (cards, pre_table_content, post_table_content).
        """
        lines = content.split("\n")
        cards = []
        pre_table_lines = []
        post_table_lines = []
        table_started = False
        table_ended = False
        col_map = {}  # header name → column index

        base_col_count = 8

        for i, line in enumerate(lines):
            if table_ended:
                post_table_lines.append(line)
                continue

            if not table_started:
                if "|" in line and not self._is_separator_row(line):
                    cells = self._parse_table_row(line)
                    if len(cells) >= base_col_count and cells[0].strip() == "#":
                        table_started = True
                        col_map = {c.strip(): idx for idx, c in enumerate(cells)}
                        pre_table_lines.append(line)
                        continue
                pre_table_lines.append(line)
                continue

            if self._is_separator_row(line):
                pre_table_lines.append(line)
                continue

            if not line.strip() or "|" not in line:
                table_ended = True
                post_table_lines.append(line)
                continue

            cells = self._parse_table_row(line)
            if len(cells) < base_col_count:
                table_ended = True
                post_table_lines.append(line)
                continue

            card = self._cells_to_card(cells, is_phrases, col_map)
            if card:
                cards.append(card)

        return cards, "\n".join(pre_table_lines), "\n".join(post_table_lines)

    def _cells_to_card(self, cells: list[str], is_phrases: bool, col_map: dict = None) -> dict | None:
        """Convert table cells to a card dict using header-based column mapping."""
        try:
            card_num = cells[0]
            if not card_num.isdigit():
                return None

            def get(name, fallback_idx=None, default=""):
                """Get cell by column name from header, or fallback index."""
                if col_map and name in col_map:
                    idx = col_map[name]
                    return cells[idx].strip() if idx < len(cells) else default
                if fallback_idx is not None and fallback_idx < len(cells):
                    return cells[fallback_idx].strip()
                return default

            if is_phrases:
                card = {
                    "num": int(card_num),
                    "source": get("Source", 1),
                    "date": get("Date", 2),
                    "chinese_prompt": get("Chinese Prompt", 3),
                    "keyword_hint": get("Keyword Hint", 4),
                    "answer": get("Answer (Target Phrase)", 5) or get("Answer", 5),
                    "example_sentence": get("Example Sentence", 6),
                    "example_chinese": get("Example Chinese"),
                    "type": "phrase",
                }
            else:
                card = {
                    "num": int(card_num),
                    "source": get("Source", 1),
                    "date": get("Date", 2),
                    "question": get("Question", 3),
                    "answer": get("Answer", 4),
                    "wrong": get("Wrong", 5),
                    "rule": get("Rule", 6),
                    "chinese": get("Chinese"),
                    "example": get("Example"),
                    "example_chinese": get("Example Chinese"),
                    "type": "grammar",
                }

            status = get("Status", 7, "new").lower()
            if status == "active":
                status = "new"
            if status not in _KNOWN_STATUSES or not status:
                status = "new"
            card["status"] = status

            card["last_reviewed"] = get("Last Reviewed")
            card["next_review"] = get("Next Review")
            easy_streak = get("Easy Streak", default="0")
            card["easy_streak"] = int(easy_streak) if easy_streak.strip().isdigit() else 0

            return card
        except (IndexError, ValueError) as e:
            logger.warning(f"Failed to parse card row: {e}")
            return None

    def apply_buffer_to_cards(self, cards: list[dict], buffer: dict, filename: str) -> list[dict]:
        """Apply buffered status updates to cards."""
        file_buffer = buffer.get(filename, {})
        if not file_buffer:
            return cards

        for card in cards:
            card_key = str(card["num"])
            if card_key in file_buffer:
                update = file_buffer[card_key]
                card["status"] = update.get("status", card["status"])
                card["last_reviewed"] = update.get("last_reviewed", card["last_reviewed"])
                card["next_review"] = update.get("next_review", card["next_review"])
                card["easy_streak"] = update.get("easy_streak", card["easy_streak"])
                if "chinese" in update:
                    card["chinese"] = update["chinese"]
                if "example" in update:
                    card["example"] = update["example"]
                if "example_chinese" in update:
                    card["example_chinese"] = update["example_chinese"]

        return cards

    def cards_to_markdown(self, cards: list[dict], pre_table: str, post_table: str, is_phrases: bool) -> str:
        """Reconstruct the full markdown file with updated card data."""
        pre_lines = pre_table.split("\n")

        if is_phrases:
            header = "| # | Source | Date | Chinese Prompt | Keyword Hint | Answer (Target Phrase) | Example Sentence | Example Chinese | Status | Last Reviewed | Next Review | Easy Streak |"
            separator = "|---|--------|------|---------------|-------------|----------------------|-----------------|-----------------|--------|---------------|-------------|-------------|"
        else:
            header = "| # | Source | Date | Question | Answer | Wrong | Rule | Chinese | Example | Example Chinese | Status | Last Reviewed | Next Review | Easy Streak |"
            separator = "|---|--------|------|----------|--------|-------|------|---------|---------|-----------------|--------|---------------|-------------|-------------|"

        new_pre_lines = []
        replaced_header = False
        replaced_separator = False
        for line in pre_lines:
            if not replaced_header and "|" in line and "#" in line and not self._is_separator_row(line):
                new_pre_lines.append(header)
                replaced_header = True
            elif replaced_header and not replaced_separator and self._is_separator_row(line):
                new_pre_lines.append(separator)
                replaced_separator = True
            else:
                new_pre_lines.append(line)

        card_rows = []
        for card in cards:
            if is_phrases:
                row = (f"| {card['num']} | {card['source']} | {card['date']} | "
                       f"{card['chinese_prompt']} | {card['keyword_hint']} | "
                       f"{card['answer']} | {card['example_sentence']} | "
                       f"{card.get('example_chinese', '')} | "
                       f"{card['status']} | {card['last_reviewed']} | "
                       f"{card['next_review']} | {card['easy_streak']} |")
            else:
                row = (f"| {card['num']} | {card['source']} | {card['date']} | "
                       f"{card['question']} | {card['answer']} | {card['wrong']} | "
                       f"{card['rule']} | {card.get('chinese', '')} | "
                       f"{card.get('example', '')} | {card.get('example_chinese', '')} | "
                       f"{card['status']} | {card['last_reviewed']} | "
                       f"{card['next_review']} | {card['easy_streak']} |")
            card_rows.append(row)

        parts = ["\n".join(new_pre_lines)]
        if card_rows:
            parts.append("\n".join(card_rows))
        if post_table.strip():
            parts.append(post_table)
        else:
            parts.append("")

        return "\n".join(parts) + "\n"

    async def fetch_cards(self, week_number: int) -> tuple[list[dict], str, str, str]:
        """Fetch and parse cards for the given week number (0-7)."""
        filename = CATEGORY_FILES[week_number]
        filepath = f"{BASE_PATH}/{filename}"
        is_phrases = (week_number == 7)

        content, _sha = await self._get_file(filepath)
        cards, pre_table, post_table = self.parse_cards(content, is_phrases)

        logger.info(f"Fetched {len(cards)} cards from {filename}")
        return cards, pre_table, post_table, filepath

    async def fetch_phrase_cards(self) -> tuple[list[dict], str, str, str]:
        """Fetch Top Phrases cards (always file 08)."""
        return await self.fetch_cards(7)

    # ── Buffer operations (daily temp storage) ──

    async def load_buffer(self) -> dict:
        """Load the daily buffer from GitHub."""
        try:
            content, _sha = await self._get_file(BUFFER_FILE)
            return json.loads(content)
        except (FileNotFoundError, Exception):
            return {}

    async def save_buffer(self, buffer: dict):
        """Save the daily buffer to GitHub."""
        content = json.dumps(buffer, indent=2, ensure_ascii=False) + "\n"
        ts = self._timestamp()
        await self._put_file(BUFFER_FILE, content, f"grammar-bot buffer: {ts}")

    async def clear_buffer(self):
        """Clear the daily buffer."""
        await self.save_buffer({})

    # ── Daily sync: write buffer back to .md files ──

    def _timestamp(self) -> str:
        """Get current timestamp string for commit messages."""
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M")

    async def sync_buffer_to_markdown(self):
        """
        Apply all buffered status updates back to the .md files on GitHub.
        Called once daily (e.g., 3 AM). Clears buffer after successful sync.
        """
        buffer = await self.load_buffer()
        if not buffer:
            logger.info("No buffer data to sync")
            return

        ts = self._timestamp()
        for filename, card_updates in buffer.items():
            if not card_updates:
                continue

            filepath = f"{BASE_PATH}/{filename}"
            is_phrases = filename == "08. Top Phrases.md"

            try:
                content, _sha = await self._get_file(filepath)
                cards, pre_table, post_table = self.parse_cards(content, is_phrases)

                for card in cards:
                    card_key = str(card["num"])
                    if card_key in card_updates:
                        update = card_updates[card_key]
                        card["status"] = update.get("status", card["status"])
                        card["last_reviewed"] = update.get("last_reviewed", card["last_reviewed"])
                        card["next_review"] = update.get("next_review", card["next_review"])
                        card["easy_streak"] = update.get("easy_streak", card["easy_streak"])
                        if "chinese" in update:
                            card["chinese"] = update["chinese"]
                        if "example" in update:
                            card["example"] = update["example"]
                        if "example_chinese" in update:
                            card["example_chinese"] = update["example_chinese"]

                new_content = self.cards_to_markdown(cards, pre_table, post_table, is_phrases)
                commit_msg = f"grammar-bot sync: {len(card_updates)} cards in {filename} ({ts})"
                await self._put_file(filepath, new_content, commit_msg)
                logger.info(f"Synced {len(card_updates)} card updates to {filename}")

            except Exception as e:
                logger.error(f"Failed to sync {filename}: {e}")
                return

        await self.clear_buffer()
        logger.info("Daily sync complete, buffer cleared")

    # ── Config operations ──

    async def fetch_config(self) -> dict:
        """Fetch bot config from GitHub."""
        try:
            content, _sha = await self._get_file(CONFIG_FILE)
            return json.loads(content)
        except (FileNotFoundError, Exception):
            return {
                "push_hour": 9,
                "push_minute": 0,
                "grammar_count": 5,
                "phrase_count": 3,
                "paused": False,
            }

    async def save_config(self, config: dict):
        """Save bot config to GitHub."""
        content = json.dumps(config, indent=2) + "\n"
        ts = self._timestamp()
        await self._put_file(CONFIG_FILE, content, f"grammar-bot config: {ts}")
