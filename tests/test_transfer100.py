from __future__ import annotations

from collections import Counter
from pathlib import Path

from ultron.learning.transfer import TransferDataset, TransferExperiment


def test_transfer100_has_five_balanced_families_and_private_contracts() -> None:
    root = Path(__file__).resolve().parents[1] / "benchmarks" / "transfer100"
    dataset = TransferDataset(root)
    tasks = dataset.public_tasks()
    assert len(tasks) == 100
    assert len(dataset.private_answers()) == 100
    assert Counter(task["family"] for task in tasks) == {
        "structured_validation": 20,
        "dependency_recovery": 20,
        "state_recovery": 20,
        "planning": 20,
        "configuration_repair": 20,
    }
    assert all({"actions", "response_format", "source_domain", "target_domain"} <= set(task) for task in tasks)
    assert all("expected_sequence" in contract for contract in dataset.private_answers().values())


def test_transfer100_rejects_objective_or_private_contract_in_experience_corpus() -> None:
    root = Path(__file__).resolve().parents[1] / "benchmarks" / "transfer100"
    dataset = TransferDataset(root)
    objective = dataset.public_tasks()[0]["objective"]
    expected = dataset.private_answers()[dataset.public_tasks()[0]["id"]]["expected_sequence"]
    for leaked in (objective, expected):
        try:
            dataset.assert_isolated([leaked])
        except RuntimeError:
            pass
        else:
            raise AssertionError("O guard deve rejeitar vazamento de objetivo ou contrato privado")


def test_transfer100_origin_procedures_do_not_contain_public_task_text() -> None:
    root = Path(__file__).resolve().parents[1] / "benchmarks" / "transfer100"
    dataset = TransferDataset(root)
    corpus = [item for values in TransferExperiment.ORIGIN_CORPUS.values() for item in values]
    dataset.assert_isolated(corpus)
