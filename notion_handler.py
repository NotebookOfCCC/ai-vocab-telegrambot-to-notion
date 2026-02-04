"""
Notion Handler - Saves vocabulary entries to Notion database
"""
import re
import random
import logging
import time
from datetime import datetime, date
from notion_client import Client

logger = logging.getLogger(__name__)


class NotionHandler:
    def __init__(self, api_key: str, database_id: str, additional_database_ids: list = None):
        """Initialize Notion handler.

        Args:
            api_key: Notion API key
            database_id: Primary database ID (used for saving entries)
            additional_database_ids: Optional list of additional database IDs for review
                                    (combined with primary database when fetching)
        """
        self.client = Client(auth=api_key)
        self.database_id = database_id
        self._category_options = None

        # All database IDs for review (primary + additional)
        self.all_database_ids = [database_id]
        if additional_database_ids:
            self.all_database_ids.extend(additional_database_ids)

    def get_category_options(self) -> list:
        """Fetch existing category options from the database."""
        if self._category_options is not None:
            return self._category_options

        try:
            db = self.client.databases.retrieve(database_id=self.database_id)
            # Try to find category property
            properties = db.get("properties", {})
            for prop_name, prop_config in properties.items():
                if prop_config.get("type") == "select" and "category" in prop_name.lower():
                    options = prop_config.get("select", {}).get("options", [])
                    self._category_options = [opt["name"] for opt in options]
                    return self._category_options
            return []
        except Exception:
            return []

    def save_entry(self, entry: dict) -> dict:
        """
        Save a vocabulary entry to Notion database.

        Expected entry format:
        {
            "english": "word/phrase",
            "chinese": "中文翻译",
            "explanation": "解释",
            "example_en": "English example",
            "example_zh": "中文例句",
            "category": "类别",
            "date": "2024-01-01"
        }
        """
        # Build properties based on common Notion vocabulary database schema
        properties = {
            "English": {
                "title": [
                    {
                        "text": {
                            "content": entry.get("english", "")
                        }
                    }
                ]
            },
            "Chinese": {
                "rich_text": [
                    {
                        "text": {
                            "content": entry.get("chinese", "")
                        }
                    }
                ]
            },
            "Explanation": {
                "rich_text": [
                    {
                        "text": {
                            "content": entry.get("explanation", "")
                        }
                    }
                ]
            },
            "Example": {
                "rich_text": [
                    {
                        "text": {
                            "content": f"{entry.get('example_en', '')}\n{entry.get('example_zh', '')}"
                        }
                    }
                ]
            },
            "Category": {
                "select": {
                    "name": entry.get("category", "其他")
                }
            },
            "Date": {
                "date": {
                    "start": entry.get("date", "")
                }
            },
            "From": {
                "rich_text": [
                    {
                        "text": {
                            "content": "From Claude"
                        }
                    }
                ]
            }
        }

        try:
            response = self.client.pages.create(
                parent={"database_id": self.database_id},
                properties=properties
            )
            return {
                "success": True,
                "page_id": response["id"],
                "url": response.get("url", "")
            }
        except Exception as e:
            error_msg = str(e)
            # Try alternative property names if the first attempt fails
            if "property" in error_msg.lower() or "validation" in error_msg.lower():
                return self._save_with_auto_detect(entry)
            return {
                "success": False,
                "error": error_msg
            }

    def _save_with_auto_detect(self, entry: dict) -> dict:
        """Try to save by auto-detecting database schema."""
        try:
            db = self.client.databases.retrieve(database_id=self.database_id)
            db_properties = db.get("properties", {})

            properties = {}

            # Map entry fields to database properties
            field_mapping = {
                "english": ["english", "word", "phrase", "vocabulary", "title", "name"],
                "chinese": ["chinese", "中文", "translation", "meaning"],
                "explanation": ["explanation", "解释", "definition", "note", "notes"],
                "example": ["example", "例句", "sentence", "usage"],
                "category": ["category", "类别", "type", "tag"],
                "date": ["date", "日期", "created", "added"],
                "from": ["from", "source", "来源"]
            }

            for db_prop_name, db_prop_config in db_properties.items():
                prop_type = db_prop_config.get("type")
                prop_name_lower = db_prop_name.lower()

                # Title property (usually English word)
                if prop_type == "title":
                    properties[db_prop_name] = {
                        "title": [{"text": {"content": entry.get("english", "")}}]
                    }

                # Rich text properties
                elif prop_type == "rich_text":
                    content = ""
                    if any(kw in prop_name_lower for kw in field_mapping["chinese"]):
                        content = entry.get("chinese", "")
                    elif any(kw in prop_name_lower for kw in field_mapping["explanation"]):
                        content = entry.get("explanation", "")
                    elif any(kw in prop_name_lower for kw in field_mapping["example"]):
                        content = f"{entry.get('example_en', '')}\n{entry.get('example_zh', '')}"
                    elif any(kw in prop_name_lower for kw in field_mapping["from"]):
                        content = "From Claude"

                    if content:
                        properties[db_prop_name] = {
                            "rich_text": [{"text": {"content": content}}]
                        }

                # Select property (category)
                elif prop_type == "select":
                    if any(kw in prop_name_lower for kw in field_mapping["category"]):
                        properties[db_prop_name] = {
                            "select": {"name": entry.get("category", "其他")}
                        }

                # Date property
                elif prop_type == "date":
                    if any(kw in prop_name_lower for kw in field_mapping["date"]):
                        properties[db_prop_name] = {
                            "date": {"start": entry.get("date", "")}
                        }

            response = self.client.pages.create(
                parent={"database_id": self.database_id},
                properties=properties
            )
            return {
                "success": True,
                "page_id": response["id"],
                "url": response.get("url", "")
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def test_connection(self) -> dict:
        """Test the Notion connection and return database info."""
        try:
            db = self.client.databases.retrieve(database_id=self.database_id)
            title = ""
            if db.get("title"):
                title = db["title"][0].get("plain_text", "Untitled")

            properties = list(db.get("properties", {}).keys())

            return {
                "success": True,
                "database_title": title,
                "properties": properties
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def _lemmatize_word(self, word: str) -> str:
        """Lemmatize a single word by removing common suffixes."""
        word = word.lower()
        # Simple lemmatization: remove common suffixes
        # Order matters - check longer suffixes first
        suffixes = ['ying', 'ing', 'ied', 'ies', 'ed', 'es', 's']
        for suffix in suffixes:
            if word.endswith(suffix) and len(word) > len(suffix) + 2:
                # Handle doubling: running -> run, stopped -> stop
                stem = word[:-len(suffix)]
                if suffix in ('ing', 'ed') and len(stem) >= 2 and stem[-1] == stem[-2]:
                    stem = stem[:-1]
                # Handle -ied -> -y: carried -> carry
                if suffix == 'ied':
                    stem = stem + 'y'
                # Handle -ies -> -y: carries -> carry
                if suffix == 'ies':
                    stem = stem + 'y'
                return stem
        return word

    def _get_base_phrase(self, text: str) -> str:
        """Extract base phrase from text, lemmatizing each word."""
        # Remove /IPA/ and (pos.)
        base = re.sub(r'/[^/]+/', '', text).strip()
        base = re.sub(r'\([^)]*\)', '', base).strip().lower()

        # Lemmatize each word in the phrase
        words = base.split()
        lemmatized = [self._lemmatize_word(w) for w in words]
        return ' '.join(lemmatized)

    def _is_same_word(self, input_text: str, stored_text: str) -> bool:
        """Check if input and stored text refer to the same word/phrase.

        - "blow" matches "blow", "blowing", "blowed"
        - "blow" does NOT match "land a blow" (different phrase)
        - "landing a blow" matches "land a blow" (same base phrase)
        """
        input_base = self._get_base_phrase(input_text)
        stored_base = self._get_base_phrase(stored_text)

        # Compare base phrases directly
        # Both single words or both phrases must have same lemmatized form
        return input_base == stored_base

    def find_entry_by_english(self, text: str):
        """Search Notion database for an existing entry matching the English word/phrase.

        Returns the entry dict with english, chinese, date fields, or None if not found.
        Matches base words (blow = blowing) but not phrases containing the word
        (blow != land a blow).
        """
        try:
            # Normalize: strip phonetics/part-of-speech for search
            search_text = re.sub(r'/[^/]+/', '', text).strip()  # Remove /IPA/
            search_text = re.sub(r'\([^)]*\)', '', search_text).strip()  # Remove (pos.)

            response = self.client.databases.query(
                database_id=self.database_id,
                filter={
                    "property": "English",
                    "title": {
                        "contains": search_text
                    }
                },
                page_size=10  # Get more results to filter
            )

            for page in response["results"]:
                props = page["properties"]

                # Extract English title
                english = ""
                if props.get("English", {}).get("title"):
                    english = props["English"]["title"][0]["plain_text"]

                # Check if it's actually the same word (not just substring)
                if not self._is_same_word(text, english):
                    continue

                # Extract date
                date_val = ""
                if props.get("Date", {}).get("date"):
                    date_val = props["Date"]["date"].get("start", "")

                # Extract Chinese
                chinese = ""
                if props.get("Chinese", {}).get("rich_text"):
                    chinese = props["Chinese"]["rich_text"][0]["plain_text"]

                return {
                    "english": english,
                    "chinese": chinese,
                    "date": date_val,
                }
        except Exception as e:
            logger.error(f"Error checking for duplicate in Notion: {e}")

        return None

    def fetch_random_entries(self, count: int = 10) -> list:
        """Fetch random entries from the database (no smart selection)."""
        return self.fetch_entries_for_review(count, smart=False)

    def fetch_entries_for_review(self, count: int = 10, smart: bool = True, max_retries: int = 3) -> list:
        """
        Fetch entries for review with optional spaced repetition.
        Queries from ALL configured databases (primary + additional).

        Smart selection prioritizes:
        1. Never reviewed entries (Last Reviewed is empty)
        2. Entries not reviewed recently (older Last Reviewed date)
        3. Entries with lower review count
        4. Newer entries (by Date added) get slight priority
        """
        last_error = None

        for attempt in range(max_retries):
            try:
                # Query all entries from ALL databases
                all_entries = []

                for db_id in self.all_database_ids:
                    has_more = True
                    start_cursor = None

                    while has_more:
                        query_params = {"database_id": db_id, "page_size": 100}
                        if start_cursor:
                            query_params["start_cursor"] = start_cursor

                        response = self.client.databases.query(**query_params)
                        all_entries.extend(response.get("results", []))
                        has_more = response.get("has_more", False)
                        start_cursor = response.get("next_cursor")

                    logger.info(f"Fetched entries from database {db_id[:8]}...")

                if not all_entries:
                    logger.warning("Notion query returned no entries")
                    return []

                # Parse all entries
                parsed_entries = []
                for page in all_entries:
                    entry = self._parse_page_to_entry(page)
                    if entry:
                        parsed_entries.append(entry)

                if not smart:
                    # Random selection
                    selected = random.sample(parsed_entries, min(count, len(parsed_entries)))
                    return selected

                # Smart selection with spaced repetition scoring
                today = date.today()
                scored_entries = []

                for entry in parsed_entries:
                    score = self._calculate_review_priority(entry, today)
                    scored_entries.append((score, random.random(), entry))  # random for tie-breaking

                # Sort by score (higher = more urgent to review)
                scored_entries.sort(key=lambda x: (x[0], x[1]), reverse=True)

                # Select top entries
                selected = [entry for _, _, entry in scored_entries[:count]]
                logger.info(f"Successfully fetched {len(selected)} entries for review")
                return selected

            except Exception as e:
                last_error = e
                logger.warning(f"Notion API error on attempt {attempt + 1}/{max_retries}: {e}")
                if attempt < max_retries - 1:
                    # Wait before retry (exponential backoff: 2s, 4s)
                    wait_time = 2 ** (attempt + 1)
                    logger.info(f"Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)

        logger.error(f"Failed to fetch entries after {max_retries} attempts. Last error: {last_error}")
        return []

    def _calculate_review_priority(self, entry: dict, today: date) -> float:
        """
        Calculate review priority score. Higher = more urgent to review.

        Factors:
        - Next Review date: due/overdue = highest priority
        - Never reviewed: EQUAL priority to due words (so new words get mixed in)
        - Days since last review: more days = higher score
        - Review count: lower count = higher score
        """
        score = 0.0

        next_review = entry.get("next_review")
        last_reviewed = entry.get("last_reviewed")
        review_count = entry.get("review_count", 0) or 0
        date_added = entry.get("date")

        # Factor 1: Next Review date (highest weight)
        if next_review:
            try:
                next_date = datetime.strptime(next_review, "%Y-%m-%d").date()
                days_until_review = (next_date - today).days
                if days_until_review <= 0:
                    # Due or overdue: highest priority
                    score += 150 + abs(days_until_review) * 5  # More overdue = higher
                else:
                    # Not yet due: lower priority
                    score += max(0, 30 - days_until_review * 3)
            except (ValueError, TypeError):
                score += 50  # If can't parse, moderate priority
        elif not last_reviewed:
            # Never reviewed and no next_review set = new word
            # SAME priority as due words so new words get mixed in with reviews
            score += 150
        else:
            # Has been reviewed but no next_review set (legacy entries)
            # Fall back to old algorithm
            try:
                last_date = datetime.strptime(last_reviewed, "%Y-%m-%d").date()
                days_since_review = (today - last_date).days
                score += min(days_since_review * 2, 50)
            except (ValueError, TypeError):
                score += 50

        # Factor 2: Lower review count = higher score (max 30 points)
        score += max(0, 30 - review_count * 3)

        # Factor 3: Newer entries get slight bonus (max 20 points)
        if date_added:
            try:
                added_date = datetime.strptime(date_added, "%Y-%m-%d").date()
                days_since_added = (today - added_date).days
                if days_since_added <= 7:
                    score += 20
                elif days_since_added <= 30:
                    score += 10
            except (ValueError, TypeError):
                pass

        return score

    def update_review_stats(self, page_id: str, response: str = "good", knew: bool = None) -> dict:
        """
        Update review stats based on user's response.

        Args:
            page_id: Notion page ID
            response: "again", "good", or "easy"
            knew: Deprecated, kept for backward compatibility

        Scheduling:
            - Again: Next review = tomorrow, reset count to 0
            - Good: Next review = 2^count days (1, 2, 4, 8, 16, 32, 60 max)
            - Easy: Next review = 2^(count+1) days, count +2 (skip ahead)
        """
        from datetime import timedelta

        # Backward compatibility
        if knew is not None:
            response = "good" if knew else "again"

        try:
            # First get current review count
            page = self.client.pages.retrieve(page_id=page_id)
            properties = page.get("properties", {})

            current_count = 0
            for prop_name, prop_value in properties.items():
                if prop_value.get("type") == "number" and "review" in prop_name.lower() and "count" in prop_name.lower():
                    current_count = prop_value.get("number") or 0
                    break

            # Calculate next review date and new count based on response
            today = date.today()

            if response == "again":
                # Review tomorrow, reset count
                next_review = today + timedelta(days=1)
                new_count = 0
            elif response == "easy":
                # Longer interval, skip ahead
                interval_days = min(2 ** (current_count + 1), 90)
                next_review = today + timedelta(days=interval_days)
                new_count = current_count + 2
            else:  # "good" or default
                # Normal interval
                interval_days = min(2 ** current_count, 60)
                next_review = today + timedelta(days=interval_days)
                new_count = current_count + 1

            # Update properties
            update_props = {}

            # Find the exact property names and update
            for prop_name, prop_value in properties.items():
                prop_name_lower = prop_name.lower()
                prop_type = prop_value.get("type")

                if prop_type == "date" and "last" in prop_name_lower and "review" in prop_name_lower:
                    update_props[prop_name] = {
                        "date": {"start": today.isoformat()}
                    }
                elif prop_type == "date" and "next" in prop_name_lower and "review" in prop_name_lower:
                    update_props[prop_name] = {
                        "date": {"start": next_review.isoformat()}
                    }
                elif prop_type == "number" and "review" in prop_name_lower and "count" in prop_name_lower:
                    update_props[prop_name] = {
                        "number": new_count
                    }

            if update_props:
                self.client.pages.update(page_id=page_id, properties=update_props)

            return {"success": True, "next_review": next_review.isoformat()}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_review_stats(self, max_retries: int = 3) -> dict:
        """Get statistics about pending reviews from ALL configured databases."""
        last_error = None

        for attempt in range(max_retries):
            try:
                # Query all entries from ALL databases
                all_entries = []

                for db_id in self.all_database_ids:
                    has_more = True
                    start_cursor = None

                    while has_more:
                        query_params = {"database_id": db_id, "page_size": 100}
                        if start_cursor:
                            query_params["start_cursor"] = start_cursor

                        response = self.client.databases.query(**query_params)
                        all_entries.extend(response.get("results", []))
                        has_more = response.get("has_more", False)
                        start_cursor = response.get("next_cursor")

                today = date.today()
                overdue = 0
                due_today = 0
                new_words = 0
                total = len(all_entries)

                for page in all_entries:
                    entry = self._parse_page_to_entry(page)
                    if not entry:
                        continue

                    next_review = entry.get("next_review")
                    last_reviewed = entry.get("last_reviewed")

                    if not last_reviewed and not next_review:
                        # Never reviewed
                        new_words += 1
                    elif next_review:
                        try:
                            next_date = datetime.strptime(next_review, "%Y-%m-%d").date()
                            if next_date < today:
                                overdue += 1
                            elif next_date == today:
                                due_today += 1
                        except (ValueError, TypeError):
                            pass

                return {
                    "overdue": overdue,
                    "due_today": due_today,
                    "new_words": new_words,
                    "total": total
                }

            except Exception as e:
                last_error = e
                logger.warning(f"Notion API error getting stats on attempt {attempt + 1}/{max_retries}: {e}")
                if attempt < max_retries - 1:
                    wait_time = 2 ** (attempt + 1)
                    time.sleep(wait_time)

        logger.error(f"Failed to get review stats after {max_retries} attempts. Last error: {last_error}")
        return {"error": str(last_error)}

    def _parse_page_to_entry(self, page: dict) -> dict:
        """Parse a Notion page into an entry dictionary."""
        try:
            properties = page.get("properties", {})
            entry = {
                "page_id": page.get("id")  # Store page ID for updates
            }

            for prop_name, prop_value in properties.items():
                prop_type = prop_value.get("type")
                prop_name_lower = prop_name.lower()

                # Title property (English word)
                if prop_type == "title":
                    title_content = prop_value.get("title", [])
                    if title_content:
                        entry["english"] = title_content[0].get("plain_text", "")

                # Rich text properties
                elif prop_type == "rich_text":
                    rich_text = prop_value.get("rich_text", [])
                    content = rich_text[0].get("plain_text", "") if rich_text else ""

                    if "chinese" in prop_name_lower or "中文" in prop_name_lower:
                        entry["chinese"] = content
                    elif "explanation" in prop_name_lower or "解释" in prop_name_lower:
                        entry["explanation"] = content
                    elif "example" in prop_name_lower or "例句" in prop_name_lower:
                        entry["example"] = content

                # Select property (category)
                elif prop_type == "select":
                    if "category" in prop_name_lower or "类别" in prop_name_lower:
                        select_value = prop_value.get("select")
                        if select_value:
                            entry["category"] = select_value.get("name", "")

                # Date properties
                elif prop_type == "date":
                    date_value = prop_value.get("date")
                    if date_value:
                        date_start = date_value.get("start", "")
                        if "next" in prop_name_lower and "review" in prop_name_lower:
                            entry["next_review"] = date_start
                        elif "last" in prop_name_lower and "review" in prop_name_lower:
                            entry["last_reviewed"] = date_start
                        elif prop_name_lower == "date" or "added" in prop_name_lower:
                            entry["date"] = date_start

                # Number properties
                elif prop_type == "number":
                    if "review" in prop_name_lower and "count" in prop_name_lower:
                        entry["review_count"] = prop_value.get("number") or 0

            return entry if entry.get("english") else None

        except Exception:
            return None
