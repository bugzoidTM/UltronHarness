"""Plano de controle determinístico: o modelo nunca executa ferramentas diretamente."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ultron.configuration import Settings
from ultron.schemas import RiskLevel


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    requires_approval: bool
    risk: RiskLevel
    rationale: str


class PolicyEngine:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.workspace_root = settings.workspace_root.resolve()
        self.approval_risks = {
            RiskLevel(value) for value in settings.raw["security"]["require_approval_for"]
        }
        self.blocked_shell_patterns = tuple(
            pattern.lower() for pattern in settings.raw["security"]["blocked_shell_patterns"]
        )

    def evaluate(
        self, tool_name: str, arguments: dict[str, Any], risk: RiskLevel, autonomy_mode: int
    ) -> PolicyDecision:
        if risk == RiskLevel.R5:
            return PolicyDecision(
                False, False, risk, "Ação classificada como proibida pela política local."
            )
        if tool_name.startswith("browser.") and not self.settings.raw["network"]["internet_read"]:
            return PolicyDecision(
                False, False, risk, "Acesso de rede desativado na configuração local."
            )
        if tool_name == "shell.run":
            command = str(arguments.get("command", "")).lower()
            windows_shells = ("powershell", "pwsh", "cmd.exe", "cmd /c", "start-process", "subprocess")
            if any(pattern in command for pattern in self.blocked_shell_patterns) or any(token in command for token in windows_shells):
                return PolicyDecision(
                    False, False, RiskLevel.R5, "Comando bloqueado por padrão de segurança."
                )
        if tool_name.startswith("file."):
            requested = arguments.get("path", "")
            if not self._workspace_path_allowed(requested):
                return PolicyDecision(
                    False, False, RiskLevel.R5, "O caminho está fora do workspace permitido."
                )
        if risk in {RiskLevel.R3, RiskLevel.R4}:
            return PolicyDecision(
                True,
                True,
                risk,
                "Ação de efeito externo ou privilegiado requer aprovação explícita.",
            )
        if risk == RiskLevel.R2 and autonomy_mode < 3:
            return PolicyDecision(
                True, True, risk, "Modificações exigem aprovação fora do modo Workspace Autonomous."
            )
        if risk in self.approval_risks:
            return PolicyDecision(
                True, True, risk, "O nível de risco está configurado para aprovação."
            )
        if autonomy_mode == 0:
            return PolicyDecision(
                False, False, risk, "Modo Chat não permite execução de ferramentas."
            )
        if autonomy_mode == 1:
            return PolicyDecision(
                True, True, risk, "Modo Copilot requer confirmação para qualquer ferramenta."
            )
        return PolicyDecision(
            True, False, risk, "Ação permitida dentro da política e modo de autonomia atuais."
        )

    def _workspace_path_allowed(self, requested: str) -> bool:
        if not requested:
            return False
        raw = str(requested).strip()
        # UNC, device paths, expansão de ambiente e NUL não têm uma semântica segura no sandbox.
        if not raw or "\x00" in raw or raw.startswith(("\\\\", "//")) or raw.startswith("\\\\?\\") or "%" in raw or "$env:" in raw.casefold():
            return False
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = self.workspace_root / candidate
        try:
            candidate.resolve().relative_to(self.workspace_root)
            return True
        except ValueError:
            return False
