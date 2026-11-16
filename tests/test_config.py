from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from csvlistmanager.app import Application
from csvlistmanager.config import load_config, load_schema
from csvlistmanager.errors import ValidationError

from tests.helpers import install_example, PROJECT


class ConfigurationTests(unittest.TestCase):
    def test_example_configuration_is_valid(self):
        config = load_config(PROJECT / "config.example.yaml")
        repository = config.repositories["sample"]
        schema = load_schema(repository)
        self.assertEqual(schema.names, ("Priority", "Next", "Last", "Tag", "Label", "Detail"))
        application = Application(config)
        loaded = application.load_repository("sample")
        self.assertEqual(len(loaded["lookups"]["Tag"]), 3)

    def test_header_and_schema_must_agree(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = install_example(root)
            store = root / "examples" / "nextact" / "nextact.csv"
            store.write_bytes(store.read_bytes().replace(b"Priority,", b"Wrong,", 1))
            with self.assertRaisesRegex(ValidationError, "does not match schema"):
                Application.from_config(config_path)

    def test_managed_flags_require_datetime(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = install_example(root)
            schema_path = root / "examples" / "nextact" / "schema.yaml"
            schema_path.write_text(
                schema_path.read_text(encoding="utf-8").replace("type: date", "type: date\n    on_create: true", 1),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValidationError, "require a datetime"):
                Application.from_config(config_path)

    def test_repository_files_cannot_escape_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = install_example(root)
            config_path.write_text(
                config_path.read_text(encoding="utf-8").replace("store: nextact.csv", "store: ../outside.csv"),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValidationError, "stay inside"):
                Application.from_config(config_path)


if __name__ == "__main__":
    unittest.main()
