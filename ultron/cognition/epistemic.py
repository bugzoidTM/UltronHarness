"""Estado epistêmico explícito e limitado ao escopo da missão Horizon."""

from __future__ import annotations

from typing import Any

from ultron.schemas import EpistemicClaim, EpistemicKind, EpistemicState


def initial_state(objective: str, observations: list[str] | None = None) -> EpistemicState:
    """Cria um estado sem promover objetivo, inferência ou hipótese a fato."""
    state = EpistemicState()
    if objective.strip():
        state = state.model_copy(update={"open_questions": [f"Como verificar: {objective.strip()}"]})
    for observation in observations or []:
        state = observe(state, observation, evidence_ref="frozen_orientation_snapshot")
    return state


def observe(state: EpistemicState, observation: str, *, evidence_ref: str | None = None) -> EpistemicState:
    """Registra somente o que foi observado como FACT, sem inferência automática."""
    text = observation.strip()
    if not text:
        return state
    claim = EpistemicClaim(
        kind=EpistemicKind.FACT,
        content=text[:2000],
        confidence=1.0,
        evidence_refs=[evidence_ref] if evidence_ref else [],
        source="observation",
    )
    facts = [*state.known_facts, claim][-20:]
    return state.model_copy(update={"known_facts": facts})


def record_unknown(state: EpistemicState, question: str, *, evidence_ref: str | None = None) -> EpistemicState:
    text = question.strip()
    if not text:
        return state
    claim = EpistemicClaim(
        kind=EpistemicKind.UNKNOWN,
        content=text[:1000],
        confidence=0.0,
        evidence_refs=[evidence_ref] if evidence_ref else [],
        source="state_update",
    )
    unknowns = [*state.unknowns, claim][-20:]
    return state.model_copy(update={"unknowns": unknowns})


def record_inference(state: EpistemicState, content: str, *, evidence_refs: list[str] | None = None, confidence: float = 0.5) -> EpistemicState:
    """Registra uma inferência em campo próprio; nunca a inclui em known_facts."""
    claim = EpistemicClaim(
        kind=EpistemicKind.INFERENCE,
        content=content.strip()[:2000],
        confidence=confidence,
        evidence_refs=[str(item) for item in (evidence_refs or [])],
        source="explicit_update",
    )
    derived = [*state.derived_facts, claim][-20:]
    return state.model_copy(update={"derived_facts": derived})


def record_assumption(state: EpistemicState, content: str, *, evidence_refs: list[str] | None = None) -> EpistemicState:
    claim = EpistemicClaim(
        kind=EpistemicKind.ASSUMPTION,
        content=content.strip()[:2000],
        confidence=0.5,
        evidence_refs=[str(item) for item in (evidence_refs or [])],
        source="explicit_update",
    )
    return state.model_copy(update={"assumptions": [*state.assumptions, claim][-20:]})


def record_hypothesis(state: EpistemicState, content: str, *, confidence: float = 0.5, evidence_for: list[str] | None = None, evidence_against: list[str] | None = None) -> EpistemicState:
    claim = EpistemicClaim(
        kind=EpistemicKind.HYPOTHESIS,
        content=content.strip()[:2000],
        confidence=confidence,
        evidence_refs=[],
        source="explicit_update",
    )
    key = claim.content
    confidences = dict(state.hypothesis_confidences)
    confidences[key] = confidence
    supporting = dict(state.evidence_for)
    opposing = dict(state.evidence_against)
    supporting[key] = [str(item) for item in (evidence_for or [])]
    opposing[key] = [str(item) for item in (evidence_against or [])]
    return state.model_copy(
        update={
            "hypotheses": [*state.hypotheses, claim][-10:],
            "hypothesis_confidences": confidences,
            "evidence_for": supporting,
            "evidence_against": opposing,
        }
    )


def update_from_observation(
    state: EpistemicState | None,
    *,
    objective: str,
    tool: str,
    output: str,
    ok: bool,
    verification_passed: bool,
    error: str | None,
    evidence_ref: str | None,
) -> EpistemicState:
    current = state or initial_state(objective)
    if ok:
        current = observe(current, f"{tool}: {output}".strip(), evidence_ref=evidence_ref)
    else:
        failure = f"{tool} falhou" + (f": {error.strip()}" if error and error.strip() else "")
        current = observe(current, failure, evidence_ref=evidence_ref)
        current = record_unknown(current, f"Se a condição de sucesso foi satisfeita após a falha de {tool}.", evidence_ref=evidence_ref)
    if ok and not verification_passed:
        current = record_unknown(current, f"Se a condição de verificação foi satisfeita para {tool}.", evidence_ref=evidence_ref)
    return current


def prompt_summary(state: EpistemicState | None, *, max_items: int = 5) -> dict[str, Any]:
    if state is None:
        return {"enabled": False}
    return {
        "enabled": True,
        "known_facts": [item.model_dump(mode="json") for item in state.known_facts[-max_items:]],
        "unknowns": [item.model_dump(mode="json") for item in state.unknowns[-max_items:]],
        "assumptions": [item.model_dump(mode="json") for item in state.assumptions[-max_items:]],
        "hypotheses": [item.model_dump(mode="json") for item in state.hypotheses[-max_items:]],
        "derived_facts": [item.model_dump(mode="json") for item in state.derived_facts[-max_items:]],
        "contradictions": state.contradictions[-max_items:],
        "constraints": state.constraints[-max_items:],
        "open_questions": state.open_questions[-max_items:],
        "failed_hypotheses": state.failed_hypotheses[-max_items:],
        "active_strategy": state.active_strategy,
        "candidate_strategies": state.candidate_strategies[-max_items:],
        "hypothesis_confidences": dict(list(state.hypothesis_confidences.items())[-max_items:]),
        "evidence_for": {key: value[-max_items:] for key, value in list(state.evidence_for.items())[-max_items:]},
        "evidence_against": {key: value[-max_items:] for key, value in list(state.evidence_against.items())[-max_items:]},
    }
