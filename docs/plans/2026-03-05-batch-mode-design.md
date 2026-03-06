# Batch Mode Design

## Problem

Current vocab flow is synchronous: type one phrase → wait for analysis → save → repeat.
This is time-consuming when the user has many phrases to save. The user wants to dump
a list of phrases, walk away, and come back to save them.

## Solution

Batch mode: multi-message collection phase, then parallel analysis, then all cards
sent at once with individual Save/Skip buttons.

---

## Persistent Reply Keyboard

Add a persistent reply keyboard (always visible) with two buttons:

```
[Batch]  [Word Count]
```

- **Batch** — enters collection mode
- **Word Count** — queries all Notion DBs and replies with word count per database

---

## Word Count Feature

Tap [Word Count]:
- Bot queries all configured Notion DBs in parallel
- Replies with count per DB, e.g.:
  ```
  Word Count:
  - Primary DB: 1,243 words
  - Archive DB: 1,876 words
  - Total: 3,119 words
  ```

---

## Batch Mode Flow

### Phase 1: Collection

1. User taps [Batch]
2. Bot sends: "Batch mode on. Send your phrases one by one." with an [Analyze (0)] inline button
3. Each message the user sends adds to the queue; bot updates the button: [Analyze (1)], [Analyze (2)], etc.
4. User taps [Analyze (N)] when done

### Phase 2: Analysis

- Bot replies "Analyzing N phrases..." and processes all queued phrases in parallel
- Once ALL analyses are complete, bot sends all cards together (not one at a time)

### Phase 3: Results

- One message per phrase, each with:
  ```
  [Save]  [Skip]
  ```
- Cards persist — user can come back later and save

### Concurrent single-phrase input

While batch cards are sitting unsaved, new text the user sends is treated as a normal
single-phrase analysis (independent session). Unsaved batch cards are unaffected.

---

## Input Format

Phrases can be messy, e.g.:
```
block out (from article)
paradigm shift
give it a shot - heard in meeting
the report was quite compelling
```

Each line is treated as one input. AI handles extraction of the actual phrase from
context notes (same as current analyze_input logic).

---

## Key Implementation Files

- `bot.py` — add reply keyboard, batch session state, collection handler, word count handler
- `notion_handler.py` — add word count query method (count per DB)

---

## Out of Scope

- Saving entire batch at once ("Save All" for batch) — user saves individually per card
- Batch mode cancel / clearing queued phrases before analysis
- Batch-specific model selection
