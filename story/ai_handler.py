"""
Story Bot AI Handler - Revises English text and provides grammar suggestions.

Uses Claude Sonnet as primary model with Haiku and GPT-4o-mini fallback.
Cost: ~$0.005 per revision.
"""
import anthropic
import asyncio
import json
import re
import time
import logging

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an English writing coach for a Chinese learner practicing daily storytelling.

Your job:
1. If the input is English: revise it for naturalness, grammar, and fluency. Provide detailed Chinese grammar explanations.
2. If the input is Chinese: translate it into natural, idiomatic English. Explain translation choices in Chinese.
3. If the input is mixed: convert everything to polished English. Explain in Chinese.
4. Even if the input has no errors, suggest improvements — more advanced vocabulary, more idiomatic phrasing, better sentence structure. Explain why the alternatives are better.

IMPORTANT:
- "revised" should be the improved/translated English text
- "notes" should be detailed Chinese explanations (grammar errors, word choices, translation reasoning, improvement suggestions)
- Keep the original meaning intact
- Be encouraging but thorough

Respond with ONLY valid JSON, no markdown:
{"revised": "the improved English text", "notes": "详细的中文语法解释和建议"}"""


class StoryAIHandler:
    def __init__(self, anthropic_api_key: str, openai_api_key: str = None):
        self.client = anthropic.Anthropic(api_key=anthropic_api_key)
        self.primary_model = "claude-sonnet-4-5"
        self.fallback_model = "claude-haiku-4-5-20251001"

        self.openai_client = None
        self.openai_model = "gpt-4o-mini"
        if openai_api_key:
            try:
                from openai import OpenAI
                self.openai_client = OpenAI(api_key=openai_api_key)
                logger.info("Story AI: OpenAI fallback enabled")
            except ImportError:
                logger.warning("openai package not installed - fallback disabled")

    def _retry_anthropic(self, **kwargs):
        """Call Anthropic API with up to 3 retries for 429/529 errors."""
        max_retries = 3
        base_delay = 5
        last_error = None

        for attempt in range(max_retries):
            try:
                return self.client.messages.create(**kwargs)
            except anthropic.APIStatusError as e:
                if e.status_code in (429, 529):
                    last_error = e
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        logger.warning(f"Anthropic overloaded (attempt {attempt+1}), retrying in {delay}s...")
                        time.sleep(delay)
                else:
                    raise

        raise last_error or RuntimeError("Unreachable")

    def _get_response_text(self, model: str, messages: list, system: str = None) -> str:
        """Get AI response with fallback chain: requested model -> fallback model -> OpenAI."""
        anthropic_models = [model]
        if model != self.fallback_model:
            anthropic_models.append(self.fallback_model)

        last_error = None
        for attempt_model in anthropic_models:
            try:
                kwargs = {
                    "model": attempt_model,
                    "max_tokens": 1000,
                    "messages": messages,
                }
                if system:
                    kwargs["system"] = system
                response = self._retry_anthropic(**kwargs)
                return response.content[0].text
            except anthropic.APIStatusError as e:
                is_usage_limit = e.status_code == 400 and "usage" in str(e).lower()
                if e.status_code in (429, 529, 404) or is_usage_limit:
                    last_error = e
                    logger.warning(f"Anthropic {attempt_model} unavailable ({e.status_code})")
                    if is_usage_limit:
                        break
                    continue
                raise

        if self.openai_client:
            logger.warning("Anthropic unavailable, falling back to OpenAI")
            openai_messages = []
            if system:
                openai_messages.append({"role": "system", "content": system})
            openai_messages.extend(messages)
            response = self.openai_client.chat.completions.create(
                model=self.openai_model,
                max_tokens=1000,
                messages=openai_messages,
            )
            return response.choices[0].message.content

        raise last_error or RuntimeError("All AI providers unavailable")

    def _parse_json(self, text: str) -> dict:
        """Parse JSON from AI response with cleanup."""
        cleaned = text.strip()
        cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r'\s*```\s*$', '', cleaned)
        cleaned = cleaned.strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        match = re.search(r'\{[\s\S]*\}', cleaned)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        fixed = re.sub(r',(\s*[}\]])', r'\1', cleaned)
        return json.loads(fixed)

    async def revise_text(self, text: str) -> dict:
        """Revise text and return {"revised": "...", "notes": "..."}.

        Returns {"revised": None, "notes": None} if AI call fails.
        Runs the blocking API call in a thread executor.
        """
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self._revise_sync, text)
            return result
        except Exception as e:
            logger.error(f"Story AI revision failed: {e}")
            return {"revised": None, "notes": None}

    def _revise_sync(self, text: str) -> dict:
        """Synchronous revision call."""
        response_text = self._get_response_text(
            model=self.primary_model,
            messages=[{"role": "user", "content": text}],
            system=SYSTEM_PROMPT,
        )

        result = self._parse_json(response_text)
        revised = result.get("revised")
        notes = result.get("notes")

        if not revised or not notes:
            logger.warning(f"Incomplete AI response: {response_text[:200]}")

        return {"revised": revised, "notes": notes}
