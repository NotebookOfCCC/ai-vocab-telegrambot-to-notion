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
import time
import logging


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
    "精美句子": "Inspirational, poetic, or beautifully crafted sentences worth saving as a whole",
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
   - IRREGULAR PAST TENSE PHRASAL VERBS: when a verb in the input is clearly a conjugated past tense
     form of a different base verb, convert it. Examples: "tore apart" → "tear apart",
     "drove away" → "drive away", "swore by" → "swear by", "wore out" → "wear out"
   - NOTE: "bore down" is a valid base-form phrasal verb (to drill/penetrate through) — do NOT convert it
   - IRREGULAR VERB CONJUGATION IN EXPLANATION: when the base form has an irregular past tense,
     add the conjugation info at the END of the explanation field with phonetics for each form:
     Format: "（不规则变化：过去式 tore /tɔːr/，过去分词 torn /tɔːrn/）"
     More examples:
       wear → "（不规则变化：过去式 wore /wɔːr/，过去分词 worn /wɔːrn/）"
       drive → "（不规则变化：过去式 drove /drəʊv/，过去分词 driven /ˈdrɪvən/）"
     Do NOT put this note in the chinese field — it belongs in the explanation field only.
   - For "adj + to" patterns (e.g., "analogous to", "akin to", "prone to"), ALWAYS save as "be + adj + to" form: "be analogous to"
   - Exception for 精美句子 entries: keep the full sentence exactly as written (do NOT lemmatize)

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

3b. BEAUTIFUL SENTENCES (精美句子):
   - Detect when input is an inspirational, poetic, or beautifully crafted sentence (or set of sentences)
     with vivid imagery, metaphors, or empowering literary style.
   - Examples: "She grabbed life by the reins.", "She commanded her life.", "She turned life into what she wanted to."
   - When detected, create ONE 精美句子 entry for the ENTIRE input:
     - english: the full sentence(s) exactly as given, grammar-corrected if needed (NOT lemmatized)
     - chinese: natural, fluent Chinese translation of the whole sentence(s)
     - explanation: 2-3 sentence Chinese analysis — what imagery/metaphor is used, the emotional tone, why it's memorable
     - example_en: "" (empty — the sentence itself is in the english field)
     - example_zh: "" (empty)
     - category: "精美句子"
   - Do NOT add /IPA/ or (pos.) to 精美句子 entries — the english field is the full sentence.
   - If the sentence also contains extractable non-obvious vocabulary/phrases (e.g., "grab by the reins"),
     add those as SEPARATE entries AFTER the 精美句子 entry.
   - Normal sentences about everyday topics are NOT 精美句子 — use this for literary/inspirational sentences only.

4. PHONETICS - ALWAYS ADD FOR EVERY ENTRY:
   - Add IPA phonetic notation for EVERY word or phrase, no exceptions
   - For single words: "word /IPA/" e.g., "niche /niːʃ/", "run /rʌn/", "go /ɡəʊ/"
   - For phrasal verbs: include IPA for the main verb: "bear down /beər daʊn/", "give up /ɡɪv ʌp/"
   - For multi-word phrases: include IPA for the full phrase or at least the key word
   - Format: "word /phonetic/ (pos.)" e.g., "ubiquitous /juːˈbɪkwɪtəs/ (adj.)", "run /rʌn/ (v./n.)"

5. PART OF SPEECH (词性) - LIST ALL:
   - Add ALL parts of speech the word can be used as
   - Format: "word (pos1./pos2.)" e.g., "time (n./v.)", "empty (adj./v.)", "run (v./n.)"
   - If word has multiple parts of speech, list them all separated by /
   - Examples:
     * "time (n./v.)" - 时间(n.) / 计时(v.)
     * "empty (adj./v.)" - 空的(adj.) / 清空(v.)
     * "record (n./v.)" - 记录(n.) / 录制(v.)
   - For phrasal verbs: "put off (phr. v.)"
   - For idioms: "break the ice (idiom)"
   - Common abbreviations: n. (noun), v. (verb), adj. (adjective), adv. (adverb), phr. v. (phrasal verb), idiom, prep. (preposition)

6. ALL MEANINGS + CONTEXT-INDEPENDENT ANALYSIS — THIS IS CRITICAL, NEVER SKIP:
   - ALWAYS provide ALL distinct meanings of a word/phrase — never limit to just the meaning used in the sentence
   - Treat every entry as if the user looked it up in a dictionary: comprehensive, context-independent
   - THIS APPLIES EVEN WHEN INPUT IS A SENTENCE — the sentence only tells you WHICH phrase to extract, NOT which meanings to include
   - ✗ WRONG: input "blocking out an hour" → "block out" explanation only covers "为某项活动预留时间"
   - ✓ CORRECT: input "blocking out an hour" → "block out" covers ALL meanings:
       1. 遮挡或阻隔光线、声音等 2. 忽视或压制某种感受、记忆、干扰 3. 划掉或删除文本 4. 为某项活动预留时间
   - Another example: "hook up the microphone" → "hook up" must include ALL meanings (1. connect/接上 2. casual relationship/约炮 3. meet up/碰面), not just "connect"
   - For EACH numbered meaning, provide a CORRESPONDING numbered example sentence

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
    def __init__(self, api_key: str, use_cheap_model: bool = False, openai_api_key: str = None):
        """Initialize AI handler.

        Args:
            api_key: Anthropic API key
            use_cheap_model: If True, use Haiku for all requests (4x cheaper but slightly lower quality)
            openai_api_key: Optional OpenAI API key used as final fallback when Anthropic is overloaded
        """
        self.client = anthropic.Anthropic(api_key=api_key)
        self.use_cheap_model = use_cheap_model
        # Sonnet 4 for main analysis (quality matters), Haiku for secondary tasks (cost savings)
        self.main_model = "claude-haiku-4-5-20251001"  # All vocab analysis
        self.cheap_model = "claude-haiku-4-5-20251001"  # For modifications & detection

        # OpenAI fallback (optional) — used when all Anthropic models are overloaded
        self.openai_client = None
        self.openai_model = "gpt-4o-mini"
        if openai_api_key:
            try:
                from openai import OpenAI
                self.openai_client = OpenAI(api_key=openai_api_key)
                logging.info("OpenAI fallback client initialised (gpt-4o-mini)")
            except ImportError:
                logging.warning("openai package not installed — OpenAI fallback disabled")

    def _retry_anthropic(self, **kwargs) -> object:
        """Call Anthropic API with up to 3 retries for 429/529 errors."""
        max_retries = 3
        base_delay = 5  # seconds
        last_error = None

        for attempt in range(max_retries):
            try:
                return self.client.messages.create(**kwargs)
            except anthropic.APIStatusError as e:
                if e.status_code in (429, 529):
                    last_error = e
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)  # 5s, 10s, 20s
                        logging.warning(f"Anthropic overloaded (attempt {attempt+1}/{max_retries}), retrying in {delay}s...")
                        time.sleep(delay)
                else:
                    raise

        raise last_error or RuntimeError("Unreachable")

    def _get_response_text(self, model: str, messages: list, max_tokens: int, system: str = None) -> str:
        """Get AI response text with full fallback chain.

        Fallback order:
          1. Requested Anthropic model (3 retries with backoff)
          2. claude-sonnet-4-5 (if not already that model)
          3. OpenAI gpt-4o-mini (if OPENAI_API_KEY is configured)

        Triggers fallback on: 429 (rate limit), 529 (overloaded), 404 (model not found), 400 usage limit

        Returns response text string.
        Raises the last error if all providers fail.
        """
        # Build Anthropic model chain
        anthropic_models = [model]
        if model != "claude-sonnet-4-5":
            anthropic_models.append("claude-sonnet-4-5")

        last_overload_error = None
        for attempt_model in anthropic_models:
            try:
                kwargs = {"model": attempt_model, "max_tokens": max_tokens, "messages": messages}
                if system:
                    kwargs["system"] = system
                response = self._retry_anthropic(**kwargs)
                return response.content[0].text
            except anthropic.APIStatusError as e:
                # 429/529 = overloaded/rate-limited; 400 with usage limit = monthly cap hit
                # 404 = model not found (deprecated/removed model)
                is_usage_limit = e.status_code == 400 and "usage" in str(e).lower()
                is_fallback_error = e.status_code in (429, 529, 404) or is_usage_limit
                if is_fallback_error:
                    last_overload_error = e
                    logging.warning(f"Anthropic {attempt_model} unavailable ({e.status_code}), trying next fallback")
                    if is_usage_limit:
                        break  # No point trying other Anthropic models — whole account is capped
                    continue
                raise

        # All Anthropic models unavailable — try OpenAI as final fallback
        if self.openai_client:
            logging.warning("Anthropic unavailable, falling back to OpenAI gpt-4o-mini")
            openai_messages = []
            if system:
                openai_messages.append({"role": "system", "content": system})
            openai_messages.extend(messages)
            response = self.openai_client.chat.completions.create(
                model=self.openai_model,
                max_tokens=max_tokens,
                messages=openai_messages
            )
            return response.choices[0].message.content

        raise last_overload_error or RuntimeError("All AI providers unavailable")

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

        # Use cheap model (Haiku) if enabled, otherwise main model (Sonnet)
        model = self.cheap_model if self.use_cheap_model else self.main_model

        # Build model fallback chain for JSON parse failures (same as overload fallback)
        fallback_models = [model]
        if model != "claude-3-5-sonnet-20241022":
            fallback_models.append("claude-3-5-sonnet-20241022")

        last_json_error = None
        last_response_text = None

        for attempt_model in fallback_models:
            response_text = self._get_response_text(
                model=attempt_model,
                messages=[{"role": "user", "content": user_input}],
                max_tokens=max_tokens,
                system=SYSTEM_PROMPT,
            )
            last_response_text = response_text

            try:
                result = self._try_parse_json(response_text)
                today = date.today().isoformat()
                for entry in result.get("entries", []):
                    entry["date"] = today
                return result
            except json.JSONDecodeError:
                pass  # Try JSON-fix retry with same model first

            # Retry once asking the same model to fix its JSON
            try:
                retry_text = self._get_response_text(
                    model=attempt_model,
                    messages=[
                        {"role": "user", "content": user_input},
                        {"role": "assistant", "content": response_text},
                        {"role": "user", "content": "Your response had invalid JSON. Please respond with ONLY valid JSON, no extra text."}
                    ],
                    max_tokens=max_tokens,
                    system=SYSTEM_PROMPT,
                )
                result = self._try_parse_json(retry_text)
                today = date.today().isoformat()
                for entry in result.get("entries", []):
                    entry["date"] = today
                return result
            except json.JSONDecodeError as e:
                last_json_error = e
                logging.warning(f"JSON parse failed with {attempt_model}, trying next fallback model")
                continue  # Try next model in chain

        # All Anthropic models failed to produce valid JSON — try OpenAI
        if self.openai_client:
            try:
                logging.warning("All Anthropic models returned invalid JSON, falling back to OpenAI")
                openai_messages = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_input},
                ]
                response = self.openai_client.chat.completions.create(
                    model=self.openai_model,
                    max_tokens=max_tokens,
                    messages=openai_messages,
                )
                openai_text = response.choices[0].message.content
                result = self._try_parse_json(openai_text)
                today = date.today().isoformat()
                for entry in result.get("entries", []):
                    entry["date"] = today
                return result
            except Exception as e:
                logging.error(f"OpenAI fallback also failed: {e}")

        return {
            "error": f"Failed to parse AI response: {str(last_json_error)}",
            "raw_response": last_response_text
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
        modify_prompt = f"""Modify a vocabulary entry based on the user's request. Respond with ONLY valid JSON.

CURRENT ENTRY:
english: {entry.get('english', '')}
chinese: {entry.get('chinese', '')}
explanation: {entry.get('explanation', '')}
example_en: {entry.get('example_en', '')}
example_zh: {entry.get('example_zh', '')}
category: {entry.get('category', '')}

USER REQUEST: {user_request}

RULES (pick ONE that matches):
1. CHANGE PHRASE ("change to X", "save as X"): Set english to new phrase, regenerate ALL fields for the new phrase. Do NOT keep old translations.
2. CHANGE CATEGORY ("category to X", "分类改成X"): ONLY change category. Copy all other fields exactly.
3. CHANGE EXAMPLE ("换个例子", "different example"): ONLY change example_en and example_zh. Copy all other fields exactly.
4. FIX FIELD ("翻译改成", "Chinese should be"): ONLY change that one field. Copy all other fields exactly.
5. ADD PHONETICS ("音标", "pronunciation"): Add /IPA/ to english field only. Copy all other fields exactly.
6. QUESTION (contains ? or 吗/呢/什么): Put answer in question_answer. Copy all entry fields exactly unless the answer requires a change.
7. DEFAULT: Make minimal changes. Copy unchanged fields exactly.

IMPORTANT: For rules 2-7, you MUST copy unchanged fields exactly as shown above. Do NOT rewrite or rephrase them.

Valid categories: {CATEGORY_LIST}

JSON format:
{{"question_answer": null, "entry": {{"english": "...", "chinese": "...", "explanation": "...", "example_en": "...", "example_zh": "...", "category": "..."}}}}"""

        try:
            # Use cheaper model for modifications (falls back to Sonnet 3.5 / OpenAI if overloaded)
            response_text = self._get_response_text(
                model=self.cheap_model,
                messages=[{"role": "user", "content": modify_prompt}],
                max_tokens=800,
            )
        except Exception as e:
            # Log and return error if API call fails
            logging.error(f"API error in modify_entry: {e}")
            return {"success": False, "error": f"API error: {str(e)}"}

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
            logging.error(f"JSON parse error in modify_entry: {e}, response: {response_text[:200]}")
            return {"success": False, "error": f"JSON parse error: {str(e)}"}

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

        detect_prompt = f"""Entries:
{entries_desc}

User feedback: "{user_feedback}"

Which entry (1-{len(entries)}) is the user referring to? Reply with ONLY one number."""

        try:
            # Use cheaper model for simple number detection
            response = self._get_response_text(
                model=self.cheap_model,
                messages=[{"role": "user", "content": detect_prompt}],
                max_tokens=10,
            ).strip()
            # Extract number from response
            num_match = re.search(r'(\d+)', response)
            if num_match:
                num = int(num_match.group(1))
                if 1 <= num <= len(entries):
                    return num - 1
        except Exception as e:
            logging.error(f"Error in detect_target_entry: {e}")

        # Default to first entry
        return 0
