from ultron.research.hermes_transfer import (
    CrossDomainTrial,
    CrossModelTrial,
    model_transfer_matrix,
    summarize_cross_domain,
)


def test_cross_domain_requires_positive_evidence_in_two_families() -> None:
    trials = [
        CrossDomainTrial("json", "yaml", "validation", 0.2, 0.5),
        CrossDomainTrial("json", "yaml", "validation", 0.2, 0.45),
        CrossDomainTrial("python", "node", "dependency", 0.1, 0.4),
        CrossDomainTrial("python", "node", "dependency", 0.1, 0.35),
    ]
    summary = summarize_cross_domain(trials)
    assert summary.general_procedural_transfer_gain > 0
    assert summary.positive_families == 2


def test_model_transfer_matrix_is_separated_by_model_and_family() -> None:
    matrix = model_transfer_matrix([
        CrossModelTrial("research", "validation", 0.2, 0.5),
        CrossModelTrial("smoke", "validation", 0.2, 0.1),
    ])
    assert matrix["research"]["validation"] == 0.3
    assert matrix["smoke"]["validation"] == -0.1
