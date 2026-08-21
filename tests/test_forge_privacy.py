from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest

from ultron.configuration import Settings, load_settings
from ultron.learning.transfer import PrivateBenchmarkRootError, TransferDataset, TransferExperiment
from ultron.research.leakage import (
    assert_private_contracts_isolated,
    scan_repository_for_private_contracts,
)

ROOT = Path(__file__).resolve().parents[1]


def _public_generator():
    path = ROOT / "scripts" / "build_transfer100_v4.py"
    spec = importlib.util.spec_from_file_location("build_transfer100_v4", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Gerador Transfer-100 v4 indisponível")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _private_contracts(tasks: list[dict]) -> dict[str, dict[str, str]]:
    return {
        str(task["id"]): {
            "expected_sequence": ">".join(str(action["code"]) for action in task["actions"][:2]),
            "contract_version": "fixture-private-v4",
        }
        for task in tasks
    }


def test_private_answers_not_reconstructable_from_public_generator() -> None:
    generator = _public_generator()
    tasks = generator.build_public_tasks()
    serialized = json.dumps(tasks, ensure_ascii=False)
    assert len(tasks) == 100
    assert not any("expected_sequence" in task or "fixture" in task for task in tasks)
    assert "expected_sequence" not in serialized
    assert "answers" not in generator.__dict__
    assert "fixtures" not in generator.__dict__


def test_public_repo_cannot_reconstruct_private_answers(tmp_path: Path) -> None:
    generator = _public_generator()
    public_root = tmp_path / "benchmarks" / "transfer100_v4"
    tasks = generator.write_public_dataset(public_root)
    private_root = tmp_path / "private" / "transfer100_v4"
    private_root.mkdir(parents=True)
    answers = _private_contracts(tasks)
    (private_root / "answers.json").write_text(json.dumps(answers), encoding="utf-8")
    (private_root / "fixtures.json").write_text(json.dumps({key: {"token": f"secret-{key}"} for key in answers}), encoding="utf-8")
    dataset = TransferDataset(public_root, private_root, require_external_contracts=True)
    assert len(dataset.public_tasks()) == 100
    assert dataset.private_answers() == answers
    assert not (public_root / "answers.json").exists()
    assert not (public_root / "fixtures.json").exists()


def test_leakage_scanner_reports_zero_overlap_and_detects_injected_contract(tmp_path: Path) -> None:
    generator = _public_generator()
    repo = tmp_path / "repo"
    public_root = repo / "benchmarks" / "transfer100_v4"
    tasks = generator.write_public_dataset(public_root)
    for directory in (repo / "scripts", repo / "ultron"):
        directory.mkdir(parents=True)
    private_root = tmp_path / "private"
    private_root.mkdir()
    answers = _private_contracts(tasks)
    (private_root / "answers.json").write_text(json.dumps(answers), encoding="utf-8")
    (private_root / "fixtures.json").write_text(json.dumps({key: {"token": f"isolation-value-{key}"} for key in answers}), encoding="utf-8")
    report = assert_private_contracts_isolated(repo, private_root)
    assert report.public_private_overlap == 0
    leaked_value = next(iter(answers.values()))["expected_sequence"]
    (repo / "scripts" / "leak.py").write_text(f"value = {leaked_value!r}\n", encoding="utf-8")
    detected = scan_repository_for_private_contracts(repo, private_root)
    assert detected.public_private_overlap == 1


def test_transfer100_v4_requires_configured_private_root(tmp_path: Path) -> None:
    settings = Settings(raw=deepcopy(load_settings(ROOT).raw), root_dir=tmp_path)
    settings.raw["research"]["private_benchmark_root"] = None
    with pytest.raises(PrivateBenchmarkRootError):
        TransferExperiment(settings, benchmark_name="transfer100_v4")


def test_transfer100_v4_rejects_public_directory_as_contract_root(tmp_path: Path) -> None:
    generator = _public_generator()
    public_root = tmp_path / "benchmarks" / "transfer100_v4"
    generator.write_public_dataset(public_root)
    with pytest.raises(PrivateBenchmarkRootError):
        TransferDataset(public_root, public_root, require_external_contracts=True)
