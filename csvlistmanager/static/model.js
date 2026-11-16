export function collectChanges(rows, originalRows) {
  const originals = new Map(originalRows.map((row) => [row.index, row]));
  const changes = [];
  for (const row of rows) {
    if (row.isNew) continue;
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

export function hasUnsavedChanges(rows, originalRows) {
  return collectNewRows(rows).length > 0 || collectChanges(rows, originalRows).length > 0;
}

export function buildSavePayload(repository, revision, rows, originalRows) {
  return {
    repository,
    revision,
    changes: collectChanges(rows, originalRows),
    new_rows: collectNewRows(rows),
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
