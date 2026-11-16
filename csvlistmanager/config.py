"""Configuration, schema, and lookup loading with actionable validation."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ValidationError
from .simpleyaml import YAMLError, loads


FIELD_TYPES = {"date", "datetime", "dropdown", "text", "note"}
MODES = {"editable", "read-only"}


def _mapping(value: Any, description: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError(f"{description} must be a mapping")
    return value


def _string(value: Any, description: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{description} must be a non-empty string")
    return value.strip()


def _keys(value: dict[str, Any], allowed: set[str], description: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValidationError(f"Unknown {description} key(s): {', '.join(unknown)}")


def _yaml(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ValidationError(f"Cannot read {path}: {error.strerror or error}") from error
    try:
        return loads(text)
    except YAMLError as error:
        raise ValidationError(f"Invalid YAML in {path}: {error}") from error


def _child_path(base: Path, value: Any, description: str) -> Path:
    raw = _string(value, description)
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def _inside(path: Path, directory: Path, description: str) -> Path:
    if not path.is_relative_to(directory):
        raise ValidationError(f"{description} must stay inside its repository directory")
    return path


@dataclass(frozen=True)
class Lookup:
    values: tuple[str, ...] | None = None
    file: Path | None = None
    column: str | None = None

    def to_dict(self) -> dict[str, Any]:
        if self.values is not None:
            return {"values": list(self.values)}
        return {"file": self.file.name if self.file else None, "column": self.column}


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    lookup: Lookup | None = None
    on_create: bool = False
    on_update: bool = False

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"name": self.name, "type": self.type}
        if self.lookup:
            result["lookup"] = self.lookup.to_dict()
        if self.on_create:
            result["on_create"] = True
        if self.on_update:
            result["on_update"] = True
        return result


@dataclass(frozen=True)
class Schema:
    columns: tuple[Column, ...]

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns)

    def to_dict(self) -> dict[str, Any]:
        return {"columns": [column.to_dict() for column in self.columns]}


@dataclass(frozen=True)
class Script:
    name: str
    command: tuple[str, ...]
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description}


@dataclass(frozen=True)
class Repository:
    id: str
    name: str
    directory: Path
    store: Path
    schema: Path
    log: Path
    scripts: tuple[Script, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "scripts": [script.to_dict() for script in self.scripts],
        }


@dataclass(frozen=True)
class AppConfig:
    root: Path
    preferences: Path
    repositories: dict[str, Repository]


def _lookup(raw: Any, directory: Path, column_name: str) -> Lookup | None:
    if raw is None:
        return None
    if isinstance(raw, list):
        return Lookup(values=tuple(_string(item, f"Lookup value for {column_name}") for item in raw))
    value = _mapping(raw, f"Lookup for {column_name}")
    _keys(value, {"values", "file", "column"}, f"lookup for {column_name}")
    if ("values" in value) == ("file" in value):
        raise ValidationError(f"Lookup for {column_name} must define exactly one of values or file")
    if "values" in value:
        if not isinstance(value["values"], list):
            raise ValidationError(f"Lookup values for {column_name} must be a list")
        return Lookup(values=tuple(_string(item, f"Lookup value for {column_name}") for item in value["values"]))
    path = _inside(
        _child_path(directory, value["file"], f"Lookup file for {column_name}"),
        directory,
        f"Lookup file for {column_name}",
    )
    column = _string(value.get("column", "value"), f"Lookup column for {column_name}")
    return Lookup(file=path, column=column)


def load_schema(repository: Repository) -> Schema:
    raw = _mapping(_yaml(repository.schema), f"Schema {repository.schema}")
    _keys(raw, {"columns"}, "schema")
    columns_raw = raw.get("columns")
    if not isinstance(columns_raw, list) or not columns_raw:
        raise ValidationError(f"Schema {repository.schema} must contain a non-empty columns list")
    columns: list[Column] = []
    seen: set[str] = set()
    for index, item in enumerate(columns_raw, 1):
        value = _mapping(item, f"Schema column {index}")
        _keys(value, {"name", "type", "lookup", "on_create", "on_update"}, f"schema column {index}")
        name = _string(value.get("name"), f"Schema column {index} name")
        if name in seen:
            raise ValidationError(f"Duplicate schema column {name!r}")
        seen.add(name)
        field_type = _string(value.get("type"), f"Type for {name}")
        if field_type not in FIELD_TYPES:
            raise ValidationError(f"Column {name} has invalid type {field_type!r}; choose from {', '.join(sorted(FIELD_TYPES))}")
        lookup = _lookup(value.get("lookup"), repository.directory, name)
        if field_type == "dropdown" and lookup is None:
            raise ValidationError(f"Dropdown column {name} requires a lookup")
        if field_type != "dropdown" and lookup is not None:
            raise ValidationError(f"Only dropdown columns may define a lookup ({name})")
        on_create = value.get("on_create", False)
        on_update = value.get("on_update", False)
        if not isinstance(on_create, bool) or not isinstance(on_update, bool):
            raise ValidationError(f"Managed flags for {name} must be true or false")
        if (on_create or on_update) and field_type != "datetime":
            raise ValidationError(f"Managed flags require a datetime column ({name})")
        if on_create and on_update:
            raise ValidationError(f"Column {name} cannot have both on_create and on_update")
        columns.append(Column(name, field_type, lookup, on_create, on_update))
    return Schema(tuple(columns))


def read_lookup(column: Column) -> list[dict[str, str]]:
    lookup = column.lookup
    if lookup is None:
        return []
    if lookup.values is not None:
        return [{"value": value, "description": "", "parent": ""} for value in lookup.values]
    try:
        with lookup.file.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or lookup.column not in reader.fieldnames:
                raise ValidationError(f"Lookup {lookup.file} needs a {lookup.column!r} column")
            return [
                {
                    "value": row.get(lookup.column, ""),
                    "description": row.get("description", ""),
                    "parent": row.get("parent", ""),
                }
                for row in reader
            ]
    except OSError as error:
        raise ValidationError(f"Cannot read lookup {lookup.file}: {error.strerror or error}") from error


def _script(raw: Any, repository_id: str) -> Script:
    value = _mapping(raw, f"Script in repository {repository_id}")
    _keys(value, {"name", "command", "description"}, f"script in repository {repository_id}")
    name = _string(value.get("name"), "Script name")
    command = value.get("command")
    if not isinstance(command, list) or not command:
        raise ValidationError(f"Script {name} command must be a non-empty list")
    command_tuple = tuple(_string(part, f"Command item for {name}") for part in command)
    description = value.get("description", "")
    if not isinstance(description, str):
        raise ValidationError(f"Script description for {name} must be a string")
    return Script(name, command_tuple, description)


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path).expanduser().resolve()
    raw = _mapping(_yaml(config_path), f"Configuration {config_path}")
    _keys(raw, {"repository_root", "repositories", "preferences"}, "configuration")
    root = _child_path(config_path.parent, raw.get("repository_root", "."), "repository_root")
    repositories_raw = _mapping(raw.get("repositories"), "repositories")
    if not repositories_raw:
        raise ValidationError("At least one repository must be configured")
    preferences = _child_path(root, raw.get("preferences", "local/preferences.json"), "preferences")
    repositories: dict[str, Repository] = {}
    for repository_id, item in repositories_raw.items():
        repository_id = _string(repository_id, "Repository id")
        value = _mapping(item, f"Repository {repository_id}")
        _keys(value, {"name", "directory", "store", "schema", "log", "scripts"}, f"repository {repository_id}")
        directory = _child_path(root, value.get("directory"), f"Directory for {repository_id}")
        store = _inside(_child_path(directory, value.get("store"), f"Store for {repository_id}"), directory, f"Store for {repository_id}")
        schema = _inside(_child_path(directory, value.get("schema"), f"Schema for {repository_id}"), directory, f"Schema for {repository_id}")
        log = _inside(_child_path(directory, value.get("log", "changes.csv"), f"Log for {repository_id}"), directory, f"Log for {repository_id}")
        scripts_raw = value.get("scripts", [])
        if not isinstance(scripts_raw, list):
            raise ValidationError(f"Scripts for {repository_id} must be a list")
        scripts = tuple(_script(script, repository_id) for script in scripts_raw)
        if len({script.name for script in scripts}) != len(scripts):
            raise ValidationError(f"Script names must be unique in repository {repository_id}")
        repositories[repository_id] = Repository(
            id=repository_id,
            name=_string(value.get("name", repository_id), f"Name for {repository_id}"),
            directory=directory,
            store=store,
            schema=schema,
            log=log,
            scripts=scripts,
        )
    return AppConfig(root, preferences, repositories)
