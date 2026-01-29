"""
AI Handler - Uses Claude API for vocabulary learning
"""
import anthropic
from datetime import date
import json
import re


SYSTEM_PROMPT = """You are an English vocabulary learning assistant for intermediate-to-advanced Chinese learners.

CRITICAL RULES:

0. USE BASE/DICTIONARY FORM FOR WORDS:
   - ALWAYS convert words to their base/dictionary/lemma form in the "english" field
   - Plurals → Singular: "fidelities" → "fidelity", "kettles" → "kettle", "analyses" → "analysis"
   - Conjugated verbs → Base form: "running" → "run", "went" → "go" (unless the specific form has unique meaning)
   - Past participles → Base form: "broken" → "break" (unless used as adjective with different meaning)
   - Exception: Keep the original form if it has a distinct meaning (e.g., "broken" as adjective meaning 损坏的)
   - For phrasal verbs and fixed expressions, use the base verb form: "putting off" → "put off"

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

    def _sanitize_json_response(self, text: str) -> str:
        """Fix special characters that break JSON parsing."""
        # Replace curly/smart quotes with straight quotes
        text = text.replace('"', '"').replace('"', '"')
        text = text.replace(''', "'").replace(''', "'")
        # Replace other problematic Unicode characters
        text = text.replace('…', '...')
        text = text.replace('—', '-').replace('–', '-')
        return text

    def _try_parse_json(self, text: str) -> dict:
        """
        Try multiple strategies to parse JSON from AI response.
        Returns parsed dict or raises JSONDecodeError if all strategies fail.
        """
        # Strategy 1: Direct parse after basic cleanup
        cleaned = text.strip()

        # Remove markdown code blocks if present
        cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r'\s*```\s*$', '', cleaned)
        cleaned = cleaned.strip()

        # Sanitize special characters
        cleaned = self._sanitize_json_response(cleaned)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Strategy 2: Extract JSON object using regex (handles text before/after JSON)
        json_match = re.search(r'\{[\s\S]*\}', cleaned)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        # Strategy 3: Fix common JSON issues
        fixed = cleaned

        # Fix trailing commas before } or ]
        fixed = re.sub(r',(\s*[}\]])', r'\1', fixed)

        # Fix unescaped newlines in strings (convert to \n)
        # This handles cases where AI puts actual newlines inside JSON strings
        lines = fixed.split('\n')
        in_string = False
        result_lines = []
        for i, line in enumerate(lines):
            # Count unescaped quotes to track if we're in a string
            quote_count = 0
            j = 0
            while j < len(line):
                if line[j] == '"' and (j == 0 or line[j-1] != '\\'):
                    quote_count += 1
                j += 1

            if i > 0 and in_string:
                # We're continuing a string from previous line - join with escaped newline
                result_lines[-1] = result_lines[-1] + '\\n' + line
            else:
                result_lines.append(line)

            # Update in_string state
            if quote_count % 2 == 1:
                in_string = not in_string

        fixed = '\n'.join(result_lines)

        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass

        # Strategy 4: Try extracting JSON again after fixes
        json_match = re.search(r'\{[\s\S]*\}', fixed)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        # All strategies failed - raise the original error for debugging
        return json.loads(cleaned)  # This will raise JSONDecodeError with details

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

        try:
            result = self._try_parse_json(response_text)
            # Add today's date to each entry
            today = date.today().isoformat()
            for entry in result.get("entries", []):
                entry["date"] = today
            return result
        except json.JSONDecodeError as e:
            # Retry once with explicit JSON request
            try:
                retry_message = self.client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=2000,
                    messages=[
                        {"role": "user", "content": user_input},
                        {"role": "assistant", "content": response_text},
                        {"role": "user", "content": "Your response had invalid JSON. Please respond with ONLY valid JSON, no extra text."}
                    ],
                    system=SYSTEM_PROMPT
                )
                retry_text = retry_message.content[0].text
                result = self._try_parse_json(retry_text)
                today = date.today().isoformat()
                for entry in result.get("entries", []):
                    entry["date"] = today
                return result
            except json.JSONDecodeError as retry_e:
                return {
                    "error": f"Failed to parse AI response: {str(retry_e)}",
                    "raw_response": response_text
                }
            except Exception:
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
        """Modify an entry based on user's follow-up request.

        If user asks a question, returns both the answer and modified entry.
        """
        modify_prompt = f"""You have a vocabulary entry that the user is interacting with.

CURRENT ENTRY:
- English: {entry.get('english', '')}
- Chinese: {entry.get('chinese', '')}
- Explanation: {entry.get('explanation', '')}
- Example EN: {entry.get('example_en', '')}
- Example ZH: {entry.get('example_zh', '')}
- Category: {entry.get('category', '')}

USER MESSAGE: {user_request}

INSTRUCTIONS:
1. First, determine if the user is asking a QUESTION (contains ?, 吗, 呢, 什么, 为什么, 怎么, 是不是, 是否, etc.)
2. If the user is asking a question:
   - Provide a clear, helpful answer to their question in "question_answer"
   - Then update the entry if the question implies a modification is needed
3. If the user is giving feedback/instructions (not a question):
   - Set "question_answer" to null
   - Modify the entry according to their request

REMEMBER: Use the base/dictionary form for the "english" field (plurals → singular, conjugated → base form).

OUTPUT FORMAT (strict JSON):
{{
  "question_answer": "Answer to the user's question in the same language they asked (Chinese or English), OR null if not a question",
  "entry": {{
    "english": "...",
    "chinese": "...",
    "explanation": "...",
    "example_en": "...",
    "example_zh": "...",
    "category": "one of: 固定词组, 口语, 新闻, 职场, 学术词汇, 写作, 情绪, 其他"
  }}
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

        try:
            result = self._try_parse_json(response_text)
            modified_entry = result.get("entry", result)  # Support both new and old format
            modified_entry["date"] = entry.get("date", date.today().isoformat())

            return {
                "success": True,
                "entry": modified_entry,
                "question_answer": result.get("question_answer")
            }
        except json.JSONDecodeError as e:
            return {"success": False, "error": str(e)}

    def detect_target_entry(self, entries: list, user_feedback: str) -> int:
        """
        Detect which entry (0-indexed) the user is referring to in their feedback.
        Uses multiple strategies: explicit number, phrase matching, and AI inference.

        Returns the index of the target entry (0-indexed).
        """
        if len(entries) <= 1:
            return 0

        # Strategy 1: Check for explicit entry number reference (e.g., "第2个", "[2]", "2号")
        number_patterns = [
            r'第\s*(\d+)\s*[个条]',  # 第2个, 第2条
            r'\[(\d+)\]',             # [2]
            r'(\d+)\s*号',            # 2号
            r'entry\s*(\d+)',         # entry 2
            r'#\s*(\d+)',             # #2
        ]
        for pattern in number_patterns:
            match = re.search(pattern, user_feedback, re.IGNORECASE)
            if match:
                num = int(match.group(1))
                if 1 <= num <= len(entries):
                    return num - 1  # Convert to 0-indexed

        # Strategy 2: Check if user's feedback contains any of the English phrases
        user_feedback_lower = user_feedback.lower()
        matched_indices = []
        for i, entry in enumerate(entries):
            english = entry.get('english', '').lower()
            # Remove phonetic notation for matching
            english_clean = re.sub(r'/[^/]+/', '', english).strip()

            # Check if the English phrase appears in user's feedback
            if english_clean and english_clean in user_feedback_lower:
                matched_indices.append((i, len(english_clean)))

            # Also check individual words for partial matches
            words = english_clean.split()
            for word in words:
                if len(word) > 3 and word in user_feedback_lower:
                    matched_indices.append((i, len(word)))

        # Return the best match (longest match wins)
        if matched_indices:
            matched_indices.sort(key=lambda x: x[1], reverse=True)
            return matched_indices[0][0]

        # Strategy 3: Use AI to determine which entry the feedback refers to
        entries_desc = "\n".join([
            f"[{i+1}] {e.get('english', '')} - {e.get('chinese', '')}"
            for i, e in enumerate(entries)
        ])

        detect_prompt = f"""Given these vocabulary entries:
{entries_desc}

And this user feedback: "{user_feedback}"

Which entry number (1-{len(entries)}) is the user most likely referring to?
- If feedback mentions a specific phrase or word from an entry, choose that entry
- If unclear, respond with the most likely one based on context
- If truly ambiguous, respond with 1

Respond with ONLY the number (1-{len(entries)}), nothing else."""

        try:
            message = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=10,
                messages=[{"role": "user", "content": detect_prompt}]
            )
            response = message.content[0].text.strip()
            # Extract number from response
            num_match = re.search(r'(\d+)', response)
            if num_match:
                num = int(num_match.group(1))
                if 1 <= num <= len(entries):
                    return num - 1
        except Exception:
            pass

        # Default to first entry
        return 0
