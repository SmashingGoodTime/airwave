"""Tests for the local PowerShell test runner."""

import os
import shutil
import subprocess
import textwrap
import uuid
from pathlib import Path

import pytest


def _run_test_script(
    repo_root: Path,
    test_file: Path,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Run scripts/test.ps1 against a generated test file."""
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell is required to exercise scripts/test.ps1")

    if env is None:
        env = os.environ.copy()
        env.pop("PYTEST_ADDOPTS", None)

    return subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(repo_root / "scripts" / "test.ps1"),
            str(test_file),
        ],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )


def test_test_script_uses_workspace_basetemp_by_default() -> None:
    """The PowerShell runner should keep pytest temp files in the repo."""
    repo_root = Path(__file__).resolve().parents[1]
    nested_dir = repo_root / "tests" / ".tmp" / f"test_runner_{uuid.uuid4().hex}"
    nested_dir.mkdir(parents=True)
    nested_test = nested_dir / "test_workspace_basetemp.py"
    expected_basetemp = repo_root / ".pytest_tmp"

    nested_test.write_text(
        textwrap.dedent(
            f"""
            from pathlib import Path


            def test_tmp_path_is_under_workspace_basetemp(tmp_path):
                expected = Path({str(expected_basetemp)!r}).resolve()
                actual = tmp_path.resolve()
                assert expected == actual or expected in actual.parents
            """
        ).lstrip(),
        encoding="utf-8",
    )

    external_temproot = nested_dir / "external_temp"
    external_temproot.mkdir()
    env = os.environ.copy()
    env.pop("PYTEST_ADDOPTS", None)
    env["PYTEST_DEBUG_TEMPROOT"] = str(external_temproot)

    try:
        result = _run_test_script(repo_root, nested_test, env=env)
    finally:
        shutil.rmtree(nested_dir, ignore_errors=True)

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "1 passed" in output, output
    assert "failed" not in output.lower(), output


def test_test_script_propagates_pytest_failure_exit_code() -> None:
    """The PowerShell runner should fail when the pytest run fails."""
    repo_root = Path(__file__).resolve().parents[1]
    nested_dir = repo_root / "tests" / ".tmp" / f"test_runner_{uuid.uuid4().hex}"
    nested_dir.mkdir(parents=True)
    nested_test = nested_dir / "test_failure_exit_code.py"

    nested_test.write_text(
        textwrap.dedent(
            """
            def test_intentional_failure():
                assert False
            """
        ).lstrip(),
        encoding="utf-8",
    )

    try:
        result = _run_test_script(repo_root, nested_test)
    finally:
        shutil.rmtree(nested_dir, ignore_errors=True)

    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "FAILED" in output, output
