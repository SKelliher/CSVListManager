# CSVListManager

CSVListManager is a configurable, local grid for editing plain RFC 4180 CSV data stores. The CSV remains the source of truth: there is no database, shadow index, cloud account, or runtime network dependency.

This repository contains a Python standard-library service and a dependency-free HTML/vanilla-JavaScript grid. Together they provide typed schemas, human-editable lookup files, safe explicit saves, repository preferences, stable view-only sorting, and an append-only CSV change log.

## Implemented

- YAML application configuration and schema validation with actionable errors.
- Multiple named data repositories and per-repository editable/read-only modes.
- RFC 4180 parsing through Python's `csv` module, including quoted commas, quotes, empty values, and embedded newlines.
- Field-level save patches that leave all untouched bytes, quoting, record order, and line endings unchanged.
- Atomic temporary-file-and-replace saves and revision checks that prevent overwriting external edits.
- New-row appends and optional `on_create`/`on_update` datetime columns.
- Append-only cell-edit, row-addition, and save log events.
- A localhost-only JSON HTTP API and locally served browser interface.
- Sticky-header grid with stable ascending/descending sorting and no file reordering.
- Exact-value date/dropdown filters with blank/unknown values, combined filtering, row counts, and clearing.
- Draggable persisted column widths and a persisted show/hide note-editor control.
- Native date/datetime controls, text inputs, lookup dropdowns, and a full multi-line note pane.
- Configured external scripts run from the browser with confirmation, captured output, success/failure feedback, and an automatic reload and store re-validation afterward.
- Per-row mark-for-deletion applied on explicit save, with undo and `row_delete` log entries.
- A read-only in-app change-log viewer with refresh.
- Add-row workflow, explicit Save button/shortcut, dirty indicator, and unsaved-change warnings.
- A completely synthetic NextAct example and automated unit/HTTP/JavaScript tests.

The external script runner and in-app change-log viewer are not implemented yet. The live personal NextAct store is not connected by any shipped configuration.

## Requirements

- Python 3.11 or later
- A modern browser
- No runtime packages outside the Python standard library
- Node.js 20 or later only for the optional JavaScript model tests

## Run against the synthetic example

From a source checkout:

```sh
python3 -m csvlistmanager --config config.example.yaml --check
python3 -m csvlistmanager --config config.example.yaml
```

The service listens on `127.0.0.1:8765`. Open <http://127.0.0.1:8765> in a browser to use the grid. `--port 0` selects an available port. Non-loopback bind addresses are rejected.

The checked-in example can be edited through the API, so its files will become modified after saves. To keep the checkout pristine, copy `examples/nextact` and `config.example.yaml` to a local directory and adjust the paths in the copied configuration. The ignored `local/` directory is suitable for experiments.

## Browser editing

Click a non-note column heading to sort ascending, again for descending, and a third time to restore file order. Sorting changes only the view. Empty values sort last, and equal values retain their stable file order.

Text, date/datetime, and dropdown fields edit inline. Existing values that are invalid for a native date/datetime control fall back to a text input so they remain visible and unchanged. Unknown dropdown values are displayed as such. Managed datetime columns are visible but locked because the service owns their values.

Select any note cell to open the full note pane. **Hide note editor** collapses the panel without hiding note cells; reopening restores the selected note where possible. Panel visibility is persisted per repository. Note edits retain the cell's original newline convention, including CRLF embedded newlines. In read-only mode, notes remain selectable and readable while all editing and saving controls are disabled.

Drag a column's right border to resize it, or focus its resize separator and use the arrow keys. Widths from 80 to 600 pixels are persisted per repository and schema column name.

The second header row filters `date` and `dropdown` columns by one exact value. Choices include blank, lookup values, and unknown values actually present in the store. Multiple filters combine with AND logic and the active sort. The status bar shows `Showing X of Y rows` and provides **Clear filters**. Filters are session-only, are not written to preferences or CSV files, and remain active across saves/reloads in the same browser session. Editing and saving include dirty rows even when filters hide them.

**Add row** creates an in-memory row; **Save** or Ctrl/Cmd+S writes all pending changes explicitly. New rows always append at the bottom of the CSV regardless of view sorting or filtering. The per-row ✕ control marks an existing row for deletion (click again or ↩ to undo); deletions apply only on Save, never reorder the file, and are logged as `row_delete` entries with the removed values. Reload, repository switching, and browser closing protect unsaved changes with warnings. A revision conflict leaves edits in the grid and requires an explicit reload rather than silently overwriting external changes.

## Configuration

`config.example.yaml` demonstrates the application format:

```yaml
repository_root: .
preferences: local/preferences.json
repositories:
  sample:
    name: Synthetic NextAct
    directory: examples/nextact
    store: nextact.csv
    schema: schema.yaml
    log: changes.csv
    scripts:
      - name: archive
        command: [python3, archive.py]
        description: Move completed (priority Z) rows into archive.csv
```

The repository root is resolved relative to the configuration file. Store, schema, log, and lookup paths must remain inside their configured repository directory. All repositories, stores, schemas, and lookups are validated at startup; invalid user data is not modified.

Schemas declare an ordered `columns` list. Field types are `date`, `datetime`, `dropdown`, `text`, and `note`. Dropdowns use either inline values or a lookup CSV:

```yaml
columns:
  - name: Priority
    type: dropdown
    lookup:
      values: [A, B, C, Z]
  - name: Tag
    type: dropdown
    lookup:
      file: tags.csv
      column: tag
  - name: Created
    type: datetime
    on_create: true
  - name: Updated
    type: datetime
    on_update: true
```

Adding, removing, renaming, or reordering columns requires only schema and corresponding CSV header changes. Values outside a dropdown lookup are preserved and displayed; validation does not police existing data.

## Scripts

Scripts are configured external commands listed per repository. The service runs them from the repository directory, supplies `CSVLIST_REPOSITORY_DIR`, `CSVLIST_STORE`, and `CSVLIST_LOG` environment variables, captures output and exit status, appends a `script_run` entry to the change log, and reloads and re-validates the store afterward. A non-zero exit, a launch failure, a timeout, or a store that no longer loads is reported as a visible failure, never as success. Scripts own their domain logic and must perform their own atomic data transformations; see `examples/nextact/archive.py` for a working example. The browser **Run script** control asks for confirmation, is disabled while unsaved changes are pending, and reloads the grid after a successful run.

The dependency-free YAML reader supports indentation-based mappings/lists, plain and quoted scalars, and flow lists/mappings. It intentionally rejects unsupported features such as block scalars with a source line number rather than guessing.

## HTTP API

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Service health |
| GET | `/api/repositories` | Repositories, selection, and modes |
| POST | `/api/repositories/select` | Persist the selected repository |
| GET | `/api/repository?repository=ID` | Load schema, lookups, rows, mode, view preferences, and revision |
| POST | `/api/preferences/mode` | Set `editable` or `read-only` mode |
| POST | `/api/preferences/view` | Set note visibility and per-column widths |
| POST | `/api/save` | Atomically apply changes and append rows |
| GET | `/api/log?repository=ID&limit=500` | Read the append-only change log |

A save supplies the loaded file revision, changed row indexes with only their changed values, and optional new rows:

```json
{
  "repository": "sample",
  "revision": "revision returned by GET /api/repository",
  "changes": [
    {"row": 0, "values": {"Next": "2027-01-15"}}
  ],
  "new_rows": [
    {"Priority": "B", "Label": "New synthetic item"}
  ]
}
```

A stale revision returns HTTP 409 without writing. A save in read-only mode returns HTTP 403. Sorting and filtering are view operations and are not part of save, so they cannot reorder the file or exclude hidden edits.

## Data safety and repository contents

Real data stores, personal configuration, credentials, preferences, and real change logs belong outside this source repository. `config.yaml`, `local/`, and `data/` are ignored. Only the invented records under `examples/` are committed.

Requirements and the implementation plan are in `docs/`.

## Tests

```sh
python3 -m unittest discover -s tests -v
node --test tests/js/*.test.mjs
```

Tests copy the dedicated synthetic fixture from `tests/fixtures/nextact` into temporary directories, so local edits to the runnable example do not affect test results. Python coverage includes byte-identical no-op round trips, exact field-level edits, embedded newlines, managed timestamps, appended rows, schema changes, read-only enforcement, external-edit conflicts, logging, view-preference validation/persistence, script success/failure/corruption handling, script-run log entries, static assets, and live localhost HTTP requests. JavaScript model tests cover stable sorting, exact and combined filters, blank/unknown filter values, file-order preservation, saving filtered-out edits, width limits, minimal save payloads, appended-row order, native editor fallback, note newline preservation, script result messages, and log entry formatting.

## License

MIT — see [`LICENSE`](LICENSE).
