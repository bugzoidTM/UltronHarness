from __future__ import annotations

import os
from pathlib import Path

import pytest

from ultron.configuration import load_settings
from ultron.policy.engine import PolicyEngine
from ultron.schemas import RiskLevel


@pytest.fixture()
def policy(tmp_path: Path) -> PolicyEngine:
    settings = load_settings()
    settings.workspace_root = tmp_path / "workspace"
    settings.workspace_root.mkdir()
    return PolicyEngine(settings)


@pytest.mark.parametrize("path", [
    "..\\..\\Windows\\System32",
    "../../Windows/System32",
    "C:\\Windows\\System32",
    "\\\\server\\share\\secret.txt",
    "\\\\?\\C:\\Windows\\System32",
    "%USERPROFILE%\\secret.txt",
    "$env:USERPROFILE\\secret.txt",
])
def test_windows_path_escape_is_denied(policy: PolicyEngine, path: str) -> None:
    decision = policy.evaluate("file.read", {"path": path}, RiskLevel.R0, 3)
    assert not decision.allowed
    assert decision.risk == RiskLevel.R5


def test_symlink_and_case_variation_escape_are_denied(policy: PolicyEngine, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    link = policy.workspace_root / "LinkOut"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except OSError:
        pytest.skip("Criação de symlink indisponível neste Windows")
    assert not policy.evaluate("file.read", {"path": "linkout\\secret.txt"}, RiskLevel.R0, 3).allowed


@pytest.mark.parametrize("command", [
    "powershell -Command Get-ChildItem",
    "cmd.exe /c whoami",
    "pwsh -Command Get-ChildItem",
    "Start-Process cmd.exe",
    "python -c \"import subprocess\"",
])
def test_nested_windows_shell_invocation_is_denied(policy: PolicyEngine, command: str) -> None:
    decision = policy.evaluate("shell.run", {"command": command}, RiskLevel.R2, 3)
    assert not decision.allowed
    assert decision.risk == RiskLevel.R5
