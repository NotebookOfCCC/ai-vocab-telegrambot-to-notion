# Obsidian Dual-Save Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** When saving vocab entries to Notion, simultaneously append them to a local Obsidian markdown table file via GitHub API.

**Architecture:** New `obsidian_vocab_handler.py` wraps `github_handler.py`'s `_get_file`/`_put_file` pattern. On each save, it appends a row to the current Vocabulary_NNN.md file, auto-creating a new file at 1000 entries.

**Tech Stack:** aiohttp (GitHub API), existing github_handler patterns

---

### Task 1: Create obsidian_vocab_handler.py

**Files:**
- Create: `obsidian_vocab_handler.py`

- [ ] **Step 1: Create the handler with append_entry() method**

Core logic:
- Reuse GitHub API pattern from github_handler.py (_get_file, _put_file)
- `append_entry(entry)`: fetches current file, counts rows, appends entry as table row
- Auto-creates new Vocabulary_NNN.md when current file hits 1000 entries
- Escapes pipe characters in cell content
- Entry fields mapped to: #, English, Chinese, Explanation, Example EN, Example ZH, Category, Date

- [ ] **Step 2: Commit**

### Task 2: Integrate into bot.py save flow

**Files:**
- Modify: `bot.py` (save handler ~line 1028, batch save ~line 787, imports, main())

- [ ] **Step 1: Import and initialize obsidian_vocab_handler in main()**

Add global `obsidian_handler`, initialize in `main()` alongside notion_handler.

- [ ] **Step 2: Add obsidian save call after Notion save succeeds**

In both save paths (single save ~line 1028-1034, batch save ~line 787-791):
- After `result["success"]`, call `await obsidian_handler.append_entry(entry)` in background
- Log errors but don't fail the save (Notion is primary, Obsidian is secondary)

- [ ] **Step 3: Update confirmation messages**

Change "Saved to Notion" → "Saved to Notion + Obsidian"
Change "Replaced" message similarly.

- [ ] **Step 4: Commit**

### Task 3: Update CLAUDE.md and README

- [ ] **Step 1: Update CLAUDE.md** with Obsidian dual-save docs (architecture, env vars, recent changes)
- [ ] **Step 2: Commit and push**
