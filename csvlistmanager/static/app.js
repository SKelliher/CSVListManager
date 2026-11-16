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
} from "/model.js";

const elements = {
  repository: document.querySelector("#repository-select"),
  reload: document.querySelector("#reload-button"),
  mode: document.querySelector("#mode-button"),
  add: document.querySelector("#add-row-button"),
  save: document.querySelector("#save-button"),
  modeIndicator: document.querySelector("#mode-indicator"),
  dirtyIndicator: document.querySelector("#dirty-indicator"),
  status: document.querySelector("#status-message"),
  head: document.querySelector("#grid-head"),
  body: document.querySelector("#grid-body"),
  noteLocation: document.querySelector("#note-location"),
  noteEditor: document.querySelector("#note-editor"),
  noteMode: document.querySelector("#note-mode"),
};

const state = {
  repositories: [],
  repositoryId: null,
  mode: "editable",
  revision: null,
  columns: [],
  lookups: {},
  rows: [],
  originalRows: [],
  originals: new Map(),
  sort: null,
  selectedNote: null,
  selectedNoteNewline: "\n",
  newRowCounter: 0,
  busy: false,
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: options.body ? { "Content-Type": "application/json" } : undefined,
  });
  const payload = await response.json();
  if (!response.ok) {
    const error = new Error(payload.error?.message || `Request failed (${response.status})`);
    error.code = payload.error?.code;
    error.status = response.status;
    throw error;
  }
  return payload;
}

function setStatus(message, isError = false) {
  elements.status.textContent = message;
  elements.status.classList.toggle("error", isError);
  elements.status.title = message;
}

function dirty() {
  return hasUnsavedChanges(state.rows, state.originalRows);
}

function findRow(key) {
  return state.rows.find((row) => String(row.key) === String(key));
}

function rowLabel(row) {
  return row.isNew ? "New row" : `Row ${row.index + 1}`;
}

function isCellChanged(row, columnName) {
  if (row.isNew) return true;
  return state.originals.get(row.index)?.values[columnName] !== row.values[columnName];
}

function updateControls() {
  const hasRepository = Boolean(state.repositoryId);
  const hasChanges = dirty();
  elements.repository.disabled = state.busy;
  elements.reload.disabled = state.busy || !hasRepository;
  elements.mode.disabled = state.busy || !hasRepository;
  elements.add.disabled = state.busy || !hasRepository || state.mode === "read-only";
  elements.save.disabled = state.busy || !hasRepository || !hasChanges || state.mode === "read-only";
  elements.mode.textContent = state.mode === "read-only" ? "Switch to editable" : "Switch to read-only";
  elements.modeIndicator.textContent = state.mode === "read-only" ? "Read-only" : "Editable";
  elements.modeIndicator.classList.toggle("read-only", state.mode === "read-only");
  elements.dirtyIndicator.hidden = !hasChanges;
  document.title = `${hasChanges ? "* " : ""}CSVListManager`;
}

function renderRepositoryOptions() {
  elements.repository.replaceChildren();
  for (const repository of state.repositories) {
    const option = document.createElement("option");
    option.value = repository.id;
    option.textContent = repository.name;
    elements.repository.append(option);
  }
  if (state.repositoryId) elements.repository.value = state.repositoryId;
}

function renderHeader() {
  const row = document.createElement("tr");
  const number = document.createElement("th");
  number.className = "row-number";
  number.scope = "col";
  number.textContent = "#";
  row.append(number);

  for (const column of state.columns) {
    const heading = document.createElement("th");
    heading.scope = "col";
    if (column.type === "note") {
      heading.className = "note-heading-cell";
      heading.textContent = column.name;
    } else {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "sort-button";
      button.disabled = state.busy;
      button.setAttribute("aria-label", `Sort by ${column.name}`);
      const label = document.createElement("span");
      label.textContent = column.name;
      const direction = document.createElement("span");
      direction.className = "sort-direction";
      if (state.sort?.name === column.name) {
        direction.textContent = state.sort.direction === "asc" ? "▲" : "▼";
        heading.setAttribute("aria-sort", state.sort.direction === "asc" ? "ascending" : "descending");
      }
      button.append(label, direction);
      button.addEventListener("click", () => {
        if (state.sort?.name === column.name && state.sort.direction === "asc") {
          state.sort = { name: column.name, direction: "desc" };
        } else if (state.sort?.name === column.name) {
          state.sort = null;
        } else {
          state.sort = { name: column.name, direction: "asc" };
        }
        renderGrid();
      });
      heading.append(button);
    }
    row.append(heading);
  }
  elements.head.replaceChildren(row);
}

function appendOption(select, value, label) {
  const option = document.createElement("option");
  option.value = value;
  option.textContent = label;
  select.append(option);
}

function createDropdown(row, column, disabled) {
  const select = document.createElement("select");
  select.className = "cell-select";
  select.dataset.rowKey = row.key;
  select.dataset.column = column.name;
  select.setAttribute("aria-label", `${column.name}, ${rowLabel(row)}`);
  select.disabled = disabled;
  appendOption(select, "", "");
  const entries = state.lookups[column.name] || [];
  const known = new Set(entries.map((entry) => entry.value));
  for (const entry of entries) {
    appendOption(select, entry.value, entry.description ? `${entry.value} — ${entry.description}` : entry.value);
  }
  const current = row.values[column.name];
  if (current && !known.has(current)) appendOption(select, current, `${current} (not in lookup)`);
  select.value = current;
  select.addEventListener("change", () => updateCell(row, column, select.value, select));
  return select;
}

function createInput(row, column, disabled) {
  const input = document.createElement("input");
  const current = row.values[column.name];
  input.type = editorKind(column, current);
  input.className = "cell-input";
  input.dataset.rowKey = row.key;
  input.dataset.column = column.name;
  input.setAttribute("aria-label", `${column.name}, ${rowLabel(row)}`);
  input.value = toEditorValue(column, current);
  input.disabled = disabled;
  input.spellcheck = column.type === "text";
  input.addEventListener("input", () => {
    updateCell(row, column, fromEditorValue(column, input.value), input);
  });
  return input;
}

function notePreview(value) {
  return value ? value.replace(/\s+/g, " ").trim() || "Whitespace only" : "Empty note";
}

function createNoteButton(row, column) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "note-cell";
  button.dataset.rowKey = row.key;
  button.dataset.column = column.name;
  const value = row.values[column.name];
  button.textContent = notePreview(value);
  button.classList.toggle("empty", !value);
  button.classList.toggle(
    "selected",
    state.selectedNote?.key === row.key && state.selectedNote?.column === column.name,
  );
  button.setAttribute("aria-label", `${column.name}, ${rowLabel(row)}: ${notePreview(value)}`);
  button.addEventListener("click", () => selectNote(row, column));
  return button;
}

function renderGrid() {
  renderHeader();
  elements.body.replaceChildren();
  if (!state.columns.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.className = "empty-row";
    cell.textContent = state.busy ? "Loading…" : "No repository loaded.";
    row.append(cell);
    elements.body.append(row);
    return;
  }

  const changed = new Map(collectChanges(state.rows, state.originalRows).map((change) => [change.row, change.values]));
  const visibleRows = sortedRows(state.rows, state.columns, state.sort);
  if (!visibleRows.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.className = "empty-row";
    cell.colSpan = state.columns.length + 1;
    cell.textContent = "This store has no records. Use Add row to create one.";
    row.append(cell);
    elements.body.append(row);
    return;
  }

  for (const record of visibleRows) {
    const tableRow = document.createElement("tr");
    tableRow.classList.toggle("new-row", record.isNew);
    const number = document.createElement("th");
    number.className = "row-number";
    number.scope = "row";
    number.textContent = record.isNew ? "New" : String(record.index + 1);
    tableRow.append(number);

    for (const column of state.columns) {
      const cell = document.createElement("td");
      const changedCell = record.isNew || Boolean(changed.get(record.index)?.[column.name] !== undefined);
      let editor;
      if (column.type === "note") {
        editor = createNoteButton(record, column);
      } else {
        const managed = column.on_create || column.on_update;
        const disabled = state.busy || state.mode === "read-only" || managed;
        editor = column.type === "dropdown"
          ? createDropdown(record, column, disabled)
          : createInput(record, column, disabled);
        if (managed) editor.title = "Managed automatically by CSVListManager";
      }
      editor.classList.toggle("changed", changedCell);
      cell.append(editor);
      tableRow.append(cell);
    }
    elements.body.append(tableRow);
  }
}

function selectNote(row, column) {
  state.selectedNote = { key: row.key, column: column.name };
  state.selectedNoteNewline = noteNewline(row.values[column.name]);
  renderGrid();
  renderNote();
}

function renderNote() {
  const selected = state.selectedNote;
  const row = selected ? findRow(selected.key) : null;
  if (!row) {
    elements.noteLocation.textContent = "Select a note cell to view its full contents.";
    elements.noteEditor.value = "";
    elements.noteEditor.disabled = true;
    elements.noteEditor.readOnly = false;
    elements.noteMode.textContent = "";
    return;
  }
  const value = row.values[selected.column];
  elements.noteLocation.textContent = `${rowLabel(row)} · ${selected.column}`;
  elements.noteEditor.value = value;
  elements.noteEditor.disabled = false;
  elements.noteEditor.readOnly = state.busy || state.mode === "read-only";
  elements.noteEditor.setAttribute("aria-label", `${selected.column}, ${rowLabel(row)}`);
  elements.noteMode.textContent = state.mode === "read-only" ? "Read-only" : "";
}

function renderAll() {
  renderRepositoryOptions();
  renderGrid();
  renderNote();
  updateControls();
}

function updateCell(row, column, value, editor) {
  row.values[column.name] = value;
  editor.classList.toggle("changed", isCellChanged(row, column.name));
  updateControls();
  setStatus("Changes are in memory until you save.");
}

async function loadRepository(repositoryId) {
  state.busy = true;
  updateControls();
  setStatus("Loading repository…");
  try {
    const payload = await api(`/api/repository?repository=${encodeURIComponent(repositoryId)}`);
    state.repositoryId = payload.repository.id;
    state.mode = payload.mode;
    state.revision = payload.revision;
    state.columns = payload.schema.columns;
    state.lookups = payload.lookups;
    state.rows = payload.rows.map((row) => ({ key: row.index, index: row.index, values: { ...row.values }, isNew: false }));
    state.originalRows = payload.rows.map((row) => ({ index: row.index, values: { ...row.values } }));
    state.originals = new Map(state.originalRows.map((row) => [row.index, row]));
    state.selectedNote = null;
    state.busy = false;
    renderAll();
    setStatus(`Loaded ${state.rows.length} rows from ${payload.repository.name}.`);
    return true;
  } catch (error) {
    state.busy = false;
    renderAll();
    setStatus(error.message, true);
    return false;
  }
}

async function loadRepositories() {
  state.busy = true;
  updateControls();
  try {
    const payload = await api("/api/repositories");
    state.repositories = payload.repositories;
    state.repositoryId = payload.selected_repository;
    renderRepositoryOptions();
    await loadRepository(state.repositoryId);
  } catch (error) {
    state.busy = false;
    renderAll();
    setStatus(error.message, true);
  }
}

async function changeRepository() {
  const selected = elements.repository.value;
  if (!selected || selected === state.repositoryId) return;
  if (dirty() && !window.confirm("Discard unsaved changes and switch repositories?")) {
    elements.repository.value = state.repositoryId;
    return;
  }
  try {
    await api("/api/repositories/select", {
      method: "POST",
      body: JSON.stringify({ repository: selected }),
    });
    await loadRepository(selected);
  } catch (error) {
    elements.repository.value = state.repositoryId;
    setStatus(error.message, true);
  }
}

async function reloadRepository() {
  if (!state.repositoryId || state.busy) return;
  if (dirty() && !window.confirm("Discard unsaved changes and reload the CSV from disk?")) return;
  await loadRepository(state.repositoryId);
}

async function toggleMode() {
  if (!state.repositoryId || state.busy) return;
  const mode = state.mode === "read-only" ? "editable" : "read-only";
  state.busy = true;
  updateControls();
  try {
    await api("/api/preferences/mode", {
      method: "POST",
      body: JSON.stringify({ repository: state.repositoryId, mode }),
    });
    state.mode = mode;
    state.busy = false;
    renderAll();
    setStatus(mode === "read-only" ? "Read-only mode: editing and saving are disabled." : "Editable mode enabled.");
  } catch (error) {
    state.busy = false;
    renderAll();
    setStatus(error.message, true);
  }
}

function addRow() {
  if (!state.repositoryId || state.busy || state.mode === "read-only") return;
  const key = `new-${++state.newRowCounter}`;
  const values = Object.fromEntries(state.columns.map((column) => [column.name, ""]));
  state.rows.push({ key, index: null, values, isNew: true });
  renderAll();
  setStatus("New row added in memory. Save to append it to the CSV.");
  requestAnimationFrame(() => {
    document.querySelector(`[data-row-key="${key}"]:not(.note-cell)`)?.focus();
  });
}

async function save() {
  if (!state.repositoryId || state.busy || state.mode === "read-only" || !dirty()) return;
  const repository = state.repositoryId;
  const payload = buildSavePayload(repository, state.revision, state.rows, state.originalRows);
  state.busy = true;
  renderAll();
  setStatus("Saving…");
  try {
    const result = await api("/api/save", { method: "POST", body: JSON.stringify(payload) });
    const message = `Saved ${result.edits} edit${result.edits === 1 ? "" : "s"} and ${result.additions} new row${result.additions === 1 ? "" : "s"}.`;
    if (await loadRepository(repository)) setStatus(message);
  } catch (error) {
    state.busy = false;
    renderAll();
    if (error.code === "revision_conflict") {
      setStatus(`${error.message} Your unsaved changes are still in the grid.`, true);
    } else {
      setStatus(error.message, true);
    }
  }
}

elements.repository.addEventListener("change", changeRepository);
elements.reload.addEventListener("click", reloadRepository);
elements.mode.addEventListener("click", toggleMode);
elements.add.addEventListener("click", addRow);
elements.save.addEventListener("click", save);

elements.noteEditor.addEventListener("input", () => {
  const selected = state.selectedNote;
  const row = selected ? findRow(selected.key) : null;
  if (!row || state.mode === "read-only" || state.busy) return;
  const value = fromTextareaValue(elements.noteEditor.value, state.selectedNoteNewline);
  row.values[selected.column] = value;
  const preview = [...document.querySelectorAll(".note-cell")].find(
    (button) => button.dataset.rowKey === String(row.key) && button.dataset.column === selected.column,
  );
  if (preview) {
    preview.textContent = notePreview(value);
    preview.classList.toggle("empty", !value);
    preview.classList.toggle("changed", isCellChanged(row, selected.column));
  }
  updateControls();
  setStatus("Changes are in memory until you save.");
});

document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
    event.preventDefault();
    void save();
  }
});

window.addEventListener("beforeunload", (event) => {
  if (!dirty()) return;
  event.preventDefault();
  event.returnValue = "";
});

void loadRepositories();
