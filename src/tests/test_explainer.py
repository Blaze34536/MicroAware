import json

from microaware import explainer

ALERT = {"id": "A-0001", "source": "fan_a", "kind": "machine_anomaly", "label": None, "label_conf": None,
         "evidence": {"score": 80.1, "threshold": 1.8, "top_bands": [{"band_hz": "2902-3189", "delta_db": 24.7}]}}


def good_llm(prompt):
    return json.dumps({"spoken": "Fan A has a new high-pitched tone.", "cause": "Possible bearing wear.",
                       "checks": ["a", "b", "c"], "confidence": "medium"})


def test_uses_llm_answer_when_valid():
    out = explainer.explain(dict(ALERT, id="A-1"), llm=good_llm)
    assert out["spoken"] == "Fan A has a new high-pitched tone." and out["source"] == "llm"


def test_falls_back_to_canned_on_bad_json_or_error():
    def boom(prompt):
        raise TimeoutError

    for llm in (lambda p: "not json", lambda p: json.dumps({"spoken": "x"}), boom):
        out = explainer.explain(dict(ALERT, id="A-2"), llm=llm)
        assert out["source"] == "canned" and len(out["checks"]) == 3
        explainer._cache.clear()


def test_canned_unknown_anomaly_says_unknown_and_names_the_band():
    out = explainer.explain(dict(ALERT, id="A-3"), llm=None)
    assert "unknown" in out["spoken"].lower() and "3.0 kilohertz" in out["spoken"]


def test_explains_each_alert_only_once():
    calls = []
    def counting(prompt):
        calls.append(prompt)
        return good_llm(prompt)

    explainer.explain(dict(ALERT, id="A-4"), llm=counting)
    explainer.explain(dict(ALERT, id="A-4"), llm=counting)
    assert len(calls) == 1


def test_prompt_contains_evidence_and_no_invention_rule():
    seen = []
    explainer.explain(dict(ALERT, id="A-5"), llm=lambda p: seen.append(p) or good_llm(p))
    assert "2902-3189" in seen[0] and "only the evidence" in seen[0].lower()
