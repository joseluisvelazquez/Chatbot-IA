import pytest
from app.core.intents import detect_intent
from app.core.states import ChatState


def test_affirmative_simple():
    result = detect_intent("sí", ChatState.CONFIRMAR_NOMBRE)
    assert result == "affirmative"


def test_negative_simple():
    result = detect_intent("no", ChatState.CONFIRMAR_NOMBRE)
    assert result == "negative"


def test_majority_binary_affirmative():
    result = detect_intent("si no si", ChatState.CONFIRMAR_NOMBRE)
    assert result == "affirmative"


def test_majority_binary_negative():
    result = detect_intent("no si no", ChatState.CONFIRMAR_NOMBRE)
    assert result == "negative"


def test_ambiguous_binary():
    result = detect_intent("si no", ChatState.CONFIRMAR_NOMBRE)
    assert result == "ambiguous"


def test_general_last_intent():
    result = detect_intent("quiero hablar con asesor pero si", ChatState.INICIO)
    assert result == "affirmative"


def test_no_match():
    result = detect_intent("abcdefg", ChatState.INICIO)
    assert result == "other"
