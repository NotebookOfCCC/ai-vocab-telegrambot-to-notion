"""
Review Stats Handler — tracks daily review counts in a dedicated Notion database.

Database schema:
  - Date (Title): YYYY-MM-DD
  - Reviewed (Number): total reviews for the day
  - Again (Number): again count
  - Good (Number): good count
  - Easy (Number): easy count
"""
import logging
from datetime import date, timedelta
from notion_client import Client

logger = logging.getLogger(__name__)


class ReviewStatsHandler:
    def __init__(self, api_key: str, stats_db_id: str, timezone: str = "Europe/London"):
        self.client = Client(auth=api_key)
        self.stats_db_id = stats_db_id
        self.timezone = timezone

    def _find_page_for_date(self, date_str: str) -> str | None:
        """Find the page ID for a given date, or None."""
        try:
            response = self.client.databases.query(
                database_id=self.stats_db_id,
                filter={"property": "Date", "title": {"equals": date_str}},
                page_size=1,
            )
            results = response.get("results", [])
            return results[0]["id"] if results else None
        except Exception as e:
            logger.error(f"Error finding stats page for {date_str}: {e}")
            return None

    def _read_page(self, page_id: str) -> dict:
        """Read current counts from a stats page."""
        try:
            page = self.client.pages.retrieve(page_id=page_id)
            props = page.get("properties", {})
            return {
                "reviewed": (props.get("Reviewed") or {}).get("number") or 0,
                "again": (props.get("Again") or {}).get("number") or 0,
                "good": (props.get("Good") or {}).get("number") or 0,
                "easy": (props.get("Easy") or {}).get("number") or 0,
            }
        except Exception as e:
            logger.error(f"Error reading stats page {page_id}: {e}")
            return {"reviewed": 0, "again": 0, "good": 0, "easy": 0}

    def record_review(self, response: str) -> bool:
        """Increment today's counter for the given response type.

        Args:
            response: "again", "good", or "easy"

        Returns:
            True if successful
        """
        from datetime import datetime
        import zoneinfo
        today_str = datetime.now(zoneinfo.ZoneInfo(self.timezone)).date().isoformat()
        page_id = self._find_page_for_date(today_str)

        if page_id:
            counts = self._read_page(page_id)
        else:
            counts = {"reviewed": 0, "again": 0, "good": 0, "easy": 0}

        counts["reviewed"] += 1
        counts[response] = counts.get(response, 0) + 1

        try:
            props = {
                "Reviewed": {"number": counts["reviewed"]},
                "Again": {"number": counts["again"]},
                "Good": {"number": counts["good"]},
                "Easy": {"number": counts["easy"]},
            }
            if page_id:
                self.client.pages.update(page_id=page_id, properties=props)
            else:
                props["Date"] = {"title": [{"text": {"content": today_str}}]}
                self.client.pages.create(
                    parent={"database_id": self.stats_db_id},
                    properties=props,
                )
            return True
        except Exception as e:
            logger.error(f"Error recording review stat: {e}")
            return False

    def get_date_range(self, start: date, end: date) -> list[dict]:
        """Fetch stats for a date range (inclusive). Returns list of dicts sorted by date.

        Each dict: {"date": "YYYY-MM-DD", "reviewed": int, "again": int, "good": int, "easy": int}
        Missing days are filled with zeros.

        Uses individual date queries (one per day) since Notion Title property
        doesn't support range filters. Max ~31 queries for monthly report.
        """
        data = {}
        current = start
        while current <= end:
            d_str = current.isoformat()
            page_id = self._find_page_for_date(d_str)
            if page_id:
                counts = self._read_page(page_id)
                counts["date"] = d_str
                data[d_str] = counts
            current += timedelta(days=1)

        # Fill missing days with zeros
        result = []
        current = start
        while current <= end:
            d_str = current.isoformat()
            if d_str in data:
                result.append(data[d_str])
            else:
                result.append({"date": d_str, "reviewed": 0, "again": 0, "good": 0, "easy": 0})
            current += timedelta(days=1)
        return result

    def get_all_stats(self) -> list[dict]:
        """Fetch all stats from the database (for Obsidian sync).

        Returns list of dicts: {"date": "YYYY-MM-DD", "reviewed": int, "again": int, "good": int, "easy": int}
        """
        results = []
        cursor = None
        while True:
            kwargs = {"database_id": self.stats_db_id, "page_size": 100}
            if cursor:
                kwargs["start_cursor"] = cursor
            try:
                resp = self.client.databases.query(**kwargs)
            except Exception as e:
                logger.error(f"Error fetching all stats: {e}")
                break
            for page in resp.get("results", []):
                props = page.get("properties", {})
                title = props.get("Date", {}).get("title", [])
                if not title:
                    continue
                date_str = title[0].get("plain_text", "")
                if not date_str or date_str.startswith("__CONFIG_"):
                    continue
                results.append({
                    "date": date_str,
                    "reviewed": (props.get("Reviewed") or {}).get("number") or 0,
                    "again": (props.get("Again") or {}).get("number") or 0,
                    "good": (props.get("Good") or {}).get("number") or 0,
                    "easy": (props.get("Easy") or {}).get("number") or 0,
                })
            if resp.get("has_more"):
                cursor = resp.get("next_cursor")
            else:
                break
        return sorted(results, key=lambda x: x["date"])
