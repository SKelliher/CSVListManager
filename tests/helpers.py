from __future__ import annotations

from pathlib import Path
import shutil


PROJECT = Path(__file__).resolve().parents[1]


def install_example(destination: Path) -> Path:
    shutil.copytree(PROJECT / "tests" / "fixtures" / "nextact", destination / "examples" / "nextact")
    config = destination / "config.yaml"
    config.write_text((PROJECT / "config.example.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    return config
