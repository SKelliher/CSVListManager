# Synthetic NextAct example

This repository-shaped directory contains only invented records. It demonstrates the NextAct column structure without connecting to or copying any live personal data.

- `nextact.csv` is the source-of-truth store.
- `schema.yaml` defines its columns and lookups.
- `nextact_tags.csv` is a human-editable lookup file.
- `changes.csv` starts with only the append-only log header; application operations add synthetic events.

The service reads and writes these files in place. Automated tests copy them to a temporary directory so the checked-in examples remain unchanged.
