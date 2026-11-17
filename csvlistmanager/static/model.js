export function collectChanges(rows, originalRows) {
  const originals = new Map(originalRows.map((row) => [row.index, row]));
  const changes = [];
  for (const row of rows) {
    if (row.isNew || row.isDeleted) continue;
    const original = originals.get(row.index);
    if (!original) throw new Error(`No original row for index ${row.index}`);
    const values = {};
    for (const [name, value] of Object.entries(row.values)) {
      if (value !== original.values[name]) values[name] = value;
    }
    if (Object.keys(values).length) changes.push({ row: row.index, values });
  }
  return changes;
}

export function collectNewRows(rows) {
  return rows.filter((row) => row.isNew).map((row) => ({ ...row.values }));
}

export function collectDeletions(rows) {
  return rows.filter((row) => row.isDeleted && !row.isNew).map((row) => row.index);
}

export function hasUnsavedChanges(rows, originalRows) {
  return (
    collectNewRows(rows).length > 0
    || collectDeletions(rows).length > 0
    || collectChanges(rows, originalRows).length > 0
  );
}

export function buildSavePayload(repository, revision, rows, originalRows) {
  return {
    repository,
    revision,
    changes: collectChanges(rows, originalRows),
    new_rows: collectNewRows(rows),
    deletions: collectDeletions(rows),
  };
}

export function sortedRows(rows, columns, sort) {
  const copy = [...rows];
  if (!sort) return copy;
  const column = columns.find((candidate) => candidate.name === sort.name);
  if (!column || column.type === "note") return copy;
  const positions = new Map(rows.map((row, index) => [row, index]));
  const direction = sort.direction === "desc" ? -1 : 1;
  copy.sort((left, right) => {
    const a = left.values[column.name] ?? "";
    const b = right.values[column.name] ?? "";
    if (a === "" || b === "") {
      if (a === b) return positions.get(left) - positions.get(right);
      return a === "" ? 1 : -1;
    }
    let comparison;
    if (column.type === "date" || column.type === "datetime") {
      comparison = a < b ? -1 : a > b ? 1 : 0;
    } else {
      comparison = a.localeCompare(b);
    }
    return comparison * direction || positions.get(left) - positions.get(right);
  });
  return copy;
}

export const MIN_COLUMN_WIDTH = 80;
export const MAX_COLUMN_WIDTH = 600;

export function clampColumnWidth(width) {
  return Math.min(MAX_COLUMN_WIDTH, Math.max(MIN_COLUMN_WIDTH, Math.round(width)));
}

export function filteredRows(rows, columns, filters) {
  const active = [...filters].filter(([name]) => {
    const column = columns.find((candidate) => candidate.name === name);
    return column && (column.type === "date" || column.type === "dropdown");
  });
  if (!active.length) return [...rows];
  return rows.filter((row) => active.every(([name, value]) => (row.values[name] ?? "") === value));
}

export function filterValues(rows, column, lookupEntries = []) {
  const values = new Set([""]);
  if (column.type === "dropdown") {
    for (const entry of lookupEntries) values.add(entry.value);
  }
  for (const row of rows) values.add(row.values[column.name] ?? "");
  const nonEmpty = [...values].filter((value) => value !== "");
  nonEmpty.sort((left, right) => column.type === "date"
    ? left < right ? -1 : left > right ? 1 : 0
    : left.localeCompare(right));
  return ["", ...nonEmpty];
}

export function isISODate(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return false;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day;
}

export function isISODateTime(value) {
  const match = /^(\d{4}-\d{2}-\d{2}) (\d{2}):(\d{2})$/.exec(value);
  return Boolean(
    match && isISODate(match[1]) && Number(match[2]) >= 0 && Number(match[2]) <= 23
      && Number(match[3]) >= 0 && Number(match[3]) <= 59
  );
}

export function editorKind(column, value) {
  if (column.type === "date") return value === "" || isISODate(value) ? "date" : "text";
  if (column.type === "datetime") return value === "" || isISODateTime(value) ? "datetime-local" : "text";
  return "text";
}

export function toEditorValue(column, value) {
  return column.type === "datetime" && editorKind(column, value) === "datetime-local"
    ? value.replace(" ", "T")
    : value;
}

export function fromEditorValue(column, value) {
  return column.type === "datetime" && value.includes("T") ? value.replace("T", " ") : value;
}

export function noteNewline(value) {
  if (value.includes("\r\n")) return "\r\n";
  if (value.includes("\r")) return "\r";
  return "\n";
}

export function fromTextareaValue(value, newline) {
  return value.replace(/\r\n|\r|\n/g, newline);
}

export function scriptResultMessage(result) {
  const name = result.script || "script";
  if (result.status === "success") {
    const firstLine = (result.output || "").split(/\r\n|\r|\n/).find((line) => line.trim());
    return firstLine ? `Script "${name}" finished: ${firstLine}` : `Script "${name}" completed successfully.`;
  }
  const detail = result.detail || "unknown error";
  return `Script "${name}" failed: ${detail}`;
}

export function parseLogDetails(row) {
  try {
    const parsed = JSON.parse(row.details || "{}");
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}

export function formatLogEntry(row) {
  const details = parseLogDetails(row);
  if (details === null) return row.details || "";
  switch (row.event) {
    case "cell_edit":
      return `Row ${(details.row ?? 0) + 1}: ${details.column} changed from "${details.old ?? ""}" to "${details.new ?? ""}"`;
    case "row_add":
      return `Row ${(details.row ?? 0) + 1} added`;
    case "row_delete":
      return `Row ${(details.row ?? 0) + 1} deleted`;
    case "save":
      return `Saved ${details.edit_count ?? 0} edit(s), ${details.addition_count ?? 0} new row(s), ${details.deletion_count ?? 0} deletion(s)`;
    case "script_run": {
      const base = `Script "${details.script ?? "?"}" ${details.status ?? "unknown"}`;
      const code = details.exit_code === null || details.exit_code === undefined ? "" : ` (exit ${details.exit_code})`;
      return details.detail ? `${base}${code}: ${details.detail}` : `${base}${code}`;
    }
    default:
      return row.details || "";
  }
}
