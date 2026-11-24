"""Check the agreement math on tiny examples worked out by hand. No API calls, no files."""

import pytest

from evals.judge_agreement import agreement_metrics


def test_hand_worked_example():
    # (human, judge): 2 both yes, 1 both no, 1 judge too strict, 1 judge too lenient
    pairs = [(True, True), (True, True), (True, False), (False, False), (False, True)]
    m = agreement_metrics(pairs)

    assert m["both_yes"] == 2
    assert m["both_no"] == 1
    assert m["judge_strict"] == 1
    assert m["judge_lenient"] == 1
    assert m["agreement"] == pytest.approx(3 / 5)     # 3 of 5 agree
    assert m["tpr"] == pytest.approx(2 / 3)           # I said yes 3 times, judge agreed 2
    assert m["tnr"] == pytest.approx(1 / 2)           # I said no 2 times, judge agreed 1
    # chance = 0.6*0.6 + 0.4*0.4 = 0.52 ; kappa = (0.6 - 0.52) / (1 - 0.52)
    assert m["kappa"] == pytest.approx(0.08 / 0.48)


def test_perfect_agreement_gives_kappa_1():
    pairs = [(True, True), (False, False), (True, True), (False, False)]
    m = agreement_metrics(pairs)
    assert m["agreement"] == 1
    assert m["kappa"] == pytest.approx(1)


def test_no_human_no_labels_gives_tnr_none():
    # I never said "no", so TNR can't be computed: None, not a crash
    pairs = [(True, True), (True, False)]
    m = agreement_metrics(pairs)
    assert m["tnr"] is None
