"""
One-time migration script: Export all Notion vocabulary databases to Obsidian markdown files.

Maps 4 Notion databases → Vocabulary_001.md through Vocabulary_004.md

Usage: python migrate_to_obsidian.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import logging
from dotenv import load_dotenv
from notion_client import Client
from vocab.obsidian_vocab_handler import ObsidianVocabSync, build_file_content

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# 4 Notion databases in order → Vocabulary_001 to _004
DATABASE_IDS = [
    "2eb67845254b8042bfe7d0afbb7b233c",  # → Vocabulary_001.md
    "2fb67845254b8078994cccbc33eb8f71",  # → Vocabulary_002.md
    "30e67845254b8078994cccbc33eb8f71",  # → Vocabulary_003.md
    "32667845254b80ae995fd401cf58e7ee",  # → Vocabulary_004.md
]


def fetch_all_entries(client: Client, db_id: str) -> list[dict]:
    """Fetch all vocabulary entries from a Notion database."""
    entries = []
    cursor = None

    while True:
        kwargs = {"database_id": db_id, "page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor

        resp = client.databases.query(**kwargs)

        for page in resp.get("results", []):
            entry = parse_page(page)
            if entry:
                entries.append(entry)

        if resp.get("has_more"):
            cursor = resp.get("next_cursor")
        else:
            break

    return entries


def parse_page(page: dict) -> dict | None:
    """Parse a Notion page into a vocab entry dict."""
    properties = page.get("properties", {})
    entry = {}

    for prop_name, prop_value in properties.items():
        prop_type = prop_value.get("type")
        prop_name_lower = prop_name.lower()

        if prop_type == "title":
            title_content = prop_value.get("title", [])
            if title_content:
                title_text = title_content[0].get("plain_text", "")
                if title_text.startswith("__CONFIG_"):
                    return None
                entry["english"] = title_text

        elif prop_type == "rich_text":
            rich_text = prop_value.get("rich_text", [])
            content = rich_text[0].get("plain_text", "") if rich_text else ""

            if "chinese" in prop_name_lower or "中文" in prop_name_lower:
                entry["chinese"] = content
            elif "explanation" in prop_name_lower or "解释" in prop_name_lower:
                entry["explanation"] = content
            elif "example" in prop_name_lower or "例句" in prop_name_lower:
                # Notion stores example_en + example_zh combined
                entry["example_combined"] = content

        elif prop_type == "select":
            if "category" in prop_name_lower or "类别" in prop_name_lower:
                select_value = prop_value.get("select")
                if select_value:
                    entry["category"] = select_value.get("name", "")

        elif prop_type == "date":
            date_value = prop_value.get("date")
            if date_value:
                date_start = date_value.get("start", "")
                if prop_name_lower == "date" or "added" in prop_name_lower:
                    entry["date"] = date_start

    if not entry.get("english"):
        return None

    # Split combined example into EN and ZH if possible
    example = entry.pop("example_combined", "")
    if example:
        lines = example.split("\n", 1)
        entry["example_en"] = lines[0]
        entry["example_zh"] = lines[1] if len(lines) > 1 else ""
    else:
        entry["example_en"] = ""
        entry["example_zh"] = ""

    return entry


async def main():
    notion_key = os.getenv("NOTION_API_KEY")
    if not notion_key:
        print("ERROR: NOTION_API_KEY not set")
        return

    client = Client(auth=notion_key)
    sync = ObsidianVocabSync()

    database_entries = []
    for i, db_id in enumerate(DATABASE_IDS):
        part = i + 1
        logger.info(f"Fetching database {part}/4: {db_id[:8]}...")
        try:
            entries = fetch_all_entries(client, db_id)
            logger.info(f"  Found {len(entries)} entries")
            database_entries.append((db_id, entries))
        except Exception as e:
            logger.error(f"  Failed database {db_id[:8]}: {e}")
            database_entries.append((db_id, []))

    await sync.sync_databases(database_entries)
    logger.info("Migration complete!")


if __name__ == "__main__":
    asyncio.run(main())
