"""Saúde do sistema e watchdog local sem telemetria externa."""

from __future__ import annotations

import asyncio
import shutil
from typing import Any

import psutil

from ultron.configuration import Settings
from ultron.core.events import EventBus
from ultron.core.orchestrator import Orchestrator
from ultron.db import Database
from ultron.models.gateway import ModelGateway


class HealthService:
    def __init__(self, settings: Settings, db: Database, models: ModelGateway):
        self.settings, self.db, self.models = settings, db, models

    async def snapshot(self) -> dict[str, Any]:
        disk = shutil.disk_usage(self.settings.data_dir)
        ram = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=None)
        model_health = await self.models.health()
        primary = self.settings.raw["models"]["primary"]
        primary_health = model_health.get(primary, {})
        return {
            "status": "healthy",
            "database": self._database_ok(),
            "vector_store": False,
            "llm": bool(primary_health.get("available")),
            "llm_generative": bool(
                primary_health.get("generative", primary_health.get("available", False))
                and primary != "local-fallback"
            ),
            "browser": False,
            "disk_free_gb": round(disk.free / 1024**3, 2),
            "memory_available_gb": round(ram.available / 1024**3, 2),
            "cpu_percent": cpu,
            "memory_percent": ram.percent,
            "model": {"active": primary, **primary_health},
            "privacy": {"external_telemetry": False, "cloud_llm": False, "remote_storage": False},
        }

    def _database_ok(self) -> bool:
        try:
            self.db.one("SELECT 1 AS value")
            return True
        except Exception:
            return False


class Watchdog:
    def __init__(self, settings: Settings, orchestrator: Orchestrator, events: EventBus):
        self.settings, self.orchestrator, self.events = settings, orchestrator, events
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if not self._task or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="ultron-watchdog")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await asyncio.wait([self._task], timeout=5)

    async def _loop(self) -> None:
        while not self._stop.is_set():
            memory = psutil.virtual_memory().percent
            cpu = psutil.cpu_percent(interval=None)
            disk_free = shutil.disk_usage(self.settings.data_dir).free / 1024**3
            limits = self.settings.raw["watchdog"]
            if (
                cpu > limits["max_cpu_percent"]
                or memory > limits["max_memory_percent"]
                or disk_free < limits["min_disk_free_gb"]
            ):
                count = await self.orchestrator.kill_all()
                await self.events.emit(
                    "system.watchdog_paused",
                    {
                        "tasks_cancelled": count,
                        "cpu_percent": cpu,
                        "memory_percent": memory,
                        "disk_free_gb": round(disk_free, 2),
                    },
                )
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=float(limits["poll_seconds"]))
            except TimeoutError:
                pass
