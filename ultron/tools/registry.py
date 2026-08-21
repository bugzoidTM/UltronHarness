"""Ferramentas locais com manifestos, limites e execução dentro do workspace isolado."""

from __future__ import annotations

import asyncio
import os
import subprocess
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from ultron.configuration import Settings
from ultron.schemas import RiskLevel


@dataclass(frozen=True, slots=True)
class ToolManifest:
    name: str
    description: str
    risk: RiskLevel
    approval: bool
    timeout: int
    permissions: tuple[str, ...]


@dataclass(slots=True)
class ToolResult:
    ok: bool
    output: str
    error: str | None
    duration_ms: int
    metadata: dict[str, Any]


ToolHandler = Callable[[dict[str, Any], Path], Awaitable[ToolResult]]


class ToolRegistry:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.root = settings.workspace_root.resolve()
        self.manifests: dict[str, ToolManifest] = {}
        self.handlers: dict[str, ToolHandler] = {}
        self._register_defaults()

    def _register(self, manifest: ToolManifest, handler: ToolHandler) -> None:
        self.manifests[manifest.name] = manifest
        self.handlers[manifest.name] = handler

    def _register_defaults(self) -> None:
        self._register(
            ToolManifest(
                "file.list",
                "Lista arquivos dentro do workspace.",
                RiskLevel.R0,
                False,
                15,
                ("workspace.read",),
            ),
            self._file_list,
        )
        self._register(
            ToolManifest(
                "file.read",
                "Lê texto UTF-8 dentro do workspace.",
                RiskLevel.R0,
                False,
                15,
                ("workspace.read",),
            ),
            self._file_read,
        )
        self._register(
            ToolManifest(
                "file.search",
                "Busca texto em arquivos dentro do workspace.",
                RiskLevel.R0,
                False,
                15,
                ("workspace.read",),
            ),
            self._file_search,
        )
        self._register(
            ToolManifest(
                "file.write",
                "Cria ou substitui arquivo no workspace.",
                RiskLevel.R2,
                True,
                15,
                ("workspace.write",),
            ),
            self._file_write,
        )
        self._register(
            ToolManifest(
                "file.delete",
                "Remove arquivo no workspace.",
                RiskLevel.R2,
                True,
                15,
                ("workspace.write",),
            ),
            self._file_delete,
        )
        self._register(
            ToolManifest(
                "python.execute",
                "Executa um script Python isolado no workspace.",
                RiskLevel.R1,
                False,
                30,
                ("workspace.execute",),
            ),
            self._python_execute,
        )
        self._register(
            ToolManifest(
                "shell.run",
                "Executa comando sem shell, em diretório isolado.",
                RiskLevel.R2,
                True,
                30,
                ("workspace.execute",),
            ),
            self._shell_run,
        )
        self._register(
            ToolManifest(
                "git.status",
                "Mostra estado Git do workspace.",
                RiskLevel.R0,
                False,
                20,
                ("workspace.read",),
            ),
            self._git_status,
        )
        self._register(
            ToolManifest(
                "git.diff",
                "Mostra mudanças Git do workspace.",
                RiskLevel.R0,
                False,
                20,
                ("workspace.read",),
            ),
            self._git_diff,
        )
        self._register(
            ToolManifest(
                "git.log",
                "Mostra histórico Git do workspace.",
                RiskLevel.R0,
                False,
                20,
                ("workspace.read",),
            ),
            self._git_log,
        )

    def list_manifests(self) -> list[dict[str, Any]]:
        return [
            {**asdict(manifest), "risk": manifest.risk.value}
            for manifest in self.manifests.values()
        ]

    def get_manifest(self, name: str) -> ToolManifest | None:
        return self.manifests.get(name)

    async def execute(
        self, name: str, arguments: dict[str, Any], workspace_name: str
    ) -> ToolResult:
        handler = self.handlers.get(name)
        if not handler:
            return ToolResult(False, "", f"Ferramenta desconhecida: {name}", 0, {})
        workspace = self.workspace_for(workspace_name)
        started = perf_counter()
        try:
            result = await asyncio.wait_for(
                handler(arguments, workspace), timeout=self.manifests[name].timeout
            )
            result.duration_ms = max(result.duration_ms, int((perf_counter() - started) * 1000))
            return result
        except TimeoutError:
            return ToolResult(
                False,
                "",
                "Tempo máximo de ferramenta excedido.",
                int((perf_counter() - started) * 1000),
                {},
            )
        except Exception as exc:  # superfície controlada para o executor
            return ToolResult(
                False, "", f"Falha da ferramenta: {exc}", int((perf_counter() - started) * 1000), {}
            )

    def workspace_for(self, name: str) -> Path:
        safe = "".join(char for char in name if char.isalnum() or char in "_-") or "default"
        path = (self.root / safe).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _limit(text: str) -> str:
        return text[:20000]

    @staticmethod
    def _result(
        ok: bool, output: str = "", error: str | None = None, **metadata: Any
    ) -> ToolResult:
        return ToolResult(ok, output[:20000], error, 0, metadata)

    def _resolve(self, workspace: Path, raw_path: str) -> Path:
        path = (workspace / raw_path).resolve()
        try:
            path.relative_to(workspace)
        except ValueError as exc:
            raise ValueError("Caminho fora do workspace.") from exc
        return path

    async def _file_list(self, args: dict[str, Any], workspace: Path) -> ToolResult:
        target = self._resolve(workspace, str(args.get("path", ".")))
        if not target.exists():
            return self._result(False, error="Caminho não encontrado.")
        entries = [
            str(item.relative_to(workspace)) + ("/" if item.is_dir() else "")
            for item in target.rglob("*")
            if len(item.relative_to(target).parts) <= 4
        ]
        return self._result(True, "\n".join(sorted(entries)[:1000]), count=len(entries))

    async def _file_read(self, args: dict[str, Any], workspace: Path) -> ToolResult:
        target = self._resolve(workspace, str(args.get("path", "")))
        if not target.is_file():
            return self._result(False, error="Arquivo não encontrado.")
        return self._result(
            True,
            target.read_text(encoding="utf-8", errors="replace"),
            path=str(target.relative_to(workspace)),
        )

    async def _file_search(self, args: dict[str, Any], workspace: Path) -> ToolResult:
        query = str(args.get("query", "")).lower()
        if not query:
            return self._result(False, error="Consulta de busca vazia.")
        matches: list[str] = []
        for file in workspace.rglob("*"):
            if not file.is_file() or file.stat().st_size > 1_000_000:
                continue
            try:
                for index, line in enumerate(
                    file.read_text(encoding="utf-8", errors="ignore").splitlines(), 1
                ):
                    if query in line.lower():
                        matches.append(f"{file.relative_to(workspace)}:{index}: {line[:500]}")
            except OSError:
                continue
        return self._result(True, "\n".join(matches[:500]), count=len(matches))

    async def _file_write(self, args: dict[str, Any], workspace: Path) -> ToolResult:
        raw_path, content = str(args.get("path", "")), str(args.get("content", ""))
        if not raw_path:
            return self._result(False, error="Caminho do arquivo ausente.")
        target = self._resolve(workspace, raw_path)
        allowed = tuple(self.settings.raw["workspace"]["allowed_extensions"])
        if target.suffix.lower() not in allowed:
            return self._result(False, error="Extensão não permitida no workspace.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return self._result(
            True,
            f"Arquivo gravado: {target.relative_to(workspace)}",
            bytes=len(content.encode("utf-8")),
        )

    async def _file_delete(self, args: dict[str, Any], workspace: Path) -> ToolResult:
        target = self._resolve(workspace, str(args.get("path", "")))
        if not target.is_file():
            return self._result(False, error="Somente arquivos existentes podem ser removidos.")
        target.unlink()
        return self._result(True, f"Arquivo removido: {target.relative_to(workspace)}")

    async def _python_execute(self, args: dict[str, Any], workspace: Path) -> ToolResult:
        code = str(args.get("code", ""))
        if not code:
            return self._result(False, error="Código Python ausente.")
        command = [os.environ.get("PYTHON", "python"), "-I", "-c", code]
        return await self._run(command, workspace)

    async def _shell_run(self, args: dict[str, Any], workspace: Path) -> ToolResult:
        command = args.get("command")
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(item, str) for item in command)
        ):
            return self._result(
                False, error="shell.run exige command como lista de argumentos, sem shell."
            )
        return await self._run(command, workspace)

    async def _git_status(self, args: dict[str, Any], workspace: Path) -> ToolResult:
        return await self._run(["git", "status", "--short", "--branch"], workspace)

    async def _git_diff(self, args: dict[str, Any], workspace: Path) -> ToolResult:
        return await self._run(["git", "diff", "--", "."], workspace)

    async def _git_log(self, args: dict[str, Any], workspace: Path) -> ToolResult:
        return await self._run(["git", "log", "--oneline", "-20"], workspace)

    async def _run(self, command: list[str], workspace: Path) -> ToolResult:
        def invoke() -> ToolResult:
            try:
                completed = subprocess.run(
                    command,
                    cwd=workspace,
                    capture_output=True,
                    text=True,
                    timeout=25,
                    shell=False,
                    check=False,
                )
                output = self._limit((completed.stdout or "") + (completed.stderr or ""))
                return self._result(
                    completed.returncode == 0,
                    output,
                    None
                    if completed.returncode == 0
                    else f"Código de saída {completed.returncode}",
                    returncode=completed.returncode,
                )
            except FileNotFoundError:
                return self._result(False, error=f"Executável indisponível: {command[0]}")
            except subprocess.TimeoutExpired:
                return self._result(False, error="Processo excedeu o tempo máximo.")

        return await asyncio.to_thread(invoke)
