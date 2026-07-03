"""Shared utility for reading and writing the .env file."""

import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Anchor the default .env path to the project root (same convention as
# server/config.py) so writes land in the same file the app reads,
# regardless of the working directory the process was launched from.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_ENV_FILE = _PROJECT_ROOT / ".env"

_VALID_VAR_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def _format_env_line(var_name: str, value: str) -> str:
    """Build a safe ``NAME=value`` line for the .env file.

    Args:
        var_name: Environment variable name.
        value: The value to write.

    Returns:
        A single sanitized ``NAME=value`` line.

    Raises:
        ValueError: If the variable name is invalid or the value contains
            control characters/newlines after whitespace stripping (which
            would inject arbitrary lines into the .env file).
    """
    if not _VALID_VAR_NAME.match(var_name):
        raise ValueError(f"Invalid environment variable name: {var_name!r}")

    value = value.strip()
    if _CONTROL_CHARS.search(value):
        raise ValueError(
            f"Value for {var_name} contains control characters or newlines"
        )

    # Quote values that a naive .env parser would truncate or mangle.
    if " " in value or "#" in value or '"' in value:
        value = '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

    return f"{var_name}={value}"


def update_env_file(keys: dict[str, str]) -> None:
    """Write or update API keys in the .env file.

    Reads the existing .env, replaces matching keys in place,
    and appends any keys that weren't already present.

    Args:
        keys: Mapping of environment variable names to values.

    Raises:
        ValueError: If a variable name is invalid or a value contains
            control characters/newlines.
    """
    env_path = Path(os.getenv("ENV_FILE", str(_DEFAULT_ENV_FILE)))

    # Sanitize everything up front so a bad value cannot leave the file
    # half-written.
    formatted = {
        var_name: _format_env_line(var_name, value)
        for var_name, value in keys.items()
    }

    existing_lines: list[str] = []
    if env_path.exists():
        existing_lines = env_path.read_text(encoding="utf-8").splitlines()

    updated_keys: set[str] = set()
    new_lines: list[str] = []

    for line in existing_lines:
        stripped = line.strip()
        # Match lines like KEY=value (skip comments and blanks)
        if stripped and not stripped.startswith("#") and "=" in stripped:
            var_name = stripped.split("=", 1)[0].strip()
            if var_name in formatted:
                new_lines.append(formatted[var_name])
                updated_keys.add(var_name)
                continue
        new_lines.append(line)

    # Append any keys that weren't already in the file
    for var_name, line in formatted.items():
        if var_name not in updated_keys:
            new_lines.append(line)

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    logger.info("Updated .env with %d API key(s)", len(keys))
