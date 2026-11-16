import test from "node:test";
import assert from "node:assert/strict";

import {
  buildSavePayload,
  collectChanges,
  editorKind,
  fromEditorValue,
  fromTextareaValue,
  hasUnsavedChanges,
  noteNewline,
  sortedRows,
  toEditorValue,
} from "../../csvlistmanager/static/model.js";

const columns = [
  { name: "Label", type: "text" },
  { name: "Next", type: "date" },
  { name: "Detail", type: "note" },
];

function row(index, label, next = "", detail = "") {
  return { key: index, index, values: { Label: label, Next: next, Detail: detail }, isNew: false };
}

test("save payload contains only changed fields", () => {
  const original = [row(0, "Alpha", "2026-01-01"), row(1, "Beta")];
  const rows = [row(0, "Changed", "2026-01-01"), row(1, "Beta")];
  assert.deepEqual(collectChanges(rows, original), [{ row: 0, values: { Label: "Changed" } }]);
  assert.equal(hasUnsavedChanges(rows, original), true);
  rows[0].values.Label = "Alpha";
  assert.equal(hasUnsavedChanges(rows, original), false);
});

test("new rows retain file order and append after existing changes", () => {
  const original = [row(0, "Alpha")];
  const rows = [
    row(0, "Changed"),
    { key: "new-1", index: null, values: { Label: "First new", Next: "", Detail: "" }, isNew: true },
    { key: "new-2", index: null, values: { Label: "Second new", Next: "", Detail: "" }, isNew: true },
  ];
  const payload = buildSavePayload("sample", "revision", rows, original);
  assert.deepEqual(payload, {
    repository: "sample",
    revision: "revision",
    changes: [{ row: 0, values: { Label: "Changed" } }],
    new_rows: [
      { Label: "First new", Next: "", Detail: "" },
      { Label: "Second new", Next: "", Detail: "" },
    ],
  });
});

test("stable sorting never mutates file row order", () => {
  const rows = [row(0, "Same"), row(1, "Alpha"), row(2, "Same"), row(3, "")];
  const sorted = sortedRows(rows, columns, { name: "Label", direction: "asc" });
  assert.deepEqual(sorted.map((item) => item.index), [1, 0, 2, 3]);
  assert.deepEqual(rows.map((item) => item.index), [0, 1, 2, 3]);
  const descending = sortedRows(rows, columns, { name: "Label", direction: "desc" });
  assert.deepEqual(descending.map((item) => item.index), [0, 2, 1, 3]);
});

test("dates sort chronologically and note columns are not sortable", () => {
  const rows = [row(0, "A", "2027-01-01", "z"), row(1, "B", "2026-01-01", "a")];
  assert.deepEqual(
    sortedRows(rows, columns, { name: "Next", direction: "asc" }).map((item) => item.index),
    [1, 0],
  );
  assert.deepEqual(
    sortedRows(rows, columns, { name: "Detail", direction: "asc" }).map((item) => item.index),
    [0, 1],
  );
});

test("invalid stored dates use text editors without rewriting values", () => {
  const date = { name: "Next", type: "date" };
  const datetime = { name: "Updated", type: "datetime" };
  assert.equal(editorKind(date, "2026-02-29"), "text");
  assert.equal(editorKind(date, "2028-02-29"), "date");
  assert.equal(editorKind(datetime, "2026-11-16 14:30"), "datetime-local");
  assert.equal(toEditorValue(datetime, "2026-11-16 14:30"), "2026-11-16T14:30");
  assert.equal(fromEditorValue(datetime, "2026-11-16T14:30"), "2026-11-16 14:30");
});

test("textarea edits retain the selected note's original newline convention", () => {
  const original = "first\r\nsecond";
  const newline = noteNewline(original);
  assert.equal(newline, "\r\n");
  assert.equal(fromTextareaValue("first\nsecond\nthird", newline), "first\r\nsecond\r\nthird");
});
