"""Test di validazione per il motore di calcolo psicometrico deterministico (STEP 4)."""

import pytest
from app.services.scoring.engine import (
    PsychometricScoringEngine,
    ScoringError,
    calculate_inverted_value,
    get_bdi2_definition,
    get_stai_y1_definition,
)


def test_calculate_inverted_value():
    """Verifica l'inversione psicometrica standard: min + max - val."""
    # Scala 1-4 (es. STAI)
    assert calculate_inverted_value(1, 1, 4) == 4
    assert calculate_inverted_value(2, 1, 4) == 3
    assert calculate_inverted_value(3, 1, 4) == 2
    assert calculate_inverted_value(4, 1, 4) == 1

    # Scala 0-3
    assert calculate_inverted_value(0, 0, 3) == 3
    assert calculate_inverted_value(3, 0, 3) == 0

    with pytest.raises(ScoringError):
        calculate_inverted_value(5, 1, 4)


def test_bdi2_scoring_benchmarks():
    """Verifica lo scoring deterministico del BDI-II rispetto ai cut-off ufficiali."""
    schema, rules = get_bdi2_definition()

    # Caso 1: Tutte risposte a zero -> Minima depressione (Punteggio 0)
    zero_answers = {f"bdi_{i}": 0 for i in range(1, 22)}
    res_zero = PsychometricScoringEngine.score_test(schema, rules, zero_answers)
    assert res_zero["raw_scores"]["total"] == 0
    assert res_zero["clinical_cutoffs"]["severity"] == "MINIMA"
    assert res_zero["subscales"]["cognitiva"] == 0
    assert res_zero["subscales"]["somatico_affettiva"] == 0

    # Caso 2: Punteggio moderato (24 punti)
    # 10 item cognitivi a 1 (=10), 7 item somatici a 2 (=14) -> totale 24
    mod_answers = {}
    for i in range(1, 11):
        mod_answers[f"bdi_{i}"] = 1
    for i in range(11, 18):
        mod_answers[f"bdi_{i}"] = 2
    for i in range(18, 22):
        mod_answers[f"bdi_{i}"] = 0

    res_mod = PsychometricScoringEngine.score_test(schema, rules, mod_answers)
    assert res_mod["raw_scores"]["total"] == 24
    assert res_mod["clinical_cutoffs"]["severity"] == "MODERATA"
    assert "20-28" in res_mod["clinical_cutoffs"]["description"]

    # Caso 3: Risposta mancante -> solleva ScoringError
    incomplete = {f"bdi_{i}": 0 for i in range(1, 20)}
    with pytest.raises(ScoringError):
        PsychometricScoringEngine.score_test(schema, rules, incomplete)


def test_stai_y1_scoring_with_inversions():
    """Verifica lo scoring dello STAI-Y1 con 10 item invertiti."""
    schema, rules = get_stai_y1_definition()

    # Se tutti gli item sono risposti con valore 1:
    # I 10 item normali valgono 1.
    # I 10 item invertiti (1, 2, 5, 8, 10, 11, 15, 16, 19, 20) vengono invertiti a 4!
    # Totale = (10 * 1) + (10 * 4) = 10 + 40 = 50.
    answers_all_one = {f"stai_{i}": 1 for i in range(1, 21)}
    res = PsychometricScoringEngine.score_test(schema, rules, answers_all_one)
    assert res["raw_scores"]["total"] == 50
    assert res["clinical_cutoffs"]["severity"] == "MODERATA"
