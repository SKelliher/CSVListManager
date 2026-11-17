# CSVListManager — Data Structure Summary

**Date:** 2026-11-17
**Source of truth:** §3.9 of `docs/nextact_grid_requirements.md` (normative). This document is a compact overview of the structures, their type options, and the format choices behind them.

---

## 1. Overview

The tool touches exactly six data structures. All are plain, human-editable files in UTF-8; nothing is binary and nothing lives in a database.

| # | Structure | File format | Owned by | Purpose |
|---|---|---|---|---|
| 1 | Store | CSV (RFC 4180) | User (source of truth) | The actual data |
| 2 | Schema | YAML | User (hand-edited) | Column names, order, types, lookups |
| 3 | Lookup list | CSV or inline list | User | Dropdown values (+ descriptions) |
| 4 | Application configuration | YAML | User | Repositories, paths, scripts |
| 5 | Change log | CSV (append-only) | Tool (append-only) | History of every tool-made change |
| 6 | Preferences | JSON | Tool (also hand-editable) | Selected repo, mode, view state |

One derived value — the **store revision** — is not stored anywhere: it is the SHA-256 hex digest of the store's bytes, recomputed on load and checked at save time to detect external edits.

---

## 2. Store (CSV)

- One header row + one record per row; column order follows the schema.
- **Every value is a raw string.** Typing is interpretive, applied by the schema — the file never encodes types itself.
- Round-trip must be lossless: quoted fields, embedded newlines (multi-line notes), commas/quotes inside fields, and column order are preserved byte-for-byte. Only sorts and saves reorder or change bytes, and sorts never rewrite the file.

### Value types (per column, from the schema)

| Type | Accepted value | Empty? | Sort order | Editing UI |
|---|---|---|---|---|
| `date` | ISO `YYYY-MM-DD` | yes | chronological | date picker / typed |
| `datetime` | ISO `YYYY-MM-DD HH:MM` | yes | chronological | datetime picker / typed |
| `dropdown` | a lookup value | yes | lookup order | dropdown/select |
| `text` | single-line string | yes | lexical | inline cell |
| `note` | multi-line string (embedded newlines) | yes | presence/length at most | expanded pane, byte-exact |

Key property: **no validation policing** (N7). Out-of-schema values already in the file are displayed as-is, never blocked or rewritten.

### Optional managed flags (datetime columns only)

- `on_create` — set once when a row is created through the tool; never touched again.
- `on_update` — refreshed on every saved edit of that row.

These are ordinary datetime fields with optional logic attached; an instance without `Created`/`Updated` simply omits them. This is the only automatic column touching the tool performs.

---

## 3. Schema (YAML)

Declares the column set; changing it requires no code change.

```yaml
columns:
  - name: Priority          # unique, non-empty
    type: dropdown          # date | datetime | dropdown | text | note
    lookup:
      values: [A, B, C, Z]  # inline list — option 1
  - name: Tag
    type: dropdown
    lookup:
      file: nextact_tags.csv # external CSV — option 2
      column: tag            # which column supplies values
  - name: Next
    type: date
  - name: Created
    type: datetime
    on_create: true          # optional, datetime only
```

Format choices made:

- **Format:** YAML (settled) — human-readable, hand-editable, comments allowed.
- **Lookup source:** exactly one of inline `values` or external `file` + `column`.
- **Editing:** in a text editor only; no schema editing in the HTML UI in v1.

---

## 4. Lookup list

Two representations, per dropdown column:

| Option | Where | Best for |
|---|---|---|
| Inline list | `lookup.values` in the schema | Short, stable sets (e.g. priorities) |
| External CSV | `lookup.file` + `lookup.column` | Longer lists with metadata (e.g. tags with description, parent) |

Rules common to both:

- Plain and human-editable.
- The tool may offer an "add value to lookup" convenience.
- **Unknown values tolerated:** a store value absent from the lookup is displayed as-is, never blocked or removed.

---

## 5. Application configuration (YAML)

```yaml
repository_root: .          # base for repository paths
preferences: local/preferences.json

repositories:               # ≥1 entry; key = repository id
  sample:
    name: Synthetic NextAct
    directory: examples/nextact
    store: nextact.csv
    schema: schema.yaml
    log: changes.csv
    scripts:                # optional
      - name: archive
        command: [python3, archive.py]
        description: Move completed (priority Z) rows into archive.csv
```

One repository = one store CSV + its schema + its lookup files + its log, rooted in a directory. Adding an instance (e.g. a future work list) is a config entry, not a code change. Scripts are external commands; the tool only supplies paths, runs them, and logs the result.

---

## 6. Change log (CSV, append-only)

Fixed header: `timestamp,event,repository,details`

| Field | Type |
|---|---|
| `timestamp` | ISO 8601 with UTC offset, written once at append |
| `event` | `cell_edit` \| `row_add` \| `row_delete` \| `save` \| `script_run` |
| `repository` | repository id |
| `details` | JSON object (or empty), type-specific |

`details` payloads:

| Event | Payload |
|---|---|
| `cell_edit` | `{row, column, old, new}` |
| `row_add` | `{row, values[]}` |
| `row_delete` | `{row, values[]}` — full prior values |
| `save` | `{previous_revision, revision, edit_count, addition_count, deletion_count}` |
| `script_run` | `{script, status, exit_code, output, detail?}` |

Constraints: append-only, never rewritten or truncated by the tool, viewable in the app but not editable there. One log per repository, stored in the repository directory.

---

## 7. Preferences (JSON)

```json
{
  "selected_repository": "nextact",
  "modes":    { "sample": "read-only" },
  "views": {
    "sample": {
      "note_visible": false,
      "column_widths": { "Label": 84 }
    }
  }
}
```

| Field | Type | Notes |
|---|---|---|
| `selected_repository` | string | must match a configured repository id |
| `modes` | repo id → `editable` \| `read-only` | persisted per repository |
| `views.<id>.note_visible` | boolean | note pane visibility |
| `views.<id>.column_widths` | column name → int (pixels) | keyed by schema column name, so it survives schema changes |

View preferences only; never written into the CSV. Filters are deliberately absent — they are session-only.

---

## 8. Store revision (derived, not stored)

- **Definition:** SHA-256 hex digest of the store file's exact bytes.
- **Use:** the client sends the revision it loaded; a save is accepted only if the revision still matches. This is how external edits (e.g. in VS Code) made while the grid is open are detected (R3).
- **Why not a file:** a stored counter or index would be a shadow state that could disagree with the file; deriving it from the bytes keeps the CSV the single source of truth.

---

## 9. Design rationale at a glance

| Decision | Choice | Why |
|---|---|---|
| Store format | Plain CSV | Human-readable, works in VS Code/Obsidian/scripts; no migration |
| Type storage | In schema, not in the file | The CSV stays pure data; schema changes need no data migration |
| Schema format | YAML | Hand-editable, comments, nested lookup config |
| Log format | CSV with JSON details column | Machine- and human-readable, append-friendly |
| Preferences format | JSON | Trivially read/written by both Python and JS |
| Revision | Byte digest, not stored | No shadow state; external edits always detectable |
| Validation | Permissive (display as-is) | The store stays honest; the tool never rewrites user data |
