from __future__ import annotations

import importlib.util
import json
from collections import Counter
from pathlib import Path

from ultron.learning.transfer import TransferDataset, TransferExperiment

ROOT = Path(__file__).resolve().parents[1]


def _generator_module():
    path = ROOT / "scripts" / "build_transfer100_v3.py"
    spec = importlib.util.spec_from_file_location("build_transfer100_v3", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Gerador Transfer-100 v3 indisponível")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_transfer100_v3_has_100_distinct_public_cases_and_balanced_families() -> None:
    generator = _generator_module()
    tasks, answers, fixtures = generator.build()
    assert len(tasks) == len(answers) == len(fixtures) == 100
    assert Counter(task["family"] for task in tasks) == {
        "structured_validation": 20,
        "dependency_recovery": 20,
        "state_recovery": 20,
        "planning": 20,
        "configuration_repair": 20,
    }
    assert len({task["case_key"] for task in tasks}) == 100
    assert all(len({task["objective"] for task in tasks if task["family"] == family}) == 20 for family in {task["family"] for task in tasks})
    assert all("expected_sequence" in contract for contract in answers.values())


def test_transfer100_v3_public_directory_has_no_contract_and_reads_external_contract(tmp_path: Path) -> None:
    generator = _generator_module()
    _, answers, fixtures = generator.build()
    public_root = ROOT / "benchmarks" / "transfer100_v3"
    assert (public_root / "tasks.yaml").exists()
    assert not (public_root / "answers.json").exists()
    assert not (public_root / "fixtures.json").exists()
    (tmp_path / "answers.json").write_text(json.dumps(answers), encoding="utf-8")
    (tmp_path / "fixtures.json").write_text(json.dumps(fixtures), encoding="utf-8")
    dataset = TransferDataset(public_root, tmp_path)
    assert len(dataset.public_tasks()) == 100
    assert len(dataset.private_answers()) == 100
    dataset.assert_isolated(["procedimento abstrato sem texto de tarefa ou contrato"])


def test_transfer100_v3_uses_correct_state_recovery_origin_family() -> None:
    assert "state_recovery" in TransferExperiment.ORIGIN_CORPUS
    assert "recovery" not in TransferExperiment.ORIGIN_CORPUS


def test_transfer100_v3_router_ablation_defaults_to_abstention_without_paired_evidence(
    tmp_path: Path,
) -> None:
    import asyncio
    from copy import deepcopy

    from ultron.configuration import Settings, load_settings
    from ultron.learning.transfer import TransferRoutingAblation
    from ultron.models.gateway import ModelResponse, Usage

    generator = _generator_module()
    _, answers, fixtures = generator.build()
    (tmp_path / "answers.json").write_text(json.dumps(answers), encoding="utf-8")
    (tmp_path / "fixtures.json").write_text(json.dumps(fixtures), encoding="utf-8")
    settings = Settings(raw=deepcopy(load_settings(ROOT).raw), root_dir=tmp_path / "runtime")
    ablation = TransferRoutingAblation(settings, "local-fallback", 42, contract_root=tmp_path)
    ablation.dataset = TransferDataset(ROOT / "benchmarks" / "transfer100_v3", tmp_path)

    async def deterministic_generate(*_args, **_kwargs):
        return ModelResponse("P>R", [], Usage(), 0, "deterministic-test", "stop", True)

    ablation.models.generate = deterministic_generate
    result = asyncio.run(ablation.run_async())
    router_traces = result["traces"]["router_use_abstain_reject"]
    assert result["execution_mode"] == "per_task"
    assert result["conditions"]["router_use_abstain_reject"] == result["conditions"]["never_inject"]
    assert all(trace["routing_decision"] == "ABSTAIN" for trace in router_traces)
    assert not any(trace["injected"] for trace in router_traces)
