# CSVListManager

CSVListManager is a configurable, local grid for editing plain RFC 4180 CSV data stores. The CSV remains the source of truth: there is no database, shadow index, cloud account, or runtime network dependency.

This repository contains a Python standard-library service and will gain an HTML/vanilla-JavaScript grid in the next implementation phase. The service provides typed schemas, human-editable lookup files, safe explicit saves, repository preferences, and an append-only CSV change log.

## Implemented in this phase

- YAML application configuration and schema validation with actionable errors.
- Multiple named data repositories and per-repository editable/read-only modes.
- RFC 4180 parsing through Python's `csv` module, including quoted commas, quotes, empty values, and embedded newlines.
- Field-level save patches that leave all untouched bytes, quoting, record order, and line endings unchanged.
- Atomic temporary-file-and-replace saves and revision checks that prevent overwriting external edits.
- New-row appends and optional `on_create`/`on_update` datetime columns.
- Append-only cell-edit, row-addition, and save log events.
- A localhost-only JSON HTTP API.
- A completely synthetic NextAct example and automated unit/HTTP integration tests.

The browser grid and external script runner are not implemented yet. The live personal NextAct store is not connected by any shipped configuration.

## Requirements

- Python 3.11 or later
- No runtime packages outside the Python standard library

## Run against the synthetic example

From a source checkout:

```sh
python3 -m csvlistmanager --config config.example.yaml --check
python3 -m csvlistmanager --config config.example.yaml
```

The service listens on `127.0.0.1:8765`. `--port 0` selects an available port. Non-loopback bind addresses are rejected.

The checked-in example can be edited through the API, so its files will become modified after saves. To keep the checkout pristine, copy `examples/nextact` and `config.example.yaml` to a local directory and adjust the paths in the copied configuration. The ignored `local/` directory is suitable for experiments.

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
    scripts: []
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

The dependency-free YAML reader supports indentation-based mappings/lists, plain and quoted scalars, and flow lists/mappings. It intentionally rejects unsupported features such as block scalars with a source line number rather than guessing.

## HTTP API

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Service health |
| GET | `/api/repositories` | Repositories, selection, and modes |
| POST | `/api/repositories/select` | Persist the selected repository |
| GET | `/api/repository?repository=ID` | Load schema, lookups, rows, mode, and revision |
| POST | `/api/preferences/mode` | Set `editable` or `read-only` mode |
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

A stale revision returns HTTP 409 without writing. A save in read-only mode returns HTTP 403. Sorting is a future view operation and is not part of save, so it cannot reorder the file.

## Data safety and repository contents

Real data stores, personal configuration, credentials, preferences, and real change logs belong outside this source repository. `config.yaml`, `local/`, and `data/` are ignored. Only the invented records under `examples/` are committed.

Requirements and the implementation plan are in `docs/`.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

Tests copy the synthetic repository into temporary directories. Coverage includes byte-identical no-op round trips, exact field-level edits, embedded newlines, managed timestamps, appended rows, schema changes, read-only enforcement, external-edit conflicts, logging, and live localhost HTTP requests.

## License

MIT — see [`LICENSE`](LICENSE).
