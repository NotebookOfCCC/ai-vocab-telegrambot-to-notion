"""
Digest Handler — fetches follow-builders feeds and generates AI summaries.

Feed URLs (GitHub CDN, free, updated daily by GitHub Actions):
- feed-x.json: 25 AI builders' tweets (24h lookback)
- feed-podcasts.json: 6 AI podcasts (14-day lookback)
- feed-blogs.json: Anthropic + Claude blogs (72h lookback)
"""

import logging
import aiohttp
import anthropic
from datetime import datetime

logger = logging.getLogger(__name__)

FEED_BASE = "https://raw.githubusercontent.com/zarazhangrui/follow-builders/main"
FEED_URLS = {
    "x": f"{FEED_BASE}/feed-x.json",
    "podcasts": f"{FEED_BASE}/feed-podcasts.json",
    "blogs": f"{FEED_BASE}/feed-blogs.json",
}


class DigestHandler:
    def __init__(self, anthropic_key: str):
        self.client = anthropic.Anthropic(api_key=anthropic_key)

    async def fetch_feeds(self) -> dict:
        """Fetch all 3 feeds from GitHub CDN. Returns dict with x/podcasts/blogs keys."""
        feeds = {}
        async with aiohttp.ClientSession() as session:
            for name, url in FEED_URLS.items():
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                        if resp.status == 200:
                            feeds[name] = await resp.json(content_type=None)
                        else:
                            logger.warning(f"Feed {name} returned {resp.status}")
                            feeds[name] = None
                except Exception as e:
                    logger.error(f"Error fetching {name} feed: {e}")
                    feeds[name] = None
        return feeds

    def _build_full_digest(self, feeds: dict) -> str | None:
        """Build a formatted full-content digest (no AI, free)."""
        today = datetime.now().strftime("%b %d, %Y")
        parts = [f"📰 AI Builders Daily — {today}"]

        # Podcasts
        podcasts = feeds.get("podcasts", {})
        if podcasts and podcasts.get("podcasts"):
            parts.append("\n🎙 PODCASTS")
            for pod in podcasts["podcasts"][:5]:
                name = pod.get("name", "")
                title = pod.get("title", "")
                url = pod.get("url", "")
                parts.append(f"• {name}: {title}\n  🔗 {url}")

        # X/Twitter
        x_data = feeds.get("x", {})
        if x_data and x_data.get("x"):
            parts.append("\n💬 X / TWITTER")
            for builder in x_data["x"]:
                name = builder.get("name", "")
                tweets = builder.get("tweets", [])
                if not tweets:
                    continue
                for tweet in tweets[:2]:
                    text = tweet.get("text", "")[:200]
                    url = tweet.get("url", "")
                    parts.append(f"• {name}: {text}\n  🔗 {url}")

        # Blogs
        blogs = feeds.get("blogs", {})
        if blogs and blogs.get("blogs"):
            parts.append("\n📝 BLOGS")
            for blog in blogs["blogs"][:5]:
                name = blog.get("name", "")
                title = blog.get("title", "")
                url = blog.get("url", "")
                parts.append(f"• {name}: {title}\n  🔗 {url}")

        if len(parts) <= 1:
            return None
        return "\n".join(parts)

    def _build_raw_content(self, feeds: dict) -> str:
        """Build raw content string from feeds for AI summarization."""
        parts = []

        # Podcasts
        podcasts = feeds.get("podcasts", {})
        if podcasts and podcasts.get("podcasts"):
            parts.append("=== PODCASTS ===")
            for pod in podcasts["podcasts"][:5]:
                title = pod.get("title", "")
                name = pod.get("name", "")
                url = pod.get("url", "")
                transcript = pod.get("transcript", "")[:3000]
                parts.append(f"\n[{name}] {title}\nURL: {url}\nTranscript excerpt: {transcript}")

        # X/Twitter
        x_data = feeds.get("x", {})
        if x_data and x_data.get("x"):
            parts.append("\n=== X / TWITTER ===")
            for builder in x_data["x"]:
                name = builder.get("name", "")
                tweets = builder.get("tweets", [])
                if not tweets:
                    continue
                parts.append(f"\n[{name}]")
                for tweet in tweets[:3]:
                    text = tweet.get("text", "")
                    url = tweet.get("url", "")
                    parts.append(f"- {text}\n  {url}")

        # Blogs
        blogs = feeds.get("blogs", {})
        if blogs and blogs.get("blogs"):
            parts.append("\n=== BLOGS ===")
            for blog in blogs["blogs"][:5]:
                title = blog.get("title", "")
                name = blog.get("name", "")
                url = blog.get("url", "")
                content = blog.get("content", "")[:2000]
                parts.append(f"\n[{name}] {title}\nURL: {url}\n{content}")

        return "\n".join(parts)

    async def generate_digest(self, language: str = "zh", mode: str = "summary") -> str | None:
        """Fetch feeds and generate a digest.

        Args:
            language: "en", "zh", or "bilingual"
            mode: "summary" (AI digest) or "full" (raw formatted content)

        Returns:
            Formatted digest string, or None if no content available.
        """
        feeds = await self.fetch_feeds()

        # Check if any feed has content
        has_content = False
        for key in ["podcasts", "x", "blogs"]:
            data = feeds.get(key)
            if data:
                list_key = "podcasts" if key == "podcasts" else key
                items = data.get(list_key, [])
                if items:
                    has_content = True
                    break

        if not has_content:
            return None

        # Full mode: return formatted raw content (no AI cost)
        if mode == "full":
            return self._build_full_digest(feeds)

        raw_content = self._build_raw_content(feeds)
        if not raw_content.strip():
            return None

        lang_instructions = {
            "en": "Write the entire digest in English.",
            "zh": "Write the entire digest in Chinese (Simplified). Keep technical terms (LLM, GPU, RAG) and proper nouns (person names, product names, company names) in English.",
            "bilingual": "Write each section with English first, then Chinese translation immediately below. Keep technical terms and proper nouns in English in both versions.",
        }

        today = datetime.now().strftime("%b %d, %Y")

        prompt = f"""You are an AI news digest writer. Summarize the following content from top AI builders into a concise, readable Telegram message.

FORMAT:
📰 AI Builders Daily — {today}

🎙 PODCASTS
• [Podcast Name]: [Episode Title] — 2-3 sentence summary of key insights
  🔗 [URL]

💬 X / TWITTER
• [Person Name]: 1-2 sentence summary of their notable post(s)
  🔗 [URL]

📝 BLOGS
• [Source]: [Title] — 2-3 sentence summary
  🔗 [URL]

RULES:
- Only include content that has actual substance (skip mundane posts, promotional tweets)
- Use full names, not @ handles
- Keep each item to 2-3 sentences max
- Include the direct URL for every item
- If a section has no notable content, omit that section entirely
- {lang_instructions.get(language, lang_instructions["zh"])}

CONTENT TO SUMMARIZE:
{raw_content}"""

        try:
            response = self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text
        except Exception as e:
            logger.error(f"Error generating digest: {e}")
            return None
