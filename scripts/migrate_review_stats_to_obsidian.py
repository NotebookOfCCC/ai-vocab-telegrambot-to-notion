"""
One-time migration: Export all review stats from Notion to Obsidian markdown.

Usage:
    python migrate_review_stats_to_obsidian.py

Requires: NOTION_API_KEY, REVIEW_STATS_DB_ID, OBSIDIAN_GITHUB_TOKEN in .env
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from dotenv import load_dotenv
from notion_client import Client
from review.obsidian_review_stats_handler import ObsidianReviewStatsHandler

load_dotenv()

NOTION_KEY = os.getenv("NOTION_API_KEY")
REVIEW_STATS_DB_ID = os.getenv("REVIEW_STATS_DB_ID") or "32e67845254b80c09cbcfb94656bed5e"


def fetch_all_stats_from_notion() -> list[dict]:
    """Fetch all review stats pages from Notion database."""
    client = Client(auth=NOTION_KEY)
    all_stats = []
    has_more = True
    start_cursor = None

    while has_more:
        kwargs = {
            "database_id": REVIEW_STATS_DB_ID,
            "page_size": 100,
            "sorts": [{"property": "Date", "direction": "ascending"}],
        }
        if start_cursor:
            kwargs["start_cursor"] = start_cursor

        response = client.databases.query(**kwargs)
        results = response.get("results", [])
        has_more = response.get("has_more", False)
        start_cursor = response.get("next_cursor")

        for page in results:
            props = page.get("properties", {})
            # Get date from title
            title_parts = (props.get("Date") or {}).get("title", [])
            if not title_parts:
                continue
            date_str = title_parts[0].get("text", {}).get("content", "")
            if not date_str or date_str.startswith("__CONFIG_"):
                continue

            reviewed = (props.get("Reviewed") or {}).get("number") or 0
            again = (props.get("Again") or {}).get("number") or 0
            good = (props.get("Good") or {}).get("number") or 0
            easy = (props.get("Easy") or {}).get("number") or 0

            all_stats.append({
                "date": date_str,
                "reviewed": reviewed,
                "again": again,
                "good": good,
                "easy": easy,
            })

    return all_stats


async def main():
    print("Fetching review stats from Notion...")
    stats = fetch_all_stats_from_notion()
    print(f"Found {len(stats)} days of review stats")

    if not stats:
        print("No stats to migrate.")
        return

    # Show first and last dates
    print(f"Date range: {stats[0]['date']} to {stats[-1]['date']}")
    total_reviews = sum(s["reviewed"] for s in stats)
    print(f"Total reviews: {total_reviews}")

    print("\nWriting to Obsidian...")
    handler = ObsidianReviewStatsHandler()
    await handler.bulk_upsert(stats)
    print(f"Done! Migrated {len(stats)} days to Obsidian.")


if __name__ == "__main__":
    asyncio.run(main())
