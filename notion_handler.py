"""
Notion Handler - Saves vocabulary entries to Notion database
"""
import random
from notion_client import Client


class NotionHandler:
    def __init__(self, api_key: str, database_id: str):
        self.client = Client(auth=api_key)
        self.database_id = database_id
        self._category_options = None

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

    def fetch_random_entries(self, count: int = 10) -> list:
        """Fetch random entries from the database."""
        try:
            # Query all entries from the database
            all_entries = []
            has_more = True
            start_cursor = None

            while has_more:
                query_params = {"database_id": self.database_id, "page_size": 100}
                if start_cursor:
                    query_params["start_cursor"] = start_cursor

                response = self.client.databases.query(**query_params)
                all_entries.extend(response.get("results", []))
                has_more = response.get("has_more", False)
                start_cursor = response.get("next_cursor")

            if not all_entries:
                return []

            # Randomly select entries
            selected = random.sample(all_entries, min(count, len(all_entries)))

            # Parse entries into dictionaries
            parsed_entries = []
            for page in selected:
                entry = self._parse_page_to_entry(page)
                if entry:
                    parsed_entries.append(entry)

            return parsed_entries

        except Exception as e:
            return []

    def _parse_page_to_entry(self, page: dict) -> dict:
        """Parse a Notion page into an entry dictionary."""
        try:
            properties = page.get("properties", {})
            entry = {}

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

            return entry if entry.get("english") else None

        except Exception:
            return None
