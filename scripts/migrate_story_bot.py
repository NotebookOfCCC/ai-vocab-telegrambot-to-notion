"""
Migrate Story Bot from old format (99. Story Bot.md, table-based)
to new format (100. Story Bot/YYYY-MM.md, heading-based).

- Correctly parses 4-column and 2-column table rows (handles long Notes)
- Revises entries that don't have Revised/Notes using AI
- Writes all entries in heading-based format

Usage: python scripts/migrate_story_bot.py
"""
import os
import sys
import re
import base64
import json
import time as time_module
import requests
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

GITHUB_TOKEN = os.getenv("OBSIDIAN_GITHUB_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
REPO = "NotebookOfCCC/Obsidian"
OLD_FILEPATH = "01. Daily Reflection/99. Story Bot.md"
NEW_DIR = "01. Daily Reflection/100. Story Bot"
API = "https://api.github.com"

headers = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
}


def github_get(filepath):
    """Fetch file content and SHA."""
    url = f"{API}/repos/{REPO}/contents/{filepath}"
    resp = requests.get(url, headers=headers)
    if resp.status_code == 404:
        return None, None
    resp.raise_for_status()
    data = resp.json()
    content = base64.b64decode(data["content"]).decode("utf-8")
    return content, data["sha"]


def github_put(filepath, content, message, sha=None):
    """Write file to GitHub."""
    url = f"{API}/repos/{REPO}/contents/{filepath}"
    encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
    payload = {"message": message, "content": encoded}
    if sha:
        payload["sha"] = sha
    resp = requests.put(url, headers=headers, json=payload)
    resp.raise_for_status()
    print(f"  Written: {filepath}")
    return resp.json()


def parse_old_format(content):
    """Parse old table-based format. Handles multi-line table rows where
    Notes content spans many lines before the closing pipe.

    Strategy: join continuation lines (lines between two | HH:MM | rows)
    back into the previous row, then split by pipes.

    Returns: dict of {date_str: [{"time", "story", "revised", "notes"}]}
    """
    entries_by_date = defaultdict(list)
    current_date = None

    lines = content.split("\n")

    # First pass: reconstruct multi-line table rows
    # A table row starts with | HH:MM |
    # Continuation lines are everything until the next | HH:MM | or ## header
    reconstructed_rows = []
    current_row = None

    for line in lines:
        # Date header
        date_match = re.match(r"^## (\d{4}-\d{2}-\d{2})$", line.strip())
        if date_match:
            if current_row:
                reconstructed_rows.append((current_date, current_row))
                current_row = None
            current_date = date_match.group(1)
            continue

        if current_date is None:
            continue

        # Skip table headers
        if line.strip().startswith("| Time") or line.strip().startswith("|---"):
            continue

        # New table row starts with | HH:MM |
        time_match = re.match(r"^\|\s*(\d{2}:\d{2})\s*\|", line)
        if time_match:
            # Save previous row if exists
            if current_row:
                reconstructed_rows.append((current_date, current_row))
            current_row = line
        elif current_row is not None:
            # Continuation of previous row — append with newline
            current_row += "\n" + line

    # Don't forget the last row
    if current_row:
        reconstructed_rows.append((current_date, current_row))

    # Second pass: parse each reconstructed row
    for date_str, row in reconstructed_rows:
        time_match = re.match(r"^\|\s*(\d{2}:\d{2})\s*\|", row)
        if not time_match:
            continue

        timestamp = time_match.group(1)
        rest = row[time_match.end():]

        # Remove the final trailing | (end of table row)
        # The row might end with "..text.. |" possibly with whitespace
        rest = rest.rstrip()
        if rest.endswith("|"):
            rest = rest[:-1]

        # Now split by the FIRST pipes to get Story, Revised, Notes
        # Story and Revised shouldn't contain pipes, but Notes might
        # So we split on first 2 pipes only
        placeholder = "\x00PIPE\x00"
        rest_safe = rest.replace("\\|", placeholder)

        # Split into at most 3 parts: Story | Revised | Notes
        parts = rest_safe.split("|", 2)
        parts = [p.replace(placeholder, "|").strip() for p in parts]

        story = parts[0] if len(parts) > 0 else ""
        revised = parts[1] if len(parts) > 1 else ""
        notes = parts[2] if len(parts) > 2 else ""

        entries_by_date[date_str].append({
            "time": timestamp,
            "story": story,
            "revised": revised,
            "notes": notes,
        })

    return entries_by_date


def revise_text(text):
    """Call Sonnet to revise text. Returns {"revised": ..., "notes": ...}."""
    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    system_prompt = """You are an English writing coach for a Chinese learner practicing daily storytelling.

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

    try:
        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=2000,
            system=system_prompt,
            messages=[{"role": "user", "content": text}],
        )
        result_text = response.content[0].text
        # Clean up and parse JSON
        cleaned = result_text.strip()
        cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r'\s*```\s*$', '', cleaned)
        cleaned = cleaned.strip()

        # Try direct parse
        try:
            match = re.search(r'\{[\s\S]*\}', cleaned)
            if match:
                return json.loads(match.group())
        except json.JSONDecodeError:
            pass

        # Fix trailing commas
        fixed = re.sub(r',(\s*[}\]])', r'\1', cleaned)
        try:
            match = re.search(r'\{[\s\S]*\}', fixed)
            if match:
                return json.loads(match.group())
        except json.JSONDecodeError:
            pass

        # Extract revised and notes manually with regex
        revised_match = re.search(r'"revised"\s*:\s*"((?:[^"\\]|\\.)*)"\s*,', cleaned, re.DOTALL)
        notes_match = re.search(r'"notes"\s*:\s*"((?:[^"\\]|\\.)*)"', cleaned, re.DOTALL)
        if revised_match and notes_match:
            revised = revised_match.group(1).replace('\\"', '"').replace('\\n', '\n')
            notes = notes_match.group(1).replace('\\"', '"').replace('\\n', '\n')
            return {"revised": revised, "notes": notes}

        print(f"  AI revision: could not parse JSON, raw response:\n    {result_text[:200]}")
        return {"revised": "", "notes": ""}
    except Exception as e:
        print(f"  AI revision failed: {e}")
        return {"revised": "", "notes": ""}


def build_new_format(entries_by_month):
    """Build new heading-based format for each month."""
    result = {}

    for month_str, dates in entries_by_month.items():
        parts = [f"# Story Bot - {month_str}\n"]

        for date_str in sorted(dates.keys(), reverse=True):
            entries = dates[date_str]
            parts.append(f"\n## {date_str}\n")

            for i, entry in enumerate(entries):
                if i > 0:
                    parts.append("\n---\n")

                parts.append(f"\n### {entry['time']}")
                parts.append(entry["story"])

                if entry["revised"]:
                    parts.append(f"\n**Revised:** {entry['revised']}")

                if entry["notes"]:
                    parts.append(f"\n**Notes:**\n{entry['notes']}")

            parts.append("")

        result[month_str] = "\n".join(parts) + "\n"

    return result


def main():
    if not GITHUB_TOKEN:
        print("ERROR: OBSIDIAN_GITHUB_TOKEN not set")
        sys.exit(1)

    # 1. Read old file
    print(f"Reading {OLD_FILEPATH}...")
    content, old_sha = github_get(OLD_FILEPATH)
    if not content:
        print("Old file not found!")
        sys.exit(1)

    # 2. Parse entries
    entries_by_date = parse_old_format(content)
    total_entries = sum(len(v) for v in entries_by_date.values())
    print(f"Found {total_entries} entries across {len(entries_by_date)} days\n")

    if total_entries == 0:
        print("No entries to migrate!")
        sys.exit(0)

    # 3. Show status of each entry
    needs_revision = []
    for date_str in sorted(entries_by_date.keys()):
        for entry in entries_by_date[date_str]:
            has_rev = "YES" if entry["revised"] else "NO"
            has_notes = "YES" if entry["notes"] else "NO"
            preview = entry["story"][:60] + "..." if len(entry["story"]) > 60 else entry["story"]
            print(f"  {date_str} {entry['time']}  Revised={has_rev}  Notes={has_notes}  | {preview}")
            if not entry["revised"]:
                needs_revision.append((date_str, entry))

    print(f"\n{len(needs_revision)} entries need AI revision.")

    # 4. Revise entries that don't have Revised/Notes
    if needs_revision and ANTHROPIC_API_KEY:
        print("\nRevising with AI (Sonnet)...\n")
        for date_str, entry in needs_revision:
            print(f"  Revising {date_str} {entry['time']}...")
            result = revise_text(entry["story"])
            entry["revised"] = result.get("revised", "")
            entry["notes"] = result.get("notes", "")
            if entry["revised"]:
                print(f"    OK: {entry['revised'][:80]}...")
            else:
                print(f"    FAILED - no revision returned")
            time_module.sleep(1)  # Rate limiting
    elif needs_revision:
        print("WARNING: ANTHROPIC_API_KEY not set, skipping AI revision")

    # 5. Group by month
    entries_by_month = defaultdict(dict)
    for date_str, entries in entries_by_date.items():
        month_str = date_str[:7]
        entries_by_month[month_str][date_str] = entries

    # 6. Build new format
    new_files = build_new_format(entries_by_month)

    # 7. Preview
    for month_str, file_content in sorted(new_files.items()):
        filepath = f"{NEW_DIR}/{month_str}.md"
        num_lines = len(file_content.split("\n"))
        print(f"\n--- {filepath} ({num_lines} lines) ---")
        preview = file_content[:500]
        print(preview)
        if len(file_content) > 500:
            print(f"... ({len(file_content)} chars total)")

    # 8. Confirm (auto-confirm with --yes flag)
    print(f"\nReady to write {len(new_files)} file(s) to GitHub.")
    if "--yes" not in sys.argv:
        confirm = input("Proceed? (y/n): ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            sys.exit(0)

    # 9. Write new files
    for month_str, file_content in sorted(new_files.items()):
        filepath = f"{NEW_DIR}/{month_str}.md"
        existing, existing_sha = github_get(filepath)
        if existing:
            github_put(filepath, file_content, f"migrate: story bot {month_str}", sha=existing_sha)
        else:
            github_put(filepath, file_content, f"migrate: story bot {month_str}")

    print(f"\nMigration complete! {total_entries} entries migrated.")
    print(f"Old file still at: {OLD_FILEPATH} (delete manually when ready)")


if __name__ == "__main__":
    main()
