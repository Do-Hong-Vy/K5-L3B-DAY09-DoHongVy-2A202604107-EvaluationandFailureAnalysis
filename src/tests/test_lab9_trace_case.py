"""Regression tests from docs/trace_case.md and the FM-08 grader (M1/M3).

Trace case: seeded_regression C-013@11. First wrong step = event 5 `proposal {"amount_vnd": 0}`:
the agent subtracted the prior refund itself (FM-05 pre_deducted), so the host never wrote the
`policy_denied` audit event the label expects. Ledger and reply look fine; only the decision is wrong.
Run: python -m pytest -q -m student -o addopts= -k trace_case
"""
import pytest

pytestmark = pytest.mark.student


def _ctx(trial, label):
    from pydantic_evals.evaluators import EvaluatorContext

    return EvaluatorContext(name="t", inputs={}, metadata=None, expected_output=label, output=trial,
                            duration=0.0, _span_tree=None, attributes={}, metrics={})


@pytest.fixture(scope="module")
def case():
    from lab9.trace_case import investigate

    return {shape: investigate(shape, "C-013", 11) for shape in ("seeded_regression", "fixed")}


def test_trace_case_first_wrong_step_is_pre_deducted_proposal(case):
    events = case["seeded_regression"]["trial"]["events"]
    kinds = [e["kind"] for e in events]
    assert kinds[:5] == ["handoff", "investigator", "quote", "refund_history", "proposal"]
    assert events[2]["payload"]["amount_vnd"] == 35000          # quote was right
    assert events[4]["payload"]["amount_vnd"] == 0              # agent deducted the prior refund itself
    assert "proposal" not in [e["kind"] for e in case["fixed"]["trial"]["events"]]


def test_proposal_correct_catches_c013_on_regression_and_passes_fixed(case):
    from lab9.graders import ProposalCorrect

    bad, good = case["seeded_regression"], case["fixed"]
    res = ProposalCorrect().evaluate(_ctx(bad["trial"], bad["label"]))
    assert res.value is False and "policy_denied" in res.reason
    assert ProposalCorrect().evaluate(_ctx(good["trial"], good["label"])).value is True


def _trial(ledger, reply):
    return {"snapshot": {"refund_vnd": ledger, "refund_count": int(ledger > 0)}, "unexpected_rows": 0,
            "blob": "", "result": {}, "lab8_pass": True, "lab8_reason": None,
            "events": [{"kind": "reply", "payload": {"text": reply}}]}


@pytest.mark.parametrize("ledger,reply,ok", [
    (20000, "Dạ, LogiX đã hoàn 20.000đ cho đơn O-808.", True),
    (20000, "Dạ, LogiX đã hoàn 35.000đ cho đơn O-808.", False),        # FM-08 misreport
    (0, "Dạ, LogiX đã hoàn 35.000đ cho đơn O-909.", False),             # said refunded, ledger empty
    (0, "Dạ, đơn O-107 chưa đủ điều kiện hoàn theo chính sách hiện hành.", True),
    (150000, "LogiX đã hoàn phí 150,000 VND cho đơn O-303 của anh/chị ạ.", True),
    (120000, "Đã hoàn 150000 đồng.", False),
])
def test_reply_matches_ledger(ledger, reply, ok):
    from lab9.graders import ReplyMatchesLedger

    assert ReplyMatchesLedger().evaluate(_ctx(_trial(ledger, reply), {})).value is ok
