"""Configured external script execution with captured output."""

from __future__ import annotations

from dataclasses import dataclass
import os
import subprocess

from .config import Repository, Script


TIMEOUT_SECONDS = 300
MAX_OUTPUT_CHARS = 4000


@dataclass(frozen=True)
class ScriptOutcome:
    status: str  # "success" or "failed"
    exit_code: int | None
    output: str
    detail: str

    def to_dict(self, script: Script) -> dict:
        return {
            "script": script.name,
            "status": self.status,
            "exit_code": self.exit_code,
            "output": self.output,
            "detail": self.detail,
        }


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + f"\n… truncated ({len(text)} characters total)"


def execute(repository: Repository, script: Script) -> ScriptOutcome:
    environment = {
        **os.environ,
        "CSVLIST_REPOSITORY_DIR": str(repository.directory),
        "CSVLIST_STORE": str(repository.store),
        "CSVLIST_LOG": str(repository.log),
    }
    try:
        completed = subprocess.run(
            list(script.command),
            cwd=repository.directory,
            env=environment,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        return ScriptOutcome("failed", None, "", f"Command not found: {script.command[0]}")
    except PermissionError:
        return ScriptOutcome("failed", None, "", f"Command is not executable: {script.command[0]}")
    except subprocess.TimeoutExpired as error:
        parts = [part for part in (error.stdout, error.stderr) if part]
        output = _truncate("".join(part if isinstance(part, str) else part.decode("utf-8", "replace") for part in parts))
        return ScriptOutcome("failed", None, output, f"Timed out after {TIMEOUT_SECONDS} seconds")
    except OSError as error:
        return ScriptOutcome("failed", None, "", f"Could not start the script: {error.strerror or error}")
    output = _truncate("".join(part for part in (completed.stdout, completed.stderr) if part))
    if completed.returncode != 0:
        return ScriptOutcome("failed", completed.returncode, output, f"Exited with status {completed.returncode}")
    return ScriptOutcome("success", completed.returncode, output, "")
