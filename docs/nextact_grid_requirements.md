# NextAct Grid — Requirements (Implementation-Independent, Generic)

**Status:** COMPLETE — all open questions settled; ready for implementation plan
**Date:** 2026-11-16
**Purpose:** Define WHAT the tool must do, without prescribing HOW (no language, framework, or UI library decisions here). The tool is a **generic grid over a configured CSV store**, not a hard-coded to-do app. Implementation design follows in a separate plan document once these requirements are approved.

---

## 1. Background and Problem

Open action and calendar items are currently tracked in `nextact.csv` — one row per item, sorted and edited with a CSV tool in VSCode. The pattern works; the implementation is clunky (awkward date editing, no inline sorting, multi-line Detail cells hard to view and edit).

The same pattern is used at work with OneNote tables (two-user list). Any tool chosen or built must not disturb the pattern itself — the store is a plain, human-readable file, editable in any text editor. The work-environment list is a possible future instance of the same tool.

An Obsidian-Tasks-style approach was trialed and rejected (view separate from storage). Zenvoy was trialed (2026-11-16) and rejected (CSV view did not open; app non-obvious; immature).

## 2. The Tool in One Sentence

A configurable, local, sortable grid view over plain CSV files ("repositories"), with typed columns, lookup-backed dropdowns, a multi-line note editor, a script interface for user-defined datastore operations, and a non-editable change log — where the column structure is data (a configuration), not code.

## 3. Core Model

### 3.1 Store

- One store = one plain CSV file (RFC 4180): header row + rows.
- Embedded newlines in quoted fields are first-class (multi-line note cells). Round-trip must be lossless.
- Column structure is defined by a **schema/config**, not inferred (see 3.3). The CSV header column names and the schema must agree.

### 3.2 Field types

Each column in the schema has one of these types. **All fields of every type permit empty (NULL) values.**

| Type | Behavior | Display / editing |
|---|---|---|
| `date` | ISO `YYYY-MM-DD` or empty | Date picker or typed entry; sortable chronologically |
| `datetime` | ISO 8601 `YYYY-MM-DD HH:MM` or empty | Datetime picker or typed entry; sortable chronologically |
| `dropdown` | One value from a lookup list, or empty | Dropdown/select in the grid; lookup source is a separate plain file or a schema-listed set |
| `text` | Single-line free text | Inline cell editing; sortable lexically |
| `note` | Multi-line free text (embedded newlines; may itself contain sub-task markers or any content) | Edited in an expanded pane, not crammed into a cell; preserved byte-for-byte; NOT sortable by content (sorts by presence/length at most) |

Types drive the editing UI and sort order only. Validation is permissive: out-of-schema values in the file are displayed as-is, never blocked or rewritten (the human-readable store stays honest).

### 3.2.1 Managed-column logic (optional, per column)

Any `datetime` column may carry a **managed flag** in the schema, giving it application logic. Two flags exist:

- `on_create` — set once when the row is created through the tool; never modified afterward (by the tool or scripts). Intended for a `Created` column.
- `on_update` — refreshed whenever any field of the row is saved through the tool. Intended for an `Updated` column.

Flags are properties of the column, not special column kinds: `Created` and `Updated` are ordinary `datetime` fields — visible, sortable, externally editable, empty-permitted — with optional logic attached. An instance without them simply omits them from the schema; a datetime column without flags has no logic at all (N7 governs edits made outside the tool). This is the only auto-touching of columns the tool performs (see §8).

### 3.3 Schema / configuration

- The column set (names, order, types, per-dropdown lookup source) is declared in a **schema file** stored alongside the store (e.g. same directory; plain human-readable format — CSV, YAML, or JSON; format decision deferred to implementation).
- The schema is **user-editable by hand** in a text editor. Schema editing in the HTML interface is explicitly NOT required in v1 (not forbidden as a later addition).
- Adding, removing, renaming, or reordering columns is a schema edit; the tool adapts with no code change. (Backfilling data for new columns is the user's job in the file; empty is valid everywhere.)
- A store's file path is configuration, not hard-coded: the tool is parameterized by (store CSV, schema). More than one instance (e.g. personal list now, work list later) = more than one config entry.

### 3.4 Lookup lists

- Each `dropdown` column names a lookup source: a small plain file (e.g. `nextact_tags.csv`: tag, description, parent) or an inline list in the schema.
- Lookup files are plain, human-editable. The tool may offer an "add value to lookup" convenience but must tolerate values present in the store but absent from the lookup (shown as-is, never blocked).

### 3.5 Fixed header

- The grid always shows a fixed/sticky header row, remaining visible when the body scrolls.

### 3.6 Repositories (instances)

- A **repository** is one configured instance: a store CSV + its schema + its lookup files, rooted in a **repository directory** whose default location is configurable.
- The tool supports multiple repositories. At startup the user picks the repository from a dropdown (persisted choice between runs).
- The tool itself knows nothing of any repository's semantics; all meaning (priorities, archive rules, tag hierarchies) lives in the repository's configuration and data.

### 3.7 Viewing modes

- Two modes: **editable** and **read-only**. Read-only renders the same grid but disables all editing (and save); a visible mode indicator prevents confusion. Mode is a user toggle, persisted per repository.

### 3.8 Change log

- The tool maintains a **change log** recording every change made through the application: cell edits, row additions, saves, sorts (optional detail), and every script execution (script name, parameters, result, row counts).
- The log itself is a plain CSV (machine- and human-readable) but is **non-editable through the tool**: append-only, viewable in the app, never rewritten or truncated by the UI. It lives in the repository directory.

## 4. The Current Instance (nextact.csv)

The existing file is the first configured instance. Its schema expresses the established pattern:

| Column | Type | Lookup | Meaning in this instance |
|---|---|---|---|
| `Priority` | dropdown | inline: A, B, C, Z | A=urgent, B=current, C=calendar/tickler, Z=done (awaiting archive) |
| `Next` | date | — | trigger date: when the item should next surface |
| `Last` | date | — | user-managed "Last Action" date in this instance's workflow (no intrinsic meaning to the tool; see §9) |
| `Tag` | dropdown | `nextact_tags.csv` (tag, description, parent — mirrors Obsidian level-two hierarchy) | domain tag |
| `Label` | text | — | short human name |
| `Detail` | note | — | multi-line scratchpad: sub-task markers (`+`, `-`, `( )`, `*`), URLs, commands, evidence |

Lifecycle (instance semantics, not tool semantics): item dormant until `Next`; `Last` is maintained by the user as "last action" (or by an external script if one is written — the tool has no built-in logic for it); completion sets `Priority=Z`; `Z` rows are archived out periodically by the archive script (R9).

The tool knows none of this — the archive rule is per-instance configuration. If this instance later wants `Created`/`Updated` columns, it adds them as flagged `datetime` fields in the schema (3.2.1); today `Last` remains a plain, user-managed date with no tool logic attached.

### 4.1 Detail-field sub-task markers (instance convention)

`Detail` lines use lightweight markers representing sub-tasks within the item:

- `+ ` — complete sub-task
- `- ` — open subtask
- `( )` — checkbox-style sub-item
- `* ` — note
- unmarked lines — free memo, URLs, commands, completion evidence

Markers are user convention, not enforced structure. The tool must **preserve them exactly**; recognizing them for display is desirable but optional (R4).

## 5. Goals

- **G1.** Replace the clunky VS Code CSV editing experience with a grid that makes common operations (sort, edit dates, pick dropdown values, update notes) fast.
- **G2.** Preserve the pattern exactly: same file, same columns, same semantics. No migration.
- **G3.** Keep the store human-readable and machine-readable; the file must remain usable in VS Code, Obsidian, scripts, and by hand at all times.
- **G4.** Local-only. No cloud, no accounts, no sync services.
- **G5.** Generic by design: schema changes, new columns of the same four kinds, and new instances require configuration only — no tool modification.
- **G6.** Reduce future rework: the design must absorb later additions (recurrence scripting, per-field rules) without schema surgery or tool surgery.

## 6. Non-Goals

- **N1.** No multi-user or LAN collaboration (work OneNote list stays separate; if ever moved over, it is a new instance of the same tool).
- **N2.** No redefinition of the user's existing pattern: priorities, deadlines, and Detail markers stay as they are.
- **N3.** No recurrence/rollover automation in v1 (explicitly deferred — "possible scripting, but not necessary").
- **N4.** No schema editing in the HTML interface in v1 (the schema is hand-edited in a text editor).
- **N5.** No plugin ecosystem, theming, or general-purpose note features. Single-purpose tool.
- **N6.** No Obsidian-Tasks-style structure (task syntax in markdown, separate views). Rejected twice by user.
- **N7.** No validation policing: the tool never rewrites or rejects data the user typed into the file directly.

## 7. Requirements

### Storage & integrity

- **R1.** The tool reads and writes the configured CSV in place. No copy, no shadow database, no index file that owns state.
- **R2.** CSV round-trip must be lossless: quoted fields, embedded newlines in note cells, commas/quotes inside fields, and column order all preserved. Sort order changes are the only re-serialization expected (see R10).
- **R3.** The file remains valid while the tool is closed, and openable in VS Code/any editor while the tool is running. (Concurrency need not be solved — single user — but the tool must not corrupt or lock the file in a way that breaks external editing.) External edits made while the grid is open should be detected and reloadable — at minimum warned about, never silently overwritten.

### Viewing & editing

- **R4.** Grid view: one row per record; fixed/sticky header (3.5). Note-type fields display in an expanded/editor pane preserving all content byte-for-byte. Text/date/dropdown fields edit inline in the grid.
- **R5.** Two view modes (3.7): editable and read-only. Read-only disables all editing and save; visible mode indicator.
- **R6.** Sorting on any non-note column (date, dropdown, text), by click or control; stable and repeatable. Note columns sort by, at most, presence/length.
- **R7.** Editing follows field type: date/datetime pickers or ISO keyboard entry; dropdown constrained to lookup values (existing-but-unknown values still display); text inline; note in pane. Managed columns (3.2.1): an `on_create` datetime column is set at row creation and never touched again; an `on_update` datetime column is refreshed on every saved edit. The tool performs **no other** automatic column updates — user-managed columns such as the nextact instance's `Last` change only when the user (or an external script) changes them.
- **R8.** New rows are appended at the bottom of the file on save. Sorting is view-only and never rewrites the file.

### Script interface

- **R9.** The tool provides an interface to run user-defined scripts against the repository's datastore. Scripts are external programs (the archive being the first instance) whose logic lives outside the application; the tool supplies the repository paths/parameters, runs the script, and reports the result. Scripts are declared in repository configuration (name, command, description).
- **R10.** Every script run is written to the change log (3.8) with script name, parameters, outcome, and affected-row counts. A script failure must leave the datastore untouched (scripts are responsible for their own atomicity; the tool verifies store validity after a run and refuses to display a corrupt store, pointing at the log).

### Schema & lookups

- **R11.** Column structure (names, order, types, lookup sources) comes from the schema file (3.3); the tool must operate correctly when the schema changes, with no code change. Schema is hand-editable (YAML settled).
- **R12.** Dropdown lookup sources as in 3.4: plain files or inline schema lists, human-editable, unknown values tolerated.

### Persistence & logging

- **R13.** Save semantics: explicit save (button/keystroke) rather than write-on-every-keystroke. Sorting is view-only (R8); new rows append at the bottom. A visible dirty-state indicator warns when unsaved changes exist, with a warning on close/quit.
- **R14.** Change log (3.8): every change made through the tool (edits, saves, script runs) is recorded to an append-only CSV in the repository directory; the log is viewable in the app but never editable or truncated by it.

### Non-functional

- **R15.** Local execution only; no network access required at runtime (updates excluded).
- **R16.** The tool must start fast and open the grid immediately on a file of the current size (~185 lines) and comfortably beyond (thousands of rows).
- **R17.** Usable by a single user day-to-day; conventions documented in a short README stored beside the CSVs.
- **R18.** Architecture (settled): HTML grid front end + small Python local service for all file I/O (R-arch). The service hosts: store read/write, script execution, change-log appends, and repository configuration.

## 8. Open Questions (for user review)

1. **Schema file format (3.3):** YAML — settled {OK on YAML}.
2. ~~Auto-bump column (R7)~~ — settled: no auto-bump of user columns. Instead, `datetime` is a generic field type (3.2) and optional per-column managed flags (`on_create`, `on_update`, 3.2.1) implement `Created`/`Updated`; `Last` in the nextact instance is a plain user-managed "Last Action" date with no tool logic {Q2}.
3. ~~Sort persistence (R10)~~ — settled: sorting is view-only and never rewrites the file; new entries append at the bottom {Q3}.
4. ~~Archive as built-in action~~ — settled: archiving is one instance of the generic script interface (R9); archive logic lives outside the application {Q4}.
5. ~~Tag lookup location~~ — settled: repositories have a configurable default directory; multiple repositories are picked from a dropdown at startup {Q5, Q7}.
6. ~~Architecture~~ — settled: Option B, HTML grid + Python service {Q6}.
7. **Repository for testing:** a new test repository (clone of nextact.csv structure) is part of the success test {§10}.

*No open questions remain.*

## 10. Distribution

- **R19.** The tool is intended for publication (GitHub, open source). Consequences:
  - No personal paths, usernames, or instance-specific assumptions in code — all instance data comes from configuration.
  - Ships with: README, license, a sample repository (store + schema + lookup + example data, not the user's real data), and the archive script as the first example script.
  - Runnable by a third party from a clean checkout with only standard tooling (Python stdlib for the service).

## 11. Success Test

- Create a new test repository (a clone of the nextact structure) — this is the required first step.
- Open the tool on the test repository; sort by `Priority` then `Next`; edit two dates, one dropdown, and one note; save; reopen the file in VS Code and confirm every byte outside the intended edits is unchanged, and that sorting did not reorder the file while new rows landed at the bottom.
- Edit the schema (add a column); reopen the tool; the column appears with correct type behavior, with existing rows intact.
- Run the archive script with a chosen cutoff via the tool's script interface; confirm rule-matching rows moved, counts match, both files remain valid CSVs, and the change log records the run.
- Toggle read-only mode; confirm editing is disabled.
- Work for a week without opening VS Code to edit the list.
