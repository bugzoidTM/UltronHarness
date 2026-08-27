"""Auditoria offline dos traces da execução pública Genesis v2-FINAL.

A auditoria não executa modelos, não consulta dados privados e não transforma
um término inválido em score zero. Ela avalia somente um candidate_answer que
esteja explicitamente serializado no JSON bruto ou em um trace estruturado.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

from ultron.benchmarks.models import BenchmarkTask, TaskExecution
from ultron.genesis.public_runner import GENESIS_PUBLIC_TASK_IDS, evaluate_public_task

PROTOCOL = "genesis-v2-final-executive-control"
HOLDOUT_IDS = ("reasoning_06", "reasoning_07")
CONDITIONS = ("generic_closed_loop_v2final", "endogenous_executive_v2final")
CONDITION_LABELS = {
    "generic_closed_loop_v2final": "B_fixed_executive",
    "endogenous_executive_v2final": "C_endogenous_executive",
}
EXPECTED_TOTAL_BUDGET = 1792
EXPECTED_MAX_DECISIONS = 7
EXPECTED_CALL_TOKENS = 256


class AuditContractError(ValueError):
    """Indica que o JSON não representa o contrato público v2-FINAL."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditContractError(message)


def _nonempty_string(value: object) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return None


def _candidate_from_row(row: dict[str, Any]) -> tuple[str | None, str | None]:
    """Recupera somente respostas explicitamente presentes, nunca por inferência."""
    direct = _nonempty_string(row.get("candidate_answer"))
    if direct is not None:
        return direct, "row.candidate_answer"

    failure_category = _nonempty_string(row.get("failure_category"))
    response = _nonempty_string(row.get("response"))
    if response is not None and failure_category not in {"TOOL_ERROR", "TIMEOUT"}:
        return response, "row.response"

    trace = row.get("trace")
    if not isinstance(trace, list):
        return None, None
    for entry in reversed(trace):
        if not isinstance(entry, dict):
            continue
        for key in ("candidate_answer", "answer"):
            candidate = _nonempty_string(entry.get(key))
            if candidate is not None:
                return candidate, f"trace.{key}"
        frame = entry.get("frame")
        if isinstance(frame, dict):
            candidate = _nonempty_string(frame.get("candidate_answer"))
            if candidate is not None:
                return candidate, "trace.frame.candidate_answer"
    return None, None


def _final_verification_status(row: dict[str, Any]) -> str:
    explicit = _nonempty_string(row.get("final_verification_status"))
    if explicit is not None:
        return explicit
    explicit = _nonempty_string(row.get("verification_status"))
    if explicit is not None:
        return explicit
    trace = row.get("trace")
    if isinstance(trace, list):
        for entry in reversed(trace):
            if isinstance(entry, dict):
                status = _nonempty_string(entry.get("verification_status"))
                if status is not None:
                    return status
    return ""


def _operator_sequence(row: dict[str, Any]) -> list[str]:
    trace = row.get("trace")
    if not isinstance(trace, list):
        return []
    return [
        operator
        for entry in trace
        if isinstance(entry, dict)
        for operator in [_nonempty_string(entry.get("operator"))]
        if operator is not None
    ]


def _load_public_tasks(repo_root: Path) -> dict[str, BenchmarkTask]:
    tasks: dict[str, BenchmarkTask] = {}
    task_dir = repo_root / "benchmarks" / "ugib_lite" / "tasks"
    for path in sorted(task_dir.glob("*.yaml")):
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        entries = loaded if isinstance(loaded, list) else [loaded]
        for entry in entries:
            task = BenchmarkTask.model_validate(entry)
            if task.id in GENESIS_PUBLIC_TASK_IDS and not task.hidden:
                tasks[task.id] = task
    return tasks


def _score_candidate(task: BenchmarkTask, candidate: str, model: str) -> dict[str, Any]:
    execution = TaskExecution(task_id=task.id, mode="baseline", response=candidate, model=model)
    evaluation = evaluate_public_task(task, execution)
    return {
        "success": evaluation.success,
        "score": evaluation.score,
        "evidence": list(evaluation.evidence),
        "errors": list(evaluation.errors),
    }


def _validate_payload_contract(payload: dict[str, Any]) -> list[dict[str, Any]]:
    _require(payload.get("protocol") == PROTOCOL, "protocol_mismatch")
    _require(tuple(payload.get("holdout_task_ids", ())) == HOLDOUT_IDS, "holdout_ids_mismatch")
    _require(payload.get("diagnosis_task_ids") == [], "diagnosis_tasks_must_be_empty")
    _require(payload.get("max_decisions_per_task") == EXPECTED_MAX_DECISIONS, "decision_budget_mismatch")
    _require(payload.get("total_token_budget_per_task_BC") == EXPECTED_TOTAL_BUDGET, "total_budget_mismatch")
    _require(payload.get("call_tokens_fixed_and_endogenous") == EXPECTED_CALL_TOKENS, "call_tokens_mismatch")
    for flag in ("holdout_sent_to_synthesizer", "rationale_used_for_execution", "synthesis_performed", "writeback_performed"):
        _require(payload.get(flag) is False, f"forbidden_flag_enabled:{flag}")

    rows = payload.get("rows")
    _require(isinstance(rows, list), "rows_must_be_list")
    _require(len(rows) == len(HOLDOUT_IDS) * len(CONDITIONS), "row_count_mismatch")
    normalized = [row for row in rows if isinstance(row, dict)]
    _require(len(normalized) == len(rows), "row_must_be_object")
    expected_pairs = {(condition, task_id) for condition in CONDITIONS for task_id in HOLDOUT_IDS}
    actual_pairs = {(row.get("condition"), row.get("task_id")) for row in normalized}
    _require(actual_pairs == expected_pairs, "condition_task_pairs_mismatch")
    for row in normalized:
        _require(row.get("decision_budget") == EXPECTED_MAX_DECISIONS, "row_decision_budget_mismatch")
        _require(row.get("call_tokens") == EXPECTED_CALL_TOKENS, "row_call_tokens_mismatch")
        _require(row.get("decisions") == EXPECTED_MAX_DECISIONS, "row_decisions_mismatch")
        _require(row.get("model_calls") == EXPECTED_MAX_DECISIONS, "row_model_calls_mismatch")
    return normalized


def audit_payload(payload: dict[str, Any], tasks: dict[str, BenchmarkTask]) -> dict[str, Any]:
    rows = _validate_payload_contract(payload)
    _require(set(tasks) >= set(HOLDOUT_IDS), "public_holdout_tasks_missing")

    config_by_task: dict[str, set[object]] = defaultdict(set)
    seed_by_task: dict[str, set[object]] = defaultdict(set)
    model_by_task: dict[str, set[object]] = defaultdict(set)
    fingerprint_by_task: dict[str, set[object]] = defaultdict(set)
    audited_rows: list[dict[str, Any]] = []
    grouped: dict[str, list[dict[str, Any]]] = {condition: [] for condition in CONDITIONS}

    for row in rows:
        task_id = str(row["task_id"])
        condition = str(row["condition"])
        config_by_task[task_id].add(row.get("config_hash"))
        seed_by_task[task_id].add(row.get("seed"))
        model_by_task[task_id].add(row.get("model"))
        fingerprint_by_task[task_id].add(row.get("task_fingerprint"))
        candidate, candidate_source = _candidate_from_row(row)
        final_status = _final_verification_status(row)
        termination_reason = _nonempty_string(row.get("termination_reason")) or ""
        self_termination = termination_reason == "verification_supported" and final_status == "supported"
        external = _score_candidate(tasks[task_id], candidate, str(row.get("model", "offline"))) if candidate is not None else None
        audited = {
            "task_id": task_id,
            "condition": condition,
            "condition_label": CONDITION_LABELS[condition],
            "candidate_answer": candidate,
            "candidate_source": candidate_source,
            "candidate_available": candidate is not None,
            "final_verification_status": final_status,
            "operator_sequence": _operator_sequence(row),
            "recovery_attempted": bool(row.get("recovery_attempted", False)),
            "recovered": bool(row.get("recovered", False)),
            "decisions": row.get("decisions"),
            "termination_reason": termination_reason,
            "vm_valid": bool(row.get("vm_valid", False)),
            "failure_category": row.get("failure_category"),
            "self_termination_success": self_termination,
            "external": external,
        }
        audited_rows.append(audited)
        grouped[condition].append(audited)

    for values in (config_by_task, seed_by_task, model_by_task, fingerprint_by_task):
        _require(all(len(items) == 1 for items in values.values()), "paired_run_metadata_mismatch")

    condition_metrics: dict[str, dict[str, Any]] = {}
    for condition, condition_rows in grouped.items():
        complete_candidates = all(row["candidate_available"] for row in condition_rows)
        external_scores = [row["external"]["score"] for row in condition_rows if row["external"] is not None]
        external_accuracy = round(sum(external_scores) / len(external_scores), 6) if complete_candidates else None
        self_successes = sum(int(row["self_termination_success"]) for row in condition_rows)
        condition_metrics[CONDITION_LABELS[condition]] = {
            "task_ids": [row["task_id"] for row in condition_rows],
            "candidate_coverage": f"{sum(int(row['candidate_available']) for row in condition_rows)}/{len(condition_rows)}",
            "candidate_complete": complete_candidates,
            "external_accuracy": external_accuracy,
            "self_termination_rate": round(self_successes / len(condition_rows), 6),
            "self_termination_supported": f"{self_successes}/{len(condition_rows)}",
            "recovery_attempts": sum(int(row["recovery_attempted"]) for row in condition_rows),
            "recovery_completed": sum(int(row["recovered"]) for row in condition_rows),
            "mean_decisions": round(sum(int(row["decisions"]) for row in condition_rows) / len(condition_rows), 6),
        }

    b_metrics = condition_metrics["B_fixed_executive"]
    c_metrics = condition_metrics["C_endogenous_executive"]
    if b_metrics["external_accuracy"] is not None and c_metrics["external_accuracy"] is not None:
        ecg_task = round(c_metrics["external_accuracy"] - b_metrics["external_accuracy"], 6)
    else:
        ecg_task = None
    ecg_self = round(c_metrics["self_termination_rate"] - b_metrics["self_termination_rate"], 6)
    candidate_count = sum(int(row["candidate_available"]) for row in audited_rows)
    decision = "AUDIT_INCONCLUSIVE_MISSING_CANDIDATE_ANSWER" if candidate_count < len(audited_rows) else "AUDIT_COMPLETE"
    return {
        "schema_version": 1,
        "protocol": PROTOCOL,
        "scientific_use": "offline_audit",
        "contract_valid": True,
        "new_model_calls": 0,
        "new_seeds": 0,
        "new_tuning": False,
        "candidate_policy": "only_explicit_serialized_candidate_answer; no inference from candidate_present",
        "decision": decision,
        "metrics": {
            "B_fixed_executive": b_metrics,
            "C_endogenous_executive": c_metrics,
            "ecg_task_C_minus_B": ecg_task,
            "ecg_self_C_minus_B": ecg_self,
        },
        "rows": audited_rows,
    }


def _cell(value: object) -> str:
    if value is None:
        return "null"
    return str(value)


def render_markdown(audit: dict[str, Any], source_name: str) -> str:
    metrics = audit["metrics"]
    lines = [
        "# Auditoria offline do Genesis v2-FINAL",
        "",
        f"Fonte: `{source_name}`. Nenhuma chamada nova ao modelo foi realizada.",
        "",
        f"**Decisão da auditoria:** `{audit['decision']}`.",
        "",
        "A auditoria considera apenas `candidate_answer` explicitamente serializado. A presença de `candidate_present=True` não é tratada como conteúdo de resposta. Quando o candidato não está disponível, a acurácia externa e `ECG-task` permanecem `null`, e não são convertidos em zero.",
        "",
        "## Quadro principal",
        "",
        "| Métrica | B — controlador fixo | C — executivo endógeno |",
        "|---|---:|---:|",
        f"| Cobertura de candidate explícito | {metrics['B_fixed_executive']['candidate_coverage']} | {metrics['C_endogenous_executive']['candidate_coverage']} |",
        f"| External accuracy no último candidate | {_cell(metrics['B_fixed_executive']['external_accuracy'])} | {_cell(metrics['C_endogenous_executive']['external_accuracy'])} |",
        f"| Self-termination supported | {metrics['B_fixed_executive']['self_termination_supported']} | {metrics['C_endogenous_executive']['self_termination_supported']} |",
        f"| Recovery attempts | {metrics['B_fixed_executive']['recovery_attempts']} | {metrics['C_endogenous_executive']['recovery_attempts']} |",
        f"| Recovery completed | {metrics['B_fixed_executive']['recovery_completed']} | {metrics['C_endogenous_executive']['recovery_completed']} |",
        f"| Média de decisões | {metrics['B_fixed_executive']['mean_decisions']} | {metrics['C_endogenous_executive']['mean_decisions']} |",
        "",
        "| Delta independente | Valor |",
        "|---|---:|",
        f"| ECG-task (C − B) | {_cell(metrics['ecg_task_C_minus_B'])} |",
        f"| ECG-self (C − B) | {_cell(metrics['ecg_self_C_minus_B'])} |",
        "",
        "## Linhas auditadas",
        "",
        "| Condição | Tarefa | Candidate | Verificação final | Operadores | Recovery | Término |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in audit["rows"]:
        lines.append(
            "| {condition_label} | {task_id} | {candidate} | {status} | {operators} | {recovery} | {termination} |".format(
                condition_label=row["condition_label"],
                task_id=row["task_id"],
                candidate="ausente" if not row["candidate_available"] else row["candidate_answer"],
                status=row["final_verification_status"] or "vazio",
                operators=" → ".join(row["operator_sequence"]),
                recovery=f"tentada={row['recovery_attempted']}; completa={row['recovered']}",
                termination=row["termination_reason"],
            )
        )
    lines.extend(
        [
            "",
            "## Interpretação",
            "",
            "O resultado de `ECG-self` mede somente a taxa de término com `verification_supported` e não mede acurácia da tarefa. `ECG-task` só é calculado quando os dois holdouts de B e os dois holdouts de C possuem candidate explícito. Portanto, ausência de candidate serializado é uma limitação de observabilidade, não um resultado negativo de capacidade.",
            "",
            "A auditoria não autoriza uma nova execução, não modifica prompts, não altera seeds e não acessa benchmark privado. Se a fonte não contiver os candidatos, a decisão científica permanece inconclusiva quanto a `C>B` externamente.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Auditoria offline dos traces Genesis v2-FINAL.")
    parser.add_argument("--input", type=Path, required=True, help="JSON bruto da execução v2-FINAL")
    parser.add_argument("--output-dir", type=Path, default=Path("data/artifacts/research/genesis_v2final_audit"))
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    _require(isinstance(payload, dict), "payload_must_be_object")
    audit = audit_payload(payload, _load_public_tasks(args.repo_root.resolve()))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "genesis_v2final_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "genesis_v2final_audit.md").write_text(render_markdown(audit, args.input.name), encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
