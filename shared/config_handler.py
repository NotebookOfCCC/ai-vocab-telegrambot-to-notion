"""
Central Config Handler — reads/writes bot configs to a shared Notion database.

Works with ANY Notion database regardless of property names.
Auto-detects the title property and first rich_text property.
Config pages are identified by their title = config_key (e.g. "__CONFIG_review_schedule__").
JSON data is stored in the first rich_text property.
"""

import json
import logging
from notion_client import Client

logger = logging.getLogger(__name__)


class ConfigHandler:
    def __init__(self, api_key: str, database_id: str):
        self.client = Client(auth=api_key)
        self.database_id = database_id
        self._title_prop = None
        self._text_prop = None
        self._detect_properties()

    def _detect_properties(self):
        """Auto-detect title and rich_text property names from the database schema."""
        try:
            db = self.client.databases.retrieve(database_id=self.database_id)
            props = db.get("properties", {})
            for name, prop in props.items():
                if prop.get("type") == "title" and not self._title_prop:
                    self._title_prop = name
                elif prop.get("type") == "rich_text" and not self._text_prop:
                    self._text_prop = name
            if self._title_prop and self._text_prop:
                logger.info(f"Config DB properties: title='{self._title_prop}', text='{self._text_prop}'")
            else:
                logger.error(f"Config DB missing properties: title={self._title_prop}, text={self._text_prop}")
        except Exception as e:
            logger.error(f"Failed to detect config DB properties: {e}")

    def load(self, config_key: str) -> dict | None:
        """Load config by key. Returns parsed dict or None."""
        if not self._title_prop or not self._text_prop:
            return None
        try:
            response = self.client.databases.query(
                database_id=self.database_id,
                filter={
                    "property": self._title_prop,
                    "title": {"equals": config_key}
                },
                page_size=1,
            )
            if response.get("results"):
                page = response["results"][0]
                props = page.get("properties", {})
                text_prop = props.get(self._text_prop, {})
                rich_text = text_prop.get("rich_text", [])
                if rich_text:
                    data_str = rich_text[0].get("plain_text", "")
                    return json.loads(data_str)
            return None
        except Exception as e:
            logger.error(f"Error loading config '{config_key}': {e}")
            return None

    def save(self, config_key: str, data: dict) -> bool:
        """Save config by key. Creates or updates the page. Returns True if successful."""
        if not self._title_prop or not self._text_prop:
            return False
        data_json = json.dumps(data)
        try:
            response = self.client.databases.query(
                database_id=self.database_id,
                filter={
                    "property": self._title_prop,
                    "title": {"equals": config_key}
                },
                page_size=1,
            )
            if response.get("results"):
                page_id = response["results"][0]["id"]
                self.client.pages.update(
                    page_id=page_id,
                    properties={
                        self._text_prop: {
                            "rich_text": [{"text": {"content": data_json}}]
                        }
                    }
                )
            else:
                self.client.pages.create(
                    parent={"database_id": self.database_id},
                    properties={
                        self._title_prop: {
                            "title": [{"text": {"content": config_key}}]
                        },
                        self._text_prop: {
                            "rich_text": [{"text": {"content": data_json}}]
                        }
                    }
                )
            logger.info(f"Saved config '{config_key}'")
            return True
        except Exception as e:
            logger.error(f"Error saving config '{config_key}': {e}")
            return False
