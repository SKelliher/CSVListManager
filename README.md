# CSVListManager

CSVListManager is a configurable, local grid for editing plain RFC 4180 CSV data stores. A Python standard-library service will provide safe file access, while an HTML/vanilla-JavaScript interface will provide typed editing, stable view-only sorting, lookup-backed dropdowns, multi-line notes, external scripts, and an append-only change log.

The CSV file remains the source of truth. The application requires no network access at runtime and uses no database, cloud account, or data synchronization service.

## Project status

Initial repository setup. Implementation will follow the approved plan in [`docs/CSVListManager_implementation_plan.md`](docs/CSVListManager_implementation_plan.md), with the generic requirements in [`docs/nextact_grid_requirements.md`](docs/nextact_grid_requirements.md).

## Repository layout

- `docs/` — requirements and implementation plan snapshots.
- Source, tests, and synthetic sample data will be added during implementation.

Real data stores, personal configuration, credentials, and real change logs must remain outside this code repository.

## Development requirements

- Python 3.11 or later (standard library only for the service)
- A modern browser for the grid interface

Installation and usage instructions will be added with the runnable application.

## License

MIT — see [`LICENSE`](LICENSE).
