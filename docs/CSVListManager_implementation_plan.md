# CSVListManager — Implementation Plan

**Status:** Complete; all phases plus built-in row deletion are implemented and verified. The repository is public.
**Date:** 2026-11-16
**Updated:** 2026-11-16
**Requirements:** `docs/nextact_grid_requirements.md`
**License:** MIT

## 1. Project and repository setup

1. Create the code project at `~/Code/GitHub/CSVListManager`.
2. Initialize Git and create a **private** GitHub repository linked to that directory. Make it public only after the success tests pass and publication review is complete.
3. Add the MIT license, README, `.gitignore`, and a snapshot of the approved requirements under `docs/`.
4. Keep all real data, personal configuration, and real change logs outside the Git repository. Commit only source, tests, and synthetic example data.

Terminology: the **code repository** contains CSVListManager; a CSVListManager **data repository** is a configured CSV datastore and its supporting files.

## 2. Architecture

Use two deep modules behind narrow interfaces:

- **Python service (stdlib-first):** owns configuration loading, CSV/schema parsing, atomic writes, script execution, change-log appends, and the HTTP API.
- **HTML/vanilla-JS grid:** owns repository selection, editable/read-only modes, sorting, view-only filtering, column sizing, note-pane visibility, inline editing, the multi-line note pane, script controls, and log viewing.

No database or shadow index. The CSV remains the source of truth.

## 3. Repository configuration

Create an application-level YAML configuration with a configurable repository root and a list of named data repositories. Each repository entry defines its directory, store CSV, schema YAML, and optional scripts. Persist the last-selected repository, view mode, note-editor visibility, and per-column widths in local application preferences, not in the CSV. Column widths are keyed by repository and schema column name. Filters are session-only by default and are not persisted in the first implementation.

Each repository directory contains:

- the store CSV;
- its YAML schema;
- lookup CSVs where needed;
- an append-only CSV change log;
- an archive CSV where configured by a script.

Row deletion is a built-in editing operation (added 2026-11-17 after a CRUD gap review): rows are marked for deletion in the browser and removed only on explicit save, logged as `row_delete`. Archive semantics remain script-based.

Schema columns define `name`, `type` (`date`, `datetime`, `dropdown`, `text`, `note`), optional lookup source, and optional `on_create`/`on_update` managed flags for datetime columns. Validate configuration at startup; report actionable errors rather than modifying user files.

## 4. Service API and file safety

Provide narrow endpoints for listing/selecting repositories, loading a store and schema, saving edits, running configured scripts, and reading the change log.

- Parse and serialize RFC 4180 CSV with Python's `csv` module; preserve quoted multi-line fields and column order.
- Save explicitly through an atomic temporary-file-and-replace operation, with a backup on failure.
- Never reorder existing rows as a result of sorting or filtering. Append newly created rows at the bottom.
- Set `on_create` columns only for newly created rows and refresh `on_update` columns only when a row is saved with changes.
- Record edits, saves, and script runs in the append-only log.
- Bind to localhost only; require no network access during runtime.

## 5. Browser interface

- Startup repository dropdown, defaulting to the last-used repository.
- Sticky-header grid with stable sorting on non-note columns.
- Inline date/datetime, dropdown, and text editors; multi-line note editor pane.
- Show/hide control for the note editor, adjustable column widths, and exact-value date/dropdown filters as defined in §6.
- Editable/read-only toggle with a visible mode indicator; disable editing and save in read-only mode.
- Explicit Save, dirty-state indicator, and unsaved-changes warning.
- Configured-script menu with result feedback and reload after success.
- Read-only in-app change-log viewer.

## 6. Browser view customization and filtering (next phase)

Implement this focused UI iteration after the basic browser grid and before the script runner. These features are view concerns: they require no CSV or schema format changes and must not change save semantics.

- **Note editor visibility:** provide a show/hide toggle that collapses the note panel and gives the grid the full available width. Note cells remain visible and their contents remain in the grid data. Reopening the panel restores the previously selected note where possible. Persist visibility per repository in local preferences.
- **Column widths:** provide drag handles on column borders with sensible minimum/maximum limits and horizontal overflow. Persist widths per repository and schema column name in local preferences so the behavior remains generic across schema changes.
- **Single-value filters:** add a filter row beneath the sticky headers for `date` and `dropdown` columns. Each filter matches one exact value. Date filters match `YYYY-MM-DD`; dropdown choices include lookup values and unknown values actually present in the store. Include an explicit blank-value choice for both types.
- **Filter composition:** combine active filters with AND logic and with the current sort. Provide a visible `showing X of Y rows` count and a Clear filters action. Filters are session-only initially; no filter is written to the CSV or application data files.
- Extend local preference handling only where needed for note-panel visibility and widths. Filtering, sorting, and view customization must never reorder or rewrite records by themselves, and unsaved edits must remain dirty even when their rows are filtered out of view.

## 7. Script interface

Scripts are configured external commands, initially including archive. The service supplies the selected repository directory and store path, captures exit status/output, logs the run, and reloads/validates the store afterward. Scripts own their domain logic and atomic data transformations; failures return a visible error and do not produce a false success state.

## 8. Test data repository and automated tests

Create a synthetic test data repository using the nextact structure but no real personal records. Cover:

- quoted commas, quotes, empty fields, and embedded newlines;
- byte-level round-trip of untouched content;
- sorting without file reordering and new-row append behavior;
- all five field types and managed Created/Updated behavior;
- read-only enforcement;
- schema changes without code changes;
- note-panel hide/show behavior and per-repository column-width persistence;
- exact date/dropdown filtering, including blank and unknown dropdown values, combined filters, row counts, and clearing;
- filtering and sorting during dirty/save workflows without file reordering or losing hidden edits;
- archive success/failure and corresponding log entries.

## 9. Execution and verification order

1. Initialize private GitHub code repository and base documentation. **Complete.**
2. Implement Python service and configuration parsing. **Complete.**
3. Implement browser grid and editing modes. **Complete.**
4. Implement note-panel visibility, adjustable column widths, and exact-value date/dropdown filters with UI/model tests. **Complete.**
5. Implement script runner and change-log viewer. **Complete.**
6. Add synthetic test repository and automated tests.
7. Run tests, start the service, exercise the UI against the test repository, and diff files after saves.
8. Report actual results. Do not switch the live `nextact.csv` to the tool until the test-repository success tests pass.

## 10. Publication gate

After verification: review committed files for personal data, finalize README installation/usage instructions, confirm MIT license, then make the GitHub repository public only with your approval. **Complete 2026-11-17:** personal paths were scrubbed from all commit history, README installation instructions were added, and the repository was made public with approval.
