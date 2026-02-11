"""
Local cache for vocabulary analysis results.
Eliminates duplicate API calls by storing previous AI responses.
"""
import json
import os
from datetime import datetime

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vocab_cache.json")


class CacheHandler:
    def __init__(self, cache_file: str = CACHE_FILE):
        self.cache_file = cache_file
        self.cache = self._load_cache()

    def _load_cache(self) -> dict:
        """Load cache from disk. Returns empty dict if file missing or corrupt."""
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
        return {}

    def _save_cache(self) -> None:
        """Write cache to disk. Silently fails on IO errors."""
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
        except IOError:
            pass

    @staticmethod
    def _normalize_key(text: str) -> str:
        """Normalize input for cache lookup: lowercase, strip, collapse whitespace."""
        return " ".join(text.lower().strip().split())

    def get(self, text: str) -> dict | None:
        """Look up cached analysis result. Returns None on miss."""
        key = self._normalize_key(text)
        entry = self.cache.get(key)
        if entry:
            entry["hit_count"] = entry.get("hit_count", 0) + 1
            self._save_cache()
            return entry["result"]
        return None

    def put(self, text: str, result: dict) -> None:
        """Store analysis result in cache."""
        key = self._normalize_key(text)
        self.cache[key] = {
            "result": result,
            "timestamp": datetime.now().isoformat(),
            "hit_count": 0,
        }
        self._save_cache()

    def remove(self, text: str) -> bool:
        """Remove a single entry from cache. Returns True if found and removed."""
        key = self._normalize_key(text)
        if key in self.cache:
            del self.cache[key]
            self._save_cache()
            return True
        return False

    def clear(self) -> int:
        """Clear all cache entries. Returns number of entries removed."""
        count = len(self.cache)
        self.cache = {}
        self._save_cache()
        return count
