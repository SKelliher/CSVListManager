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
  MAX_COLUMN_WIDTH,
  MIN_COLUMN_WIDTH,
  noteNewline,
  scriptResultMessage,
  sortedRows,
  toEditorValue,
} from "/model.js";

const elements = {
  repository: document.querySelector("#repository-select"),
  reload: document.querySelector("#reload-button"),
  mode: document.querySelector("#mode-button"),
  noteToggle: document.querySelector("#note-toggle"),
  add: document.querySelector("#add-row-button"),
  save: document.querySelector("#save-button"),
  scriptSelect: document.querySelector("#script-select"),
  runScript: document.querySelector("#run-script-button"),
  logButton: document.querySelector("#log-button"),
  logDialog: document.querySelector("#log-dialog"),
  logSummary: document.querySelector("#log-summary"),
  logBody: document.querySelector("#log-body"),
  logRefresh: document.querySelector("#log-refresh"),
  logClose: document.querySelector("#log-close"),
  modeIndicator: document.querySelector("#mode-indicator"),
  dirtyIndicator: document.querySelector("#dirty-indicator"),
  status: document.querySelector("#status-message"),
  filterCount: document.querySelector("#filter-count"),
  clearFilters: document.querySelector("#clear-filters"),
  workspace: document.querySelector(".workspace"),
  notePanel: document.querySelector("#note-panel"),
  grid: document.querySelector("#data-grid"),
  gridColumns: document.querySelector("#grid-columns"),
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
  filters: new Map(),
  noteVisible: true,
  columnWidths: {},
  selectedNote: null,
  selectedNoteNewline: "\n",
  newRowCounter: 0,
  scripts: [],
  busy: false,
  viewRequest: 0,
  viewSaveTimer: null,
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
  elements.noteToggle.disabled = state.busy || !hasRepository;
  elements.add.disabled = state.busy || !hasRepository || state.mode === "read-only";
  elements.save.disabled = state.busy || !hasRepository || !hasChanges || state.mode === "read-only";
  elements.mode.textContent = state.mode === "read-only" ? "Switch to editable" : "Switch to read-only";
  elements.noteToggle.textContent = state.noteVisible ? "Hide note editor" : "Show note editor";
  elements.noteToggle.setAttribute("aria-expanded", String(state.noteVisible));
  elements.modeIndicator.textContent = state.mode === "read-only" ? "Read-only" : "Editable";
  elements.modeIndicator.classList.toggle("read-only", state.mode === "read-only");
  elements.dirtyIndicator.hidden = !hasChanges;
  elements.clearFilters.disabled = state.busy || state.filters.size === 0;
  const hasScripts = hasRepository && state.scripts.length > 0;
  elements.scriptSelect.hidden = !hasScripts;
  elements.runScript.hidden = !hasScripts;
  elements.scriptSelect.disabled = state.busy || !hasScripts;
  elements.runScript.disabled = state.busy || !hasScripts || hasChanges;
  elements.runScript.title = hasChanges ? "Save or discard unsaved changes before running a script" : "";
  elements.logButton.disabled = state.busy || !hasRepository;
  document.title = `${hasChanges ? "* " : ""}CSVListManager`;
}

function renderScriptOptions() {
  elements.scriptSelect.replaceChildren();
  for (const script of state.scripts) {
    const option = document.createElement("option");
    option.value = script.name;
    option.textContent = script.description ? `${script.name} — ${script.description}` : script.name;
    option.title = script.description || script.name;
    elements.scriptSelect.append(option);
  }
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

function defaultColumnWidth(column) {
  if (column.type === "note") return 300;
  if (column.type === "datetime") return 180;
  if (column.type === "date" || column.type === "dropdown") return 155;
  return 230;
}

function columnWidth(column) {
  return state.columnWidths[column.name] || defaultColumnWidth(column);
}

function renderColumns() {
  const columns = [document.createElement("col")];
  columns[0].style.width = "60px";
  let total = 60;
  for (const column of state.columns) {
    const definition = document.createElement("col");
    const width = columnWidth(column);
    definition.style.width = `${width}px`;
    columns.push(definition);
    total += width;
  }
  elements.gridColumns.replaceChildren(...columns);
  elements.grid.style.width = `${total}px`;
  elements.grid.style.minWidth = "100%";
}

function persistView() {
  const repository = state.repositoryId;
  if (!repository) return Promise.resolve();
  const request = ++state.viewRequest;
  const payload = {
    repository,
    note_visible: state.noteVisible,
    column_widths: { ...state.columnWidths },
  };
  return api("/api/preferences/view", { method: "POST", body: JSON.stringify(payload) })
    .then((view) => {
      if (request === state.viewRequest && repository === state.repositoryId) {
        state.noteVisible = view.note_visible;
        state.columnWidths = { ...view.column_widths };
      }
    })
    .catch((error) => setStatus(`View preference could not be saved: ${error.message}`, true));
}

function persistViewSoon() {
  window.clearTimeout(state.viewSaveTimer);
  state.viewSaveTimer = window.setTimeout(() => void persistView(), 250);
}

function createResizer(column) {
  const handle = document.createElement("span");
  handle.className = "column-resizer";
  handle.setAttribute("role", "separator");
  handle.tabIndex = 0;
  handle.setAttribute("aria-label", `Resize ${column.name} column`);
  handle.setAttribute("aria-orientation", "vertical");
  handle.setAttribute("aria-valuemin", String(MIN_COLUMN_WIDTH));
  handle.setAttribute("aria-valuemax", String(MAX_COLUMN_WIDTH));
  handle.setAttribute("aria-valuenow", String(columnWidth(column)));

  function setWidth(width) {
    const next = clampColumnWidth(width);
    state.columnWidths = { ...state.columnWidths, [column.name]: next };
    handle.setAttribute("aria-valuenow", String(next));
    renderColumns();
  }

  handle.addEventListener("pointerdown", (event) => {
    if (state.busy || event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    const startX = event.clientX;
    const startWidth = columnWidth(column);
    handle.setPointerCapture(event.pointerId);
    handle.classList.add("dragging");

    function move(moveEvent) {
      setWidth(startWidth + moveEvent.clientX - startX);
    }
    function finish() {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", finish);
      handle.removeEventListener("pointercancel", finish);
      handle.classList.remove("dragging");
      void persistView();
    }
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", finish);
    handle.addEventListener("pointercancel", finish);
  });

  handle.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const step = event.shiftKey ? 50 : 10;
    setWidth(columnWidth(column) + (event.key === "ArrowRight" ? step : -step));
    persistViewSoon();
  });
  return handle;
}

function createFilter(column) {
  const select = document.createElement("select");
  select.className = "filter-select";
  select.dataset.filterColumn = column.name;
  select.setAttribute("aria-label", `Filter ${column.name}`);
  select.disabled = state.busy;
  appendOption(select, "all", "All values");
  const selected = state.filters.has(column.name) ? JSON.stringify(state.filters.get(column.name)) : "all";
  for (const value of filterValues(state.rows, column, state.lookups[column.name] || [])) {
    appendOption(select, JSON.stringify(value), value === "" ? "(Blank)" : value);
  }
  select.value = selected;
  select.addEventListener("change", () => {
    if (select.value === "all") state.filters.delete(column.name);
    else state.filters.set(column.name, JSON.parse(select.value));
    renderGrid();
    updateControls();
  });
  return select;
}

function renderHeader() {
  const row = document.createElement("tr");
  const filterRow = document.createElement("tr");
  filterRow.className = "filter-row";
  const number = document.createElement("th");
  number.className = "row-number";
  number.scope = "col";
  number.textContent = "#";
  row.append(number);
  const filterNumber = document.createElement("th");
  filterNumber.className = "row-number filter-heading";
  filterNumber.textContent = "Filter";
  filterRow.append(filterNumber);

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
    heading.append(createResizer(column));
    row.append(heading);

    const filterCell = document.createElement("th");
    filterCell.className = "filter-cell";
    if (column.type === "date" || column.type === "dropdown") {
      filterCell.append(createFilter(column));
    } else {
      filterCell.classList.add("filter-unavailable");
      filterCell.textContent = "—";
    }
    filterRow.append(filterCell);
  }
  elements.head.replaceChildren(row, filterRow);
}

function appendOption(select, value, label) {
  const option = document.createElement("option");
  option.value = value;
  option.textContent = label;
  select.append(option);
}

function refreshFilteredColumn(column) {
  if (state.filters.has(column.name)) {
    renderGrid();
    updateControls();
  }
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
  select.addEventListener("change", () => {
    updateCell(row, column, select.value, select);
    refreshFilteredColumn(column);
  });
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
  input.addEventListener("change", () => refreshFilteredColumn(column));
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

function updateFilterControls(visibleCount) {
  elements.filterCount.textContent = `Showing ${visibleCount} of ${state.rows.length} rows`;
  elements.clearFilters.disabled = state.busy || state.filters.size === 0;
}

function renderGrid() {
  renderColumns();
  renderHeader();
  elements.body.replaceChildren();
  if (!state.columns.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.className = "empty-row";
    cell.textContent = state.busy ? "Loading…" : "No repository loaded.";
    row.append(cell);
    elements.body.append(row);
    updateFilterControls(0);
    return;
  }

  const changed = new Map(collectChanges(state.rows, state.originalRows).map((change) => [change.row, change.values]));
  const matchingRows = filteredRows(state.rows, state.columns, state.filters);
  const visibleRows = sortedRows(matchingRows, state.columns, state.sort);
  updateFilterControls(matchingRows.length);
  if (!visibleRows.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.className = "empty-row";
    cell.colSpan = state.columns.length + 1;
    cell.textContent = state.rows.length
      ? "No rows match the active filters. Clear filters to see all records."
      : "This store has no records. Use Add row to create one.";
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

function renderWorkspace() {
  elements.notePanel.hidden = !state.noteVisible;
  elements.workspace.classList.toggle("note-hidden", !state.noteVisible);
}

function renderAll() {
  renderRepositoryOptions();
  renderWorkspace();
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
  state.viewRequest += 1;
  updateControls();
  setStatus("Loading repository…");
  try {
    const payload = await api(`/api/repository?repository=${encodeURIComponent(repositoryId)}`);
    const repositoryChanged = state.repositoryId !== payload.repository.id;
    state.repositoryId = payload.repository.id;
    state.mode = payload.mode;
    state.noteVisible = payload.view.note_visible;
    state.columnWidths = { ...payload.view.column_widths };
    state.revision = payload.revision;
    state.columns = payload.schema.columns;
    state.lookups = payload.lookups;
    state.scripts = payload.repository.scripts || [];
    renderScriptOptions();
    state.rows = payload.rows.map((row) => ({ key: row.index, index: row.index, values: { ...row.values }, isNew: false }));
    state.originalRows = payload.rows.map((row) => ({ index: row.index, values: { ...row.values } }));
    state.originals = new Map(state.originalRows.map((row) => [row.index, row]));
    if (repositoryChanged) {
      state.filters = new Map();
    } else {
      state.filters = new Map([...state.filters].filter(([name]) => {
        const column = state.columns.find((candidate) => candidate.name === name);
        return column && (column.type === "date" || column.type === "dropdown");
      }));
    }
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

function toggleNoteVisibility() {
  if (!state.repositoryId || state.busy) return;
  state.noteVisible = !state.noteVisible;
  renderWorkspace();
  updateControls();
  setStatus(state.noteVisible ? "Note editor shown." : "Note editor hidden; note cells remain available.");
  void persistView();
}

function clearFilters() {
  if (!state.filters.size || state.busy) return;
  state.filters.clear();
  renderGrid();
  updateControls();
  setStatus("Filters cleared.");
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

async function runSelectedScript() {
  const name = elements.scriptSelect.value;
  const repository = state.repositoryId;
  if (!repository || state.busy || !name || dirty()) return;
  const script = state.scripts.find((candidate) => candidate.name === name);
  const question = script?.description
    ? `Run script "${name}" (${script.description}) on ${repository}?`
    : `Run script "${name}" on ${repository}?`;
  if (!window.confirm(question)) return;
  state.busy = true;
  renderAll();
  setStatus(`Running script "${name}"…`);
  try {
    const result = await api("/api/scripts/run", {
      method: "POST",
      body: JSON.stringify({ repository, script: name }),
    });
    if (result.status === "success") {
      if (await loadRepository(repository)) setStatus(scriptResultMessage(result));
    } else {
      state.busy = false;
      renderAll();
      setStatus(scriptResultMessage(result), true);
      if (result.output) console.warn(`Script "${name}" output:\n${result.output}`);
    }
  } catch (error) {
    state.busy = false;
    renderAll();
    setStatus(error.message, true);
  }
}

function renderLogRows(rows) {
  elements.logBody.replaceChildren();
  elements.logSummary.textContent = rows.length
    ? `${rows.length} most recent entr${rows.length === 1 ? "y" : "ies"}, newest last.`
    : "No log entries yet.";
  for (const row of rows) {
    const tableRow = document.createElement("tr");
    const time = document.createElement("td");
    time.className = "log-time";
    time.textContent = row.timestamp.replace("T", " ").replace(/\+00:00$/, " UTC");
    const event = document.createElement("td");
    event.textContent = row.event;
    const details = document.createElement("td");
    details.className = "log-details";
    details.textContent = formatLogEntry(row);
    tableRow.append(time, event, details);
    elements.logBody.append(tableRow);
  }
}

async function refreshLog() {
  if (!state.repositoryId) return;
  elements.logRefresh.disabled = true;
  try {
    const payload = await api(`/api/log?repository=${encodeURIComponent(state.repositoryId)}`);
    renderLogRows(payload.rows);
  } catch (error) {
    elements.logSummary.textContent = error.message;
  } finally {
    elements.logRefresh.disabled = false;
  }
}

function openLog() {
  if (!state.repositoryId || state.busy) return;
  elements.logSummary.textContent = "Loading…";
  elements.logBody.replaceChildren();
  elements.logDialog.showModal();
  void refreshLog();
}

elements.repository.addEventListener("change", changeRepository);
elements.reload.addEventListener("click", reloadRepository);
elements.mode.addEventListener("click", toggleMode);
elements.noteToggle.addEventListener("click", toggleNoteVisibility);
elements.clearFilters.addEventListener("click", clearFilters);
elements.add.addEventListener("click", addRow);
elements.save.addEventListener("click", save);
elements.runScript.addEventListener("click", runSelectedScript);
elements.logButton.addEventListener("click", openLog);
elements.logRefresh.addEventListener("click", refreshLog);
elements.logClose.addEventListener("click", () => elements.logDialog.close());

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
