"""Shared utility for reading and writing the .env file."""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def update_env_file(keys: dict[str, str]) -> None:
    """Write or update API keys in the .env file.

    Reads the existing .env, replaces matching keys in place,
    and appends any keys that weren't already present.

    Args:
        keys: Mapping of environment variable names to values.
    """
    env_path = Path(os.getenv("ENV_FILE", ".env"))
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
            if var_name in keys:
                new_lines.append(f"{var_name}={keys[var_name]}")
                updated_keys.add(var_name)
                continue
        new_lines.append(line)

    # Append any keys that weren't already in the file
    for var_name, value in keys.items():
        if var_name not in updated_keys:
            new_lines.append(f"{var_name}={value}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    logger.info("Updated .env with %d API key(s)", len(keys))
