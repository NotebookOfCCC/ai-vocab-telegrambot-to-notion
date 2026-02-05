"""
YouTube Handler

Fetches videos from configured playlists and channels using YouTube Data API v3.
Supports both playlist IDs and channel handles (@username format).

Configuration via video_config.json:
{
  "playlists": [
    {"name": "...", "playlist_id": "PLxxxxx", "enabled": true},
    {"name": "...", "channel_handle": "@username", "enabled": true}
  ]
}

Features:
- Caches results for 24 hours to minimize API calls
- Automatically resolves channel handles to uploads playlist IDs
- Filters out private/deleted videos
- Random video selection from all enabled sources

Requires: google-api-python-client
API Key: Get from Google Cloud Console with YouTube Data API v3 enabled
"""
import json
import random
import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


class YouTubeHandler:
    """Handles YouTube API interactions for fetching videos."""

    def __init__(self, api_key: str, config_path: str = "video_config.json"):
        """Initialize YouTube handler.

        Args:
            api_key: YouTube Data API key
            config_path: Path to video_config.json
        """
        self.api_key = api_key
        self.config_path = config_path
        self.config = self._load_config()
        self._cache = {}  # key -> (videos, timestamp)
        self._channel_cache = {}  # handle -> uploads_playlist_id
        self._cache_duration = timedelta(hours=24)
        self._youtube = None

    def _get_youtube_client(self):
        """Get or create YouTube API client."""
        if self._youtube is None:
            try:
                from googleapiclient.discovery import build
                self._youtube = build("youtube", "v3", developerKey=self.api_key)
            except ImportError:
                logger.error("google-api-python-client not installed")
                return None
        return self._youtube

    def _load_config(self) -> dict:
        """Load video configuration from JSON file."""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            logger.warning(f"Config file not found: {self.config_path}")
            return {"playlists": []}
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in config: {e}")
            return {"playlists": []}

    def _is_cache_valid(self, cache_key: str) -> bool:
        """Check if cached data is still valid."""
        if cache_key not in self._cache:
            return False
        _, timestamp = self._cache[cache_key]
        return datetime.now() - timestamp < self._cache_duration

    def _get_uploads_playlist_id(self, channel_handle: str) -> Optional[str]:
        """Get the uploads playlist ID for a channel handle.

        Args:
            channel_handle: Channel handle like @business

        Returns:
            Uploads playlist ID or None
        """
        # Check cache
        if channel_handle in self._channel_cache:
            return self._channel_cache[channel_handle]

        youtube = self._get_youtube_client()
        if not youtube:
            return None

        try:
            # Remove @ if present
            handle = channel_handle.lstrip("@")

            # Search for channel by handle
            request = youtube.channels().list(
                part="contentDetails",
                forHandle=handle
            )
            response = request.execute()

            items = response.get("items", [])
            if items:
                uploads_id = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
                self._channel_cache[channel_handle] = uploads_id
                logger.info(f"Found uploads playlist {uploads_id} for {channel_handle}")
                return uploads_id

            logger.warning(f"No channel found for handle {channel_handle}")
            return None

        except Exception as e:
            logger.error(f"Error getting channel {channel_handle}: {e}")
            return None

    def fetch_playlist_videos(self, playlist_id: str, max_results: int = 50) -> list:
        """Fetch videos from a YouTube playlist.

        Args:
            playlist_id: YouTube playlist ID
            max_results: Maximum number of videos to fetch

        Returns:
            List of video dictionaries with title and video_id
        """
        # Check cache first
        if self._is_cache_valid(playlist_id):
            videos, _ = self._cache[playlist_id]
            logger.info(f"Using cached videos for playlist {playlist_id}")
            return videos

        youtube = self._get_youtube_client()
        if not youtube:
            return []

        try:
            videos = []
            next_page_token = None

            while len(videos) < max_results:
                request = youtube.playlistItems().list(
                    part="snippet",
                    playlistId=playlist_id,
                    maxResults=min(50, max_results - len(videos)),
                    pageToken=next_page_token
                )
                response = request.execute()

                for item in response.get("items", []):
                    snippet = item.get("snippet", {})
                    video_id = snippet.get("resourceId", {}).get("videoId")
                    title = snippet.get("title", "Untitled")

                    # Skip private/deleted videos
                    if video_id and title not in ["Private video", "Deleted video"]:
                        videos.append({
                            "title": title,
                            "video_id": video_id,
                            "channel": snippet.get("channelTitle", ""),
                            "published_at": snippet.get("publishedAt", "")
                        })

                next_page_token = response.get("nextPageToken")
                if not next_page_token:
                    break

            # Update cache
            self._cache[playlist_id] = (videos, datetime.now())
            logger.info(f"Fetched {len(videos)} videos from playlist {playlist_id}")
            return videos

        except Exception as e:
            logger.error(f"Error fetching playlist {playlist_id}: {e}")
            return []

    def get_random_video(self) -> Optional[dict]:
        """Get a random video from enabled playlists/channels.

        Returns:
            Dictionary with video info or None if no videos available
        """
        enabled_sources = [
            p for p in self.config.get("playlists", [])
            if p.get("enabled", True)
        ]

        if not enabled_sources:
            logger.warning("No enabled video sources configured")
            return None

        # Collect videos from all enabled sources
        all_videos = []
        for source in enabled_sources:
            source_name = source.get("name", "Unknown")

            # Get playlist ID - either directly or from channel handle
            playlist_id = source.get("playlist_id")
            if not playlist_id:
                channel_handle = source.get("channel_handle")
                if channel_handle:
                    playlist_id = self._get_uploads_playlist_id(channel_handle)

            if not playlist_id:
                logger.warning(f"No playlist ID for source: {source_name}")
                continue

            videos = self.fetch_playlist_videos(playlist_id)
            for video in videos:
                video["playlist_name"] = source_name
            all_videos.extend(videos)

        if not all_videos:
            logger.warning("No videos found in any source")
            return None

        # Return random video
        video = random.choice(all_videos)
        video["url"] = f"https://youtube.com/watch?v={video['video_id']}"
        return video

    def get_video_url(self, video_id: str) -> str:
        """Get full YouTube URL for a video ID."""
        return f"https://youtube.com/watch?v={video_id}"

    def refresh_cache(self) -> None:
        """Clear cache to force refresh on next fetch."""
        self._cache.clear()
        self._channel_cache.clear()
        logger.info("YouTube cache cleared")
