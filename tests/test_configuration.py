from __future__ import annotations

import pytest

from ultron.configuration import load_settings


def test_cognition_flags_remain_off_without_development_profile(monkeypatch) -> None:
    monkeypatch.delenv("ULTRON_COGNITION_PROFILE", raising=False)
    settings = load_settings()
    flags = settings.cognition["feature_flags"]
    assert flags["epistemic_state"] is False
    assert flags["prediction_before_observation"] is False


def test_gr1_development_profile_enables_only_epistemic_state(monkeypatch) -> None:
    monkeypatch.setenv("ULTRON_COGNITION_PROFILE", "gr1")
    settings = load_settings()
    flags = settings.cognition["feature_flags"]
    assert flags["epistemic_state"] is True
    assert flags["prediction_before_observation"] is False


def test_gr1_gr2_development_profile_enables_two_independent_flags(monkeypatch) -> None:
    monkeypatch.setenv("ULTRON_COGNITION_PROFILE", "gr1-gr2")
    settings = load_settings()
    flags = settings.cognition["feature_flags"]
    assert flags["epistemic_state"] is True
    assert flags["prediction_before_observation"] is True


def test_unknown_cognition_profile_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("ULTRON_COGNITION_PROFILE", "all-the-things")
    with pytest.raises(ValueError, match="Perfil cognitivo desconhecido"):
        load_settings()
