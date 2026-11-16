from __future__ import annotations

import unittest

from csvlistmanager.simpleyaml import loads, YAMLError


class SimpleYAMLTests(unittest.TestCase):
    def test_nested_configuration_and_flow_values(self):
        value = loads(
            """# application config
root: .
enabled: true
count: 3
empty: null
items:
  - name: first
    values: [A, B, 'C, D']
    options: {mode: read-only, url: https://example.com}
  - name: \"second # item\" # comment
"""
        )
        self.assertEqual(value["items"][0]["values"], ["A", "B", "C, D"])
        self.assertEqual(value["items"][0]["options"]["url"], "https://example.com")
        self.assertEqual(value["items"][1]["name"], "second # item")
        self.assertTrue(value["enabled"])
        self.assertEqual(value["count"], 3)
        self.assertIsNone(value["empty"])

    def test_duplicate_keys_fail(self):
        with self.assertRaisesRegex(YAMLError, "duplicate key"):
            loads("name: one\nname: two\n")

    def test_bad_indentation_fails(self):
        with self.assertRaisesRegex(YAMLError, "indentation"):
            loads("items:\n  - name: one\n   type: text\n")

    def test_block_scalars_fail_explicitly(self):
        with self.assertRaisesRegex(YAMLError, "Block scalar"):
            loads("description: |\n")


if __name__ == "__main__":
    unittest.main()
