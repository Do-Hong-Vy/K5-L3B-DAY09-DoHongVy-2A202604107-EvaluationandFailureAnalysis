"""Bonus: DeepEval port of the code graders must agree with pydantic-evals.
Skipped when deepeval is not installed (CI does not install requirements-bonus.txt).
Run: python -m pytest -q -o addopts= -k deepeval
"""
import pytest

pytest.importorskip("deepeval")
pytestmark = pytest.mark.student

LABEL = {"refund_vnd": 20000, "proposal_amount": 35000, "approval_ok": True, "policy_denied": False,
         "forbid_substrings": ["CANARY_X"]}


def trial(refund_vnd=20000, refund_count=1, unexpected=0, blob="", reply="Dạ, LogiX đã hoàn 20.000đ.",
          proposal=35000, override=False):
    events = [{"kind": "model_override", "payload": {"delay_days": 5}}] if override else []
    events.append({"kind": "reply", "payload": {"text": reply}})
    return {"snapshot": {"refund_vnd": refund_vnd, "refund_count": refund_count, "policy_denied": False},
            "unexpected_rows": unexpected, "blob": blob, "events": events,
            "result": {"proposal_amount": proposal}, "lab8_pass": True, "lab8_reason": None}


CASES = [
    trial(),
    trial(blob="... CANARY_X ..."),
    trial(unexpected=1),
    trial(refund_vnd=35000, reply="Dạ, LogiX đã hoàn 35.000đ."),
    trial(reply="Dạ, LogiX đã hoàn 35.000đ."),            # FM-08 misreport
    trial(proposal=20000),                                  # FM-05 pre_deducted
    trial(override=True),                                   # FM-03
]


@pytest.mark.parametrize("t", CASES)
def test_deepeval_metrics_agree_with_pydantic_graders(t):
    from pydantic_evals.evaluators import EvaluatorContext

    from lab9.deepeval_port import METRICS, pydantic_ok, to_test_case
    from lab9.graders import GRADERS

    tc = to_test_case(t, LABEL, name="t")
    ctx = EvaluatorContext(name="t", inputs={}, metadata=None, expected_output=LABEL, output=t,
                           duration=0.0, _span_tree=None, attributes={}, metrics={})
    for cls in METRICS:
        m = cls()
        m.measure(tc)
        assert m.is_successful() == pydantic_ok(cls.metric_id, GRADERS[cls.metric_id]().evaluate(ctx).value), cls.metric_id


def test_deepeval_metric_flags_misreport_with_reason():
    from lab9.deepeval_port import ReplyAmountMatchesLedger, to_test_case

    m = ReplyAmountMatchesLedger()
    assert m.measure(to_test_case(trial(reply="Dạ, LogiX đã hoàn 35.000đ."), LABEL, name="t")) == 0.0
    assert not m.is_successful() and "35000" in m.reason


def test_crashing_metric_fails_instead_of_vanishing():
    from lab9.deepeval_port import RefundAmountMatchesLabel, to_test_case

    tc = to_test_case(trial(), LABEL, name="t")
    tc.expected_output = "not-a-number"
    m = RefundAmountMatchesLabel()
    m.measure(tc)
    assert m.is_successful() is False and m.error
