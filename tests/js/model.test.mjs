import test from "node:test";
import assert from "node:assert/strict";

import {
  buildSavePayload,
  clampColumnWidth,
  collectChanges,
  editorKind,
  filteredRows,
  filterValues,
  formatLogEntry,
  fromEditorValue,
  fromTextareaValue,
  hasUnsavedChanges,
  noteNewline,
  scriptResultMessage,
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

test("exact filters support dates, blank values, unknown dropdowns, and AND composition", () => {
  const filterColumns = [
    { name: "Priority", type: "dropdown" },
    { name: "Next", type: "date" },
    { name: "Label", type: "text" },
  ];
  const rows = [
    { index: 0, values: { Priority: "A", Next: "2026-11-16", Label: "One" } },
    { index: 1, values: { Priority: "Q", Next: "", Label: "Two" } },
    { index: 2, values: { Priority: "B", Next: "", Label: "Three" } },
  ];
  assert.deepEqual(filteredRows(rows, filterColumns, new Map([["Next", ""]])).map((row) => row.index), [1, 2]);
  assert.deepEqual(filteredRows(rows, filterColumns, new Map([["Priority", "Q"]])).map((row) => row.index), [1]);
  assert.deepEqual(
    filteredRows(rows, filterColumns, new Map([["Priority", "B"], ["Next", ""]])).map((row) => row.index),
    [2],
  );
});

test("filter values include blank, lookups, and unknown actual values", () => {
  const rows = [
    { values: { Priority: "Q" } },
    { values: { Priority: "A" } },
    { values: { Priority: "" } },
  ];
  const column = { name: "Priority", type: "dropdown" };
  const values = filterValues(rows, column, [{ value: "Z" }, { value: "A" }]);
  assert.deepEqual(values, ["", "A", "Q", "Z"]);
});

test("filtering hides rows without removing their unsaved edits from save", () => {
  const filterColumns = [{ name: "Priority", type: "dropdown" }, { name: "Label", type: "text" }];
  const original = [
    { index: 0, values: { Priority: "A", Label: "Original" } },
    { index: 1, values: { Priority: "B", Label: "Visible" } },
  ];
  const rows = [
    { index: 0, values: { Priority: "A", Label: "Hidden edit" } },
    { index: 1, values: { Priority: "B", Label: "Visible" } },
  ];
  const visible = filteredRows(rows, filterColumns, new Map([["Priority", "B"]]));
  assert.deepEqual(visible.map((row) => row.index), [1]);
  const payload = buildSavePayload("sample", "revision", rows, original);
  assert.deepEqual(payload.changes, [{ row: 0, values: { Label: "Hidden edit" } }]);
});

test("column widths are clamped to accessible limits", () => {
  assert.equal(clampColumnWidth(20), 80);
  assert.equal(clampColumnWidth(125.6), 126);
  assert.equal(clampColumnWidth(900), 600);
});

test("textarea edits retain the selected note's original newline convention", () => {
  const original = "first\r\nsecond";
  const newline = noteNewline(original);
  assert.equal(newline, "\r\n");
  assert.equal(fromTextareaValue("first\nsecond\nthird", newline), "first\r\nsecond\r\nthird");
});

test("script result messages prefer the first output line on success", () => {
  assert.equal(
    scriptResultMessage({ script: "archive", status: "success", output: "\nArchived 1 row; 3 remain.\n" }),
    'Script "archive" finished: Archived 1 row; 3 remain.',
  );
  assert.equal(
    scriptResultMessage({ script: "archive", status: "success", output: "" }),
    'Script "archive" completed successfully.',
  );
});

test("script failure messages include the detail", () => {
  assert.equal(
    scriptResultMessage({ script: "archive", status: "failed", detail: "Exited with status 3" }),
    'Script "archive" failed: Exited with status 3',
  );
});

test("log entries format edits, saves, and script runs", () => {
  assert.equal(
    formatLogEntry({ event: "cell_edit", details: '{"row":2,"column":"Next","old":"","new":"2026-11-16"}' }),
    'Row 3: Next changed from "" to "2026-11-16"',
  );
  assert.equal(
    formatLogEntry({ event: "save", details: '{"edit_count":2,"addition_count":1}' }),
    "Saved 2 edit(s) and 1 new row(s)",
  );
  assert.equal(
    formatLogEntry({ event: "script_run", details: '{"script":"archive","status":"success","exit_code":0}' }),
    'Script "archive" success (exit 0)',
  );
  assert.equal(
    formatLogEntry({ event: "script_run", details: '{"script":"archive","status":"failed","exit_code":3,"detail":"Exited with status 3"}' }),
    'Script "archive" failed (exit 3): Exited with status 3',
  );
});

test("log entries survive invalid JSON details", () => {
  assert.equal(formatLogEntry({ event: "cell_edit", details: "not json" }), "not json");
  assert.equal(formatLogEntry({ event: "mystery", details: "raw text" }), "raw text");
});
