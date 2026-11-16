"""A deliberately small, dependency-free YAML reader for application config.

Supported YAML consists of indentation-based mappings and sequences, quoted or
plain scalars, and flow lists/mappings. Unsupported constructs fail with a line
number instead of being interpreted ambiguously.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any


class YAMLError(ValueError):
    pass


@dataclass(frozen=True)
class _Token:
    line: int
    indent: int
    text: str


_INTEGER = re.compile(r"[-+]?(?:0|[1-9][0-9]*)$")
_FLOAT = re.compile(r"[-+]?(?:[0-9]+\.[0-9]*|[0-9]*\.[0-9]+)(?:[eE][-+]?[0-9]+)?$")


def _strip_comment(text: str) -> str:
    quote: str | None = None
    escaped = False
    depth = 0
    for index, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if quote == '"' and char == "\\":
            escaped = True
            continue
        if quote:
            if char == quote:
                if quote == "'" and index + 1 < len(text) and text[index + 1] == "'":
                    continue
                quote = None
            continue
        if char in "'\"":
            quote = char
        elif char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
        elif char == "#" and depth == 0 and (index == 0 or text[index - 1].isspace()):
            return text[:index].rstrip()
    return text.rstrip()


def _split_outside(text: str, separator: str) -> list[str]:
    parts: list[str] = []
    quote: str | None = None
    escaped = False
    depth = 0
    start = 0
    for index, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if quote == '"' and char == "\\":
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = None
            continue
        if char in "'\"":
            quote = char
        elif char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
        elif char == separator and depth == 0:
            parts.append(text[start:index].strip())
            start = index + 1
    if quote or depth != 0:
        raise YAMLError(f"Unclosed quote or flow collection: {text}")
    parts.append(text[start:].strip())
    return parts


def _split_pair(text: str) -> tuple[str, str] | None:
    quote: str | None = None
    escaped = False
    depth = 0
    for index, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if quote == '"' and char == "\\":
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = None
            continue
        if char in "'\"":
            quote = char
        elif char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
        elif char == ":" and depth == 0 and (index + 1 == len(text) or text[index + 1].isspace()):
            return text[:index].strip(), text[index + 1 :].strip()
    return None


def _parse_scalar(text: str) -> Any:
    text = text.strip()
    if not text:
        return None
    if text in {"|", ">", "|-", ">-", "|+", ">+"}:
        raise YAMLError("Block scalar syntax is not supported; use a quoted string")
    if text.startswith('"'):
        try:
            value = json.loads(text)
        except json.JSONDecodeError as error:
            raise YAMLError(f"Invalid double-quoted string: {error.msg}") from error
        if not isinstance(value, str):
            raise YAMLError("Expected a string")
        return value
    if text.startswith("'"):
        if len(text) < 2 or not text.endswith("'"):
            raise YAMLError("Unclosed single-quoted string")
        return text[1:-1].replace("''", "'")
    if text.startswith("["):
        if not text.endswith("]"):
            raise YAMLError("Unclosed flow list")
        inner = text[1:-1].strip()
        return [] if not inner else [_parse_scalar(part) for part in _split_outside(inner, ",")]
    if text.startswith("{"):
        if not text.endswith("}"):
            raise YAMLError("Unclosed flow mapping")
        inner = text[1:-1].strip()
        result: dict[str, Any] = {}
        if not inner:
            return result
        for part in _split_outside(inner, ","):
            pair = _split_pair(part)
            if pair is None:
                raise YAMLError(f"Expected key: value in flow mapping: {part}")
            key, value = pair
            key_value = _parse_scalar(key)
            if not isinstance(key_value, str):
                raise YAMLError("Mapping keys must be strings")
            if key_value in result:
                raise YAMLError(f"Duplicate mapping key: {key_value}")
            result[key_value] = _parse_scalar(value)
        return result
    lowered = text.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "~"}:
        return None
    if _INTEGER.fullmatch(text):
        return int(text)
    if _FLOAT.fullmatch(text):
        return float(text)
    return text


def _key(raw: str, line: int) -> str:
    try:
        value = _parse_scalar(raw)
    except YAMLError as error:
        raise YAMLError(f"Line {line}: {error}") from error
    if not isinstance(value, str) or not value:
        raise YAMLError(f"Line {line}: mapping keys must be non-empty strings")
    return value


def _scalar(raw: str, line: int) -> Any:
    try:
        return _parse_scalar(raw)
    except YAMLError as error:
        raise YAMLError(f"Line {line}: {error}") from error


def _parse_map(tokens: list[_Token], index: int, indent: int) -> tuple[dict[str, Any], int]:
    result: dict[str, Any] = {}
    while index < len(tokens) and tokens[index].indent == indent:
        token = tokens[index]
        if token.text == "-" or token.text.startswith("- "):
            break
        pair = _split_pair(token.text)
        if pair is None:
            raise YAMLError(f"Line {token.line}: expected key: value")
        raw_key, raw_value = pair
        key = _key(raw_key, token.line)
        if key in result:
            raise YAMLError(f"Line {token.line}: duplicate key {key!r}")
        index += 1
        if raw_value:
            result[key] = _scalar(raw_value, token.line)
        elif index < len(tokens) and tokens[index].indent > indent:
            result[key], index = _parse_block(tokens, index, tokens[index].indent)
        else:
            result[key] = None
        if index < len(tokens) and indent < tokens[index].indent:
            raise YAMLError(f"Line {tokens[index].line}: unexpected indentation")
    return result, index


def _parse_list(tokens: list[_Token], index: int, indent: int) -> tuple[list[Any], int]:
    result: list[Any] = []
    while index < len(tokens) and tokens[index].indent == indent:
        token = tokens[index]
        if token.text != "-" and not token.text.startswith("- "):
            break
        rest = token.text[1:].strip()
        index += 1
        if not rest:
            if index >= len(tokens) or tokens[index].indent <= indent:
                result.append(None)
            else:
                value, index = _parse_block(tokens, index, tokens[index].indent)
                result.append(value)
            continue
        pair = _split_pair(rest)
        if pair is None:
            result.append(_scalar(rest, token.line))
        else:
            raw_key, raw_value = pair
            item: dict[str, Any] = {}
            key = _key(raw_key, token.line)
            item_indent = indent + 2
            if raw_value:
                item[key] = _scalar(raw_value, token.line)
            elif index < len(tokens) and tokens[index].indent > item_indent:
                item[key], index = _parse_block(tokens, index, tokens[index].indent)
            else:
                item[key] = None
            if index < len(tokens) and tokens[index].indent == item_indent:
                extra, index = _parse_map(tokens, index, item_indent)
                for extra_key, value in extra.items():
                    if extra_key in item:
                        raise YAMLError(f"Line {token.line}: duplicate key {extra_key!r}")
                    item[extra_key] = value
            result.append(item)
        if index < len(tokens) and tokens[index].indent > indent:
            raise YAMLError(f"Line {tokens[index].line}: unexpected indentation in list item")
    return result, index


def _parse_block(tokens: list[_Token], index: int, indent: int) -> tuple[Any, int]:
    if tokens[index].indent != indent:
        raise YAMLError(f"Line {tokens[index].line}: inconsistent indentation")
    if tokens[index].text == "-" or tokens[index].text.startswith("- "):
        return _parse_list(tokens, index, indent)
    return _parse_map(tokens, index, indent)


def loads(text: str) -> Any:
    """Parse the supported YAML subset, raising YAMLError with source lines."""
    if text.startswith("\ufeff"):
        text = text[1:]
    tokens: list[_Token] = []
    for line_number, raw_line in enumerate(text.splitlines(), 1):
        if raw_line.startswith("\t"):
            raise YAMLError(f"Line {line_number}: tabs are not allowed for indentation")
        stripped = raw_line.lstrip(" ")
        content = _strip_comment(stripped)
        if not content.strip():
            continue
        tokens.append(_Token(line_number, len(raw_line) - len(stripped), content.strip()))
    if not tokens:
        return None
    if tokens[0].indent != 0:
        raise YAMLError(f"Line {tokens[0].line}: the document must start at indentation zero")
    value, index = _parse_block(tokens, 0, 0)
    if index != len(tokens):
        raise YAMLError(f"Line {tokens[index].line}: inconsistent indentation")
    return value
