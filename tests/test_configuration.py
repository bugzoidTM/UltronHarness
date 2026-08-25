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


def test_life_remains_disabled_without_profile(monkeypatch) -> None:
    monkeypatch.delenv("ULTRON_LIFE_PROFILE", raising=False)
    settings = load_settings()
    assert settings.raw["life"]["enabled"] is False
    assert all(value is False for value in settings.raw["life"]["feature_flags"].values())


def test_life_full_profile_enables_all_independent_flags(monkeypatch) -> None:
    monkeypatch.setenv("ULTRON_LIFE_PROFILE", "full")
    settings = load_settings()
    assert settings.raw["life"]["enabled"] is True
    assert all(value is True for value in settings.raw["life"]["feature_flags"].values())


def test_unknown_life_profile_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("ULTRON_LIFE_PROFILE", "unbounded")
    with pytest.raises(ValueError, match="Perfil LIFE desconhecido"):
        load_settings()


def test_unknown_cognition_profile_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("ULTRON_COGNITION_PROFILE", "all-the-things")
    with pytest.raises(ValueError, match="Perfil cognitivo desconhecido"):
        load_settings()
