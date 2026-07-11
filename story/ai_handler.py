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

SYSTEM_PROMPT = """You are an English coach for a Chinese learner who records spoken reflections and daily thoughts.

These are ORAL/CONVERSATIONAL entries, not formal writing. Preserve the user's natural voice and casual tone.

Your job:
1. If the input is English: fix genuine errors only. Keep the casual, spoken style.
2. If the input is Chinese: translate into natural, conversational English. Explain translation choices in Chinese.
3. If the input is mixed: convert everything to natural spoken English. Explain in Chinese.

What to fix (in "revised"):
- Grammar errors (tense, agreement, articles, prepositions)
- Wrong word usage or Chinglish expressions
- Sentences that sound unnatural to a native speaker

What NOT to change (in "revised"):
- Casual/informal vocabulary that is already correct (e.g. "super warm" is fine — do NOT upgrade to "wonderfully warm")
- Natural spoken expressions (e.g. "I feel for him" — do NOT change to "I truly empathize with him")
- Simple but correct phrasing (e.g. "learn so much" — do NOT change to "learn a tremendous amount")
- Contractions or lack thereof — the user types uncontracted forms for convenience, not by mistake
- The user's personal tone and style

What to include in "notes":
- Chinese explanations for each grammar/usage fix
- Actively suggest better/more natural ORAL expressions the user could have used — e.g. more vivid spoken phrases, common collocations, idiomatic ways native speakers would say it in conversation. These are suggestions for learning, NOT applied in the revised text. Label these as「💡 也可以说」
- Don't just say "your expression is fine, no need to change" — if you mention an alternative, explain WHY it's worth knowing (e.g. more commonly used, sounds more native, conveys emotion better)
- Keep notes concise — one line per fix/suggestion

IMPORTANT:
- "revised" = the user's text with ONLY genuine errors fixed, keeping their voice
- "notes" = 中文解释（语法修正 + 口语表达建议）
- "phrases" = a list of up to 5 key phrases worth remembering from this entry (corrected expressions, useful collocations, or noteworthy vocab the user used or should have used). Each item: "phrase" (the correct form) + brief Chinese explanation. If fewer than 5 are noteworthy, include fewer. Empty list if nothing stands out.
- If the input has no real errors, return it as-is and say so in notes

Respond with ONLY valid JSON, no markdown:
{"revised": "...", "notes": "...", "phrases": [{"phrase": "push their luck", "note": "固定搭配，不用 push the luck"}]}"""


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

    def _get_response_text(self, model: str, messages: list, system: str = None, max_tokens: int = 1500) -> str:
        """Get AI response with fallback chain: requested model -> fallback model -> OpenAI."""
        anthropic_models = [model]
        if model != self.fallback_model:
            anthropic_models.append(self.fallback_model)

        last_error = None
        for attempt_model in anthropic_models:
            try:
                kwargs = {
                    "model": attempt_model,
                    "max_tokens": max_tokens,
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
                max_tokens=max_tokens,
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

    def _calc_max_tokens(self, text: str) -> int:
        """Calculate max_tokens based on input length.

        Longer inputs need more tokens for revised text + detailed notes.
        Rough estimate: 1 word ≈ 1.3 tokens, output needs ~3x input
        (revised text + Chinese notes with explanations).
        """
        word_count = len(text.split())
        if word_count <= 30:
            return 1500
        elif word_count <= 80:
            return 2500
        elif word_count <= 150:
            return 3500
        else:
            return 4096

    async def revise_text(self, text: str) -> dict:
        """Revise text and return {"revised": "...", "notes": "..."}.

        Returns {"revised": None, "notes": None} if AI call fails.
        Runs the blocking API call in a thread executor.
        """
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, self._revise_sync, text)
            return result
        except Exception as e:
            logger.error(f"Story AI revision failed: {e}", exc_info=True)
            return {"revised": None, "notes": None}

    def _try_revise_with_model(self, model: str, text: str, max_tokens: int = 1500) -> dict | None:
        """Try revision with a specific model. Returns result dict or None on failure."""
        try:
            logger.info(f"Story AI: trying {model} (max_tokens={max_tokens})...")
            response_text = self._get_response_text(
                model=model,
                messages=[{"role": "user", "content": text}],
                system=SYSTEM_PROMPT,
                max_tokens=max_tokens,
            )
            logger.info(f"Story AI: got response ({len(response_text)} chars)")

            result = self._parse_json(response_text)
            revised = result.get("revised")
            notes = result.get("notes")

            if revised and notes:
                logger.info(f"Story AI: success with {model}")
                return {"revised": revised, "notes": notes}

            logger.warning(f"Story AI: {model} returned incomplete (revised={revised is not None}, notes={notes is not None})")

            # Retry once asking to fix the JSON
            logger.info(f"Story AI: retrying {model} with JSON fix prompt...")
            retry_text = self._get_response_text(
                model=model,
                messages=[
                    {"role": "user", "content": text},
                    {"role": "assistant", "content": response_text},
                    {"role": "user", "content": "Your response had invalid or incomplete JSON. Please respond with ONLY valid JSON: {\"revised\": \"...\", \"notes\": \"...\"}"},
                ],
                system=SYSTEM_PROMPT,
                max_tokens=max_tokens,
            )
            result = self._parse_json(retry_text)
            if result.get("revised") and result.get("notes"):
                logger.info(f"Story AI: success with {model} (retry)")
                return {"revised": result["revised"], "notes": result["notes"]}

            return None
        except json.JSONDecodeError as e:
            logger.warning(f"Story AI: JSON parse failed with {model}: {e}")
            return None
        except Exception as e:
            logger.warning(f"Story AI: {model} failed: {e}")
            return None

    def _try_revise_openai(self, text: str, max_tokens: int = 1500) -> dict | None:
        """Try revision with OpenAI as final fallback."""
        if not self.openai_client:
            return None
        try:
            logger.info(f"Story AI: trying OpenAI gpt-4o-mini (max_tokens={max_tokens})...")
            response = self.openai_client.chat.completions.create(
                model=self.openai_model,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
            )
            response_text = response.choices[0].message.content
            result = self._parse_json(response_text)
            if result.get("revised") and result.get("notes"):
                logger.info("Story AI: success with OpenAI")
                return {"revised": result["revised"], "notes": result["notes"]}
            return None
        except Exception as e:
            logger.warning(f"Story AI: OpenAI failed: {e}")
            return None

    def _revise_sync(self, text: str) -> dict:
        """Synchronous revision with full retry chain:
        1. Sonnet (+ JSON fix retry)
        2. Haiku (+ JSON fix retry)
        3. OpenAI gpt-4o-mini
        """
        max_tokens = self._calc_max_tokens(text)

        # Try primary model (Sonnet)
        result = self._try_revise_with_model(self.primary_model, text, max_tokens)
        if result:
            return result

        # Try fallback model (Haiku)
        result = self._try_revise_with_model(self.fallback_model, text, max_tokens)
        if result:
            return result

        # Try OpenAI
        result = self._try_revise_openai(text, max_tokens)
        if result:
            return result

        logger.error("Story AI: all models failed for revision")
        return {"revised": None, "notes": None}
