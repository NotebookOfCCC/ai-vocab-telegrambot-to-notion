"""
AI Handler - Uses Claude API for vocabulary learning
"""
import anthropic
from datetime import date
import json
import re


SYSTEM_PROMPT = """You are an English vocabulary learning assistant for intermediate-to-advanced Chinese learners.

CRITICAL RULES:

1. SENTENCE INPUT - Process in this order:
   a) GRAMMAR CHECK: Check for grammar errors. If found, correct them (keep original meaning).
   b) COMPLETION: If sentence is incomplete, complete it naturally.
   c) Show the final corrected/completed sentence in "grammar_correction" field.
   d) EXTRACT PHRASES: Only extract TRULY WORTH-LEARNING items:
      - Phrasal verbs (tear down, break up, put off)
      - Idioms and fixed expressions
      - Collocations that are non-obvious
      - Advanced/uncommon vocabulary
      - DO NOT extract common basic words like: existing, structure, important, people, thing, make, take, get, have, etc.
   e) USE THE USER'S SENTENCE: When creating examples, use the user's original/corrected sentence as the example when relevant.

2. WORD/PHRASE INPUT:
   - Create one complete learning entry.
   - If user inputs a common word, still explain it but note it's basic vocabulary.

3. SELECTIVITY IS KEY:
   - For a sentence like "tear down existing structure", only "tear down" is worth learning.
   - "existing" and "structure" are basic words - DO NOT include them.
   - Quality over quantity: 1 good entry is better than 3 mediocre ones.

OUTPUT FORMAT (strict JSON):
{
  "is_sentence": true/false,
  "grammar_correction": "corrected/completed sentence OR null if no issues and not a sentence",
  "grammar_note": "brief explanation of what was corrected, OR null",
  "entries": [
    {
      "english": "the phrase (add /phonetic/ for uncommon pronunciation)",
      "chinese": "中文翻译 (情感标签如适用，如：贬义/褒义/中性)",
      "explanation": "简洁中文解释，2-3句话概括核心含义和常见用法即可。",
      "example_en": "One clear English example sentence (prefer using the user's input sentence if it's a sentence)",
      "example_zh": "对应的完整中文翻译",
      "category": "one of: 固定词组, 口语, 新闻, 职场, 学术词汇, 写作, 情绪, 其他"
    }
  ]
}

CATEGORY GUIDE:
- 固定词组: Phrasal verbs, idioms, collocations
- 口语: Casual speech, slang, conversational
- 新闻: News, journalism, formal reporting
- 职场: Business, professional, workplace
- 学术词汇: Academic, scholarly
- 写作: Literary, formal writing
- 情绪: Emotions, feelings
- 其他: Other

Respond with valid JSON only, no markdown."""


class AIHandler:
    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)

    def analyze_input(self, user_input: str) -> dict:
        """Analyze user input and generate learning entries."""
        message = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": user_input}
            ]
        )

        response_text = message.content[0].text

        # Clean up response - remove markdown code blocks if present
        response_text = re.sub(r'^```json\s*', '', response_text)
        response_text = re.sub(r'\s*```$', '', response_text)
        response_text = response_text.strip()

        try:
            result = json.loads(response_text)
            # Add today's date to each entry
            today = date.today().isoformat()
            for entry in result.get("entries", []):
                entry["date"] = today
            return result
        except json.JSONDecodeError as e:
            return {
                "error": f"Failed to parse AI response: {str(e)}",
                "raw_response": response_text
            }

    def format_entries_for_display(self, analysis: dict) -> str:
        """Format the analysis result for Telegram display."""
        if "error" in analysis:
            return f"Error: {analysis['error']}"

        lines = []

        # Show grammar correction if applicable
        if analysis.get("is_sentence"):
            if analysis.get("grammar_correction"):
                lines.append(f"Corrected: {analysis['grammar_correction']}")
                if analysis.get("grammar_note"):
                    lines.append(f"({analysis['grammar_note']})")
                lines.append("")
            else:
                lines.append("Grammar: No issues found.\n")

        entries = analysis.get("entries", [])
        if not entries:
            return "No learnable content found."

        # Show full entry for each item
        for i, entry in enumerate(entries, 1):
            if len(entries) > 1:
                lines.append(f"{'─'*30}")
                lines.append(f"[{i}]")
            lines.append(self._format_single_entry(entry))

        if len(entries) > 1:
            lines.append(f"{'─'*30}")

        return "\n".join(lines)

    def _format_single_entry(self, entry: dict) -> str:
        """Format a single entry for display."""
        return f"""
{entry['english']}
{entry['chinese']}

Explanation:
{entry['explanation']}

Example:
{entry['example_en']}
{entry['example_zh']}

Category: {entry['category']}
Date: {entry['date']}
"""

    def format_entry_for_save_confirmation(self, entry: dict) -> str:
        """Format entry to show before saving."""
        return f"""
{entry['english']}
{entry['chinese']}
{entry['explanation']}
{entry['example_en']}
{entry['example_zh']}
Category: {entry['category']}
Date: {entry['date']}

--- Saving to Notion ---"""

    def modify_entry(self, entry: dict, user_request: str) -> dict:
        """Modify an entry based on user's follow-up request."""
        modify_prompt = f"""You have a vocabulary entry that needs modification based on user feedback.

CURRENT ENTRY:
- English: {entry.get('english', '')}
- Chinese: {entry.get('chinese', '')}
- Explanation: {entry.get('explanation', '')}
- Example EN: {entry.get('example_en', '')}
- Example ZH: {entry.get('example_zh', '')}
- Category: {entry.get('category', '')}

USER REQUEST: {user_request}

Modify the entry according to the user's request. Keep fields unchanged if not mentioned.

OUTPUT FORMAT (strict JSON):
{{
  "english": "...",
  "chinese": "...",
  "explanation": "...",
  "example_en": "...",
  "example_zh": "...",
  "category": "one of: 固定词组, 口语, 新闻, 职场, 学术词汇, 写作, 情绪, 其他"
}}

Respond with valid JSON only."""

        message = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            messages=[
                {"role": "user", "content": modify_prompt}
            ]
        )

        response_text = message.content[0].text
        response_text = re.sub(r'^```json\s*', '', response_text)
        response_text = re.sub(r'\s*```$', '', response_text)
        response_text = response_text.strip()

        try:
            modified = json.loads(response_text)
            modified["date"] = entry.get("date", date.today().isoformat())
            return {"success": True, "entry": modified}
        except json.JSONDecodeError as e:
            return {"success": False, "error": str(e)}
