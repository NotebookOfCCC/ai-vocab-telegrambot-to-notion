"""
AI Handler - Uses Claude API for vocabulary learning

Cost optimization:
- Skip AI for very common words (free response)
- Use shorter max_tokens for simple words vs sentences
- Reduced system prompt size
"""
import anthropic
from datetime import date
import json
import re


# =============================================================================
# COMMON WORDS - Skip AI for these (FREE, no API call)
# =============================================================================
COMMON_WORDS = {
    # Basic verbs
    "be", "is", "am", "are", "was", "were", "been", "being",
    "have", "has", "had", "do", "does", "did", "done",
    "go", "goes", "went", "gone", "going",
    "get", "gets", "got", "getting",
    "make", "makes", "made", "making",
    "take", "takes", "took", "taken", "taking",
    "come", "comes", "came", "coming",
    "see", "sees", "saw", "seen", "seeing",
    "know", "knows", "knew", "known",
    "think", "thinks", "thought",
    "say", "says", "said", "want", "wants", "wanted",
    "give", "gives", "gave", "given",
    "use", "uses", "used", "using",
    "find", "finds", "found",
    "tell", "tells", "told",
    "ask", "asks", "asked",
    "work", "works", "worked", "working",
    "try", "tries", "tried",
    "leave", "leaves", "left",
    "call", "calls", "called",
    "put", "puts",  # but "put up", "put off" etc are worth learning
    "keep", "keeps", "kept",
    "let", "lets",
    "begin", "begins", "began", "begun",
    "seem", "seems", "seemed",
    "help", "helps", "helped",
    "show", "shows", "showed", "shown",
    "hear", "hears", "heard",
    "play", "plays", "played",
    "run", "runs", "ran", "running",
    "move", "moves", "moved",
    "live", "lives", "lived",
    "believe", "believes", "believed",
    "bring", "brings", "brought",
    "happen", "happens", "happened",
    "write", "writes", "wrote", "written",
    "sit", "sits", "sat",
    "stand", "stands", "stood",
    "lose", "loses", "lost",
    "pay", "pays", "paid",
    "meet", "meets", "met",
    "include", "includes", "included",
    "continue", "continues", "continued",
    "set", "sets",
    "learn", "learns", "learned",
    "change", "changes", "changed",
    "lead", "leads", "led",
    "understand", "understands", "understood",
    "watch", "watches", "watched",
    "follow", "follows", "followed",
    "stop", "stops", "stopped",
    "create", "creates", "created",
    "speak", "speaks", "spoke", "spoken",
    "read", "reads",
    "spend", "spends", "spent",
    "grow", "grows", "grew", "grown",
    "open", "opens", "opened",
    "walk", "walks", "walked",
    "win", "wins", "won",
    "offer", "offers", "offered",
    "remember", "remembers", "remembered",
    "love", "loves", "loved",
    "consider", "considers", "considered",
    "appear", "appears", "appeared",
    "buy", "buys", "bought",
    "wait", "waits", "waited",
    "serve", "serves", "served",
    "die", "dies", "died",
    "send", "sends", "sent",
    "expect", "expects", "expected",
    "build", "builds", "built",
    "stay", "stays", "stayed",
    "fall", "falls", "fell", "fallen",
    "cut", "cuts",
    "reach", "reaches", "reached",
    "kill", "kills", "killed",
    "remain", "remains", "remained",

    # Basic nouns
    "time", "year", "people", "way", "day", "man", "woman",
    "thing", "child", "children", "world", "life", "hand",
    "part", "place", "case", "week", "company", "system",
    "program", "question", "work", "government", "number",
    "night", "point", "home", "water", "room", "mother",
    "area", "money", "story", "fact", "month", "lot",
    "right", "study", "book", "eye", "job", "word",
    "business", "issue", "side", "kind", "head", "house",
    "service", "friend", "father", "power", "hour", "game",
    "line", "end", "member", "law", "car", "city",
    "community", "name", "president", "team", "minute",
    "idea", "kid", "body", "information", "back", "parent",
    "face", "others", "level", "office", "door", "health",
    "person", "art", "war", "history", "party", "result",
    "morning", "reason", "research", "girl", "guy", "moment",
    "air", "teacher", "force", "education",

    # Basic adjectives
    "good", "new", "first", "last", "long", "great", "little",
    "own", "other", "old", "right", "big", "high", "different",
    "small", "large", "next", "early", "young", "important",
    "few", "public", "bad", "same", "able",

    # Basic adverbs
    "up", "so", "out", "just", "now", "how", "then", "more",
    "also", "here", "well", "only", "very", "even", "back",
    "there", "down", "still", "in", "as", "too", "when",
    "never", "really", "most", "about",

    # Pronouns & determiners
    "i", "you", "he", "she", "it", "we", "they", "me", "him",
    "her", "us", "them", "my", "your", "his", "its", "our",
    "their", "this", "that", "these", "those", "what", "which",
    "who", "whom", "whose", "where", "why",

    # Prepositions & conjunctions
    "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "or", "an", "be", "but", "not", "are", "if", "into",
    "through", "during", "before", "after", "above", "below",
    "between", "under", "again", "further", "once",

    # Articles & others
    "a", "the", "and", "but", "or", "because", "as", "until",
    "while", "of", "at", "by", "for", "with", "about", "against",
    "between", "into", "through", "during", "before", "after",
    "above", "below", "to", "from", "in", "out", "on", "off",
    "over", "under", "again", "further", "then", "once",

    # Numbers
    "one", "two", "three", "four", "five", "six", "seven",
    "eight", "nine", "ten", "hundred", "thousand", "million",
}


# =============================================================================
# CATEGORY CONFIGURATION - Edit this dict to add/remove/modify categories
# =============================================================================
CATEGORIES = {
    "固定词组": "Phrasal verbs, idioms, collocations",
    "口语": "Casual speech, slang, conversational",
    "新闻": "News, journalism, formal reporting",
    "职场": "Business, professional, workplace",
    "学术词汇": "Academic, scholarly",
    "写作": "Literary, formal writing",
    "情绪": "Emotions, feelings",
    "科技": "Technology, computing, software, internet",
    "其他": "Other",
}

# Generate category list string for prompts
CATEGORY_LIST = ", ".join(CATEGORIES.keys())

# Generate category guide for prompts
CATEGORY_GUIDE = "\n".join(f"- {name}: {desc}" for name, desc in CATEGORIES.items())


SYSTEM_PROMPT = f"""You are an English vocabulary learning assistant for intermediate-to-advanced Chinese learners.

CRITICAL RULES:

0. USE BASE/DICTIONARY FORM FOR WORDS:
   - ALWAYS convert words to their base/dictionary/lemma form in the "english" field
   - Plurals → Singular: "fidelities" → "fidelity", "kettles" → "kettle", "analyses" → "analysis"
   - Conjugated verbs → Base form: "running" → "run", "went" → "go" (unless the specific form has unique meaning)
   - Past participles → Base form: "broken" → "break" (unless used as adjective with different meaning)
   - Exception: Keep the original form if it has a distinct meaning (e.g., "broken" as adjective meaning 损坏的)
   - For phrasal verbs and fixed expressions, use the base verb form: "putting off" → "put off"
   - For "adj + to" patterns (e.g., "analogous to", "akin to", "prone to"), ALWAYS save as "be + adj + to" form: "be analogous to"

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
   f) CHECK EXAMPLE GRAMMAR: If the user's sentence has grammar errors, use the CORRECTED version as the example, not the original.

2. WORD/PHRASE INPUT:
   - Create one complete learning entry.
   - If user inputs a common word, still explain it but note it's basic vocabulary.

3. SELECTIVITY IS KEY:
   - For a sentence like "tear down existing structure", only "tear down" is worth learning.
   - "existing" and "structure" are basic words - DO NOT include them.
   - Quality over quantity: 1 good entry is better than 3 mediocre ones.

4. PHONETICS - ADD LIBERALLY:
   - Add phonetic notation /IPA/ for ANY word that is NOT in the 3000 most common English words
   - ALWAYS add phonetics for: multi-syllable words, words with unusual stress, silent letters, or non-obvious pronunciation
   - Examples that NEED phonetics: unrelenting /ˌʌnrɪˈlentɪŋ/, albeit /ɔːlˈbiːɪt/, facade /fəˈsɑːd/, niche /niːʃ/
   - Format: "word /phonetic/" e.g., "ubiquitous /juːˈbɪkwɪtəs/"

5. PART OF SPEECH (词性) - ALWAYS INCLUDE:
   - Add part of speech abbreviation after the word/phrase in the "english" field
   - Format: "word (pos.)" e.g., "priority (n.)", "ubiquitous (adj.)", "procrastinate (v.)"
   - For phrasal verbs: "put off (phr. v.)"
   - For idioms: "break the ice (idiom)"
   - Common abbreviations: n. (noun), v. (verb), adj. (adjective), adv. (adverb), phr. v. (phrasal verb), idiom, prep. (preposition)

6. MULTIPLE MEANINGS:
   - If a word/phrase has MULTIPLE distinct meanings (like "put up", "undershoot"), list ALL meanings numbered
   - IMPORTANT: For EACH numbered meaning in explanation, provide a CORRESPONDING numbered example
   - Example format for multi-meaning words:
     explanation: "1. 未达到目标 2. 射击偏低 3. 飞机降落时未达到预定位置"
     example_en: "1. The company's revenue undershoots expectations. 2. The archer undershot the target. 3. The pilot undershot the runway."
     example_zh: "1. 公司收入未达预期。 2. 弓箭手射偏了目标。 3. 飞行员降落时未到达跑道。"

OUTPUT FORMAT (strict JSON):
{{
  "is_sentence": true/false,
  "grammar_correction": "corrected/completed sentence OR null if no issues and not a sentence",
  "grammar_note": "brief explanation of what was corrected, OR null",
  "entries": [
    {{
      "english": "word /phonetic/ (pos.)",
      "chinese": "中文翻译 (情感标签如适用，如：贬义/褒义/中性)",
      "explanation": "简洁中文解释。如有多个含义，编号列出：1. 含义一 2. 含义二 3. 含义三",
      "example_en": "English example(s). If multiple meanings, number them: 1. Example for meaning 1. 2. Example for meaning 2.",
      "example_zh": "中文翻译。如有多个例句，同样编号：1. 翻译一 2. 翻译二",
      "category": "one of: {CATEGORY_LIST}"
    }}
  ]
}}

CATEGORY GUIDE:
{CATEGORY_GUIDE}

Respond with valid JSON only, no markdown."""


class AIHandler:
    def __init__(self, api_key: str, use_cheap_model: bool = False):
        """Initialize AI handler.

        Args:
            api_key: Anthropic API key
            use_cheap_model: If True, use Haiku for all requests (12x cheaper but slightly lower quality)
        """
        self.client = anthropic.Anthropic(api_key=api_key)
        # Sonnet for quality, Haiku for cost savings
        self.main_model = "claude-sonnet-4-20250514"  # Always use Sonnet for reliability

    def _sanitize_json_response(self, text: str) -> str:
        """Fix special characters that break JSON parsing."""
        # Replace curly/smart quotes with straight quotes
        text = text.replace('"', '"').replace('"', '"')
        text = text.replace(''', "'").replace(''', "'")
        # Replace other problematic Unicode characters
        text = text.replace('…', '...')
        text = text.replace('—', '-').replace('–', '-')
        # Remove zero-width characters and other invisible Unicode
        text = text.replace('\u200b', '')  # zero-width space
        text = text.replace('\u200c', '')  # zero-width non-joiner
        text = text.replace('\u200d', '')  # zero-width joiner
        text = text.replace('\ufeff', '')  # BOM
        return text

    def _escape_json_string_content(self, text: str) -> str:
        """
        Fix unescaped characters inside JSON string values.
        This handles cases where AI puts unescaped quotes or control chars in strings.
        """
        result = []
        i = 0
        in_string = False
        string_start = -1

        while i < len(text):
            char = text[i]

            if char == '"':
                # Check if this quote is escaped
                num_backslashes = 0
                j = i - 1
                while j >= 0 and text[j] == '\\':
                    num_backslashes += 1
                    j -= 1

                if num_backslashes % 2 == 0:  # Quote is not escaped
                    if not in_string:
                        in_string = True
                        string_start = i
                        result.append(char)
                    else:
                        # Check if this looks like end of string (followed by : , } ] or whitespace)
                        next_char_idx = i + 1
                        while next_char_idx < len(text) and text[next_char_idx] in ' \t\n\r':
                            next_char_idx += 1

                        if next_char_idx >= len(text) or text[next_char_idx] in ':,}]':
                            # This is likely the end of the string
                            in_string = False
                            result.append(char)
                        else:
                            # This is an unescaped quote inside the string - escape it
                            result.append('\\"')
                else:
                    result.append(char)
            elif in_string and char in '\n\r\t':
                # Escape control characters inside strings
                if char == '\n':
                    result.append('\\n')
                elif char == '\r':
                    result.append('\\r')
                elif char == '\t':
                    result.append('\\t')
            else:
                result.append(char)

            i += 1

        return ''.join(result)

    def _try_parse_json(self, text: str) -> dict:
        """
        Try multiple strategies to parse JSON from AI response.
        Returns parsed dict or raises JSONDecodeError if all strategies fail.
        """
        last_error = None

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
        except json.JSONDecodeError as e:
            last_error = e

        # Strategy 2: Extract JSON object using regex (handles text before/after JSON)
        json_match = re.search(r'\{[\s\S]*\}', cleaned)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError as e:
                last_error = e

        # Strategy 3: Fix trailing commas and basic issues
        fixed = cleaned
        fixed = re.sub(r',(\s*[}\]])', r'\1', fixed)

        try:
            return json.loads(fixed)
        except json.JSONDecodeError as e:
            last_error = e

        # Strategy 4: Escape problematic characters inside string values
        escaped = self._escape_json_string_content(fixed)
        try:
            return json.loads(escaped)
        except json.JSONDecodeError as e:
            last_error = e

        # Strategy 5: Extract and escape JSON
        json_match = re.search(r'\{[\s\S]*\}', escaped)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError as e:
                last_error = e

        # Strategy 6: Fix unescaped newlines in strings (convert to \n)
        lines = fixed.split('\n')
        in_string = False
        result_lines = []
        for i, line in enumerate(lines):
            quote_count = 0
            j = 0
            while j < len(line):
                if line[j] == '"' and (j == 0 or line[j-1] != '\\'):
                    quote_count += 1
                j += 1

            if i > 0 and in_string:
                result_lines[-1] = result_lines[-1] + '\\n' + line
            else:
                result_lines.append(line)

            if quote_count % 2 == 1:
                in_string = not in_string

        fixed = '\n'.join(result_lines)

        try:
            return json.loads(fixed)
        except json.JSONDecodeError as e:
            last_error = e

        # Strategy 7: Apply escaping to the newline-fixed version
        escaped_fixed = self._escape_json_string_content(fixed)
        try:
            return json.loads(escaped_fixed)
        except json.JSONDecodeError as e:
            last_error = e

        # Strategy 8: Try extracting JSON again after all fixes
        json_match = re.search(r'\{[\s\S]*\}', escaped_fixed)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError as e:
                last_error = e

        # Strategy 9: Aggressive cleanup - remove all control characters
        aggressive = re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', cleaned)
        aggressive = self._escape_json_string_content(aggressive)
        json_match = re.search(r'\{[\s\S]*\}', aggressive)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError as e:
                last_error = e

        # All strategies failed - raise the last error for debugging
        raise last_error if last_error else json.JSONDecodeError("No valid JSON found", text, 0)

    def _is_common_word(self, text: str) -> bool:
        """Check if input is a single common word (skip AI)."""
        words = text.lower().strip().split()
        # Only skip for single common words, not phrases or sentences
        return len(words) == 1 and words[0] in COMMON_WORDS

    def _common_word_response(self, word: str) -> dict:
        """Return a simple response for common words (FREE - no API call)."""
        return {
            "is_sentence": False,
            "grammar_correction": None,
            "grammar_note": None,
            "entries": [{
                "english": f"{word} (basic)",
                "chinese": "基础词汇",
                "explanation": f"'{word}' 是非常基础的英语词汇，建议学习更高级的表达。",
                "example_en": f"This is a basic word.",
                "example_zh": "这是一个基础词汇。",
                "category": "其他",
                "date": date.today().isoformat()
            }],
            "skipped_ai": True  # Flag to indicate no API was called
        }

    def analyze_input(self, user_input: str) -> dict:
        """Analyze user input and generate learning entries."""
        # Skip AI for common single words (FREE!)
        if self._is_common_word(user_input):
            return self._common_word_response(user_input.lower().strip())

        # Determine max_tokens based on input type
        # Single word/short phrase = less tokens needed
        word_count = len(user_input.split())
        if word_count <= 3:
            max_tokens = 800  # Single word or short phrase
        else:
            max_tokens = 1000  # Sentence needs more

        message = self.client.messages.create(
            model=self.main_model,
            max_tokens=max_tokens,
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
                    model=self.main_model,
                    max_tokens=max_tokens,  # Use same limit as original
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
1. First, determine if the user is asking a QUESTION (contains ?, 吗, 呢, 什么, 为什么, 怎么, 是不是, 是否, 音标, pronunciation, etc.)
2. If the user is asking a question:
   - Provide a clear, helpful answer to their question in "question_answer"
   - IMPORTANT: Always update the entry to incorporate the answer when relevant:
     * If asking about pronunciation/音标: Add phonetic notation to the "english" field (e.g., "word /wɜːrd/")
     * If asking about meaning: Update "chinese" or "explanation" if needed
     * If asking about usage: Update "example_en"/"example_zh" if a better example is given
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
    "category": "one of: {CATEGORY_LIST}"
  }}
}}

Respond with valid JSON only."""

        # Use Haiku for modifications - cheaper and fast enough
        message = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=800,
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
            # Use Haiku for simple number detection - much cheaper
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
