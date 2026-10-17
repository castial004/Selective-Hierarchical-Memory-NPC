"""Tests for the blind judge runner.

These run fully offline: a fake transport returns canned replies, so the prompt
construction, JSON extraction, validation and tagging are all exercised without a
network or an API key. One test proves the prompt sent to a judge contains no
answer information.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from npc_memory_project.evaluation.blind_export import audit_blind_payload
from npc_memory_project.evaluation.llm_runner import (
    JudgeError, build_prompt, extract_json, load_blind_cases, load_prompt,
    run_judge,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA = REPO_ROOT / "evaluation_data"
FENCE = chr(96) * 3          # three backticks, built to keep this file quote-safe


def _blind_cases():
    return load_blind_cases(DATA / "blind_cases.json")


def _valid_reply(cases, evaluator_id="judge-test-01") -> str:
    """A synthetic reply that passes validation, built from the blind cases."""
    out = {"evaluator_id": evaluator_id, "cases": []}
    for case in cases["cases"]:
        menu = case["action_menu"]
        preferred = menu[0]
        mems = [m["event_id"] for m in case["memories"][:1]]
        out["cases"].append({
            "case_id": case["case_id"],
            "acceptable_actions": [preferred],
            "preferred_action": preferred,
            "action_family": "warm",
            "punitive_action_acceptable": False,
            "decisive_memory_ids": mems,
            "contradiction_present": False,
            "contradiction_summary": None,
            "confidence": 0.7,
            "rationale": "Synthetic fixture for the runner test only.",
        })
    return json.dumps(out)


# ------------------------------------------------------------- prompt safety
def test_prompt_keeps_its_placeholders():
    text = load_prompt(DATA / "evaluator_prompt.md")
    assert "{{EVALUATOR_ID}}" in text
    assert "{{EVALUATION_CASES_JSON}}" in text


def test_built_prompt_reveals_no_answer_information():
    """The prompt handed to a judge must be as clean as the blind cases.

    The template itself contains an example output-format JSON block (with
    placeholder text like <action>), so we cannot parse "the" JSON out of the
    prompt. Instead we check the two things that matter: no unfilled
    placeholders remain, and no answer/method vocabulary appears anywhere in the
    full prompt string.
    """
    cases = _blind_cases()
    prompt = build_prompt(load_prompt(DATA / "evaluator_prompt.md"),
                          "judge-test-01", cases)
    assert prompt.count("{{") == 0, "unfilled placeholder left in the prompt"
    low = prompt.lower()
    for banned in ("expected_family", "expected_actions", "author_label",
                   "adjudicated_family", "selected_action", "action_scores",
                   "feature_key", "recency-only", "importance-only",
                   "status-aware", "shm (this architecture)"):
        assert banned not in low, "prompt leaks " + repr(banned)

    # every original (answer-revealing) case id must be absent too
    from npc_memory_project.evaluation.labelled import author_labelled_cases
    for case in author_labelled_cases():
        assert case.case_id.lower() not in low, "prompt leaks id " + case.case_id

    # and the cases payload embedded in the prompt audits clean
    assert audit_blind_payload(cases) == []


# ------------------------------------------------------------ json extraction
def test_extract_json_plain():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_from_fenced_prose():
    text = "Sure!\n\n" + FENCE + "json\n{\"a\": 2}\n" + FENCE + "\n"
    assert extract_json(text) == {"a": 2}


def test_extract_json_rejects_garbage():
    with pytest.raises(JudgeError):
        extract_json("no json here")


# -------------------------------------------------------------- runner flow
def test_run_judge_validates_and_tags():
    cases = _blind_cases()
    reply = _valid_reply(cases)

    def fake(endpoint, api_key, model, prompt):
        assert "case-001" in prompt
        return reply

    run = run_judge(evaluator_id="judge-test-01", model="fake-1",
                    endpoint="http://fake", transport=fake,
                    prompt_path=DATA / "evaluator_prompt.md",
                    blind_path=DATA / "blind_cases.json")
    assert run.labels["annotator_type"] == "llm_blind"
    assert run.labels["blind"] is True
    assert run.labels["ground_truth"] is False
    assert "not human ground truth" in run.labels["note"].lower()
    assert len(run.labels["cases"]) == len(cases["cases"])


def test_run_judge_rejects_invalid_annotation():
    """An action outside the menu must fail validation, not be saved."""
    cases = _blind_cases()
    bad = json.loads(_valid_reply(cases))
    bad["cases"][0]["acceptable_actions"] = ["arrest_player"]
    bad["cases"][0]["preferred_action"] = "arrest_player"

    def fake(endpoint, api_key, model, prompt):
        return json.dumps(bad)

    with pytest.raises(SystemExit):
        run_judge(evaluator_id="judge-test-01", model="fake-1",
                  endpoint="http://fake", transport=fake,
                  prompt_path=DATA / "evaluator_prompt.md",
                  blind_path=DATA / "blind_cases.json")


def test_run_judge_rejects_empty_reply():
    def fake(endpoint, api_key, model, prompt):
        return ""

    with pytest.raises(JudgeError):
        run_judge(evaluator_id="judge-test-01", model="fake-1",
                  endpoint="http://fake", transport=fake,
                  prompt_path=DATA / "evaluator_prompt.md",
                  blind_path=DATA / "blind_cases.json")


def test_run_judge_never_fabricates_on_transport_failure():
    def boom(endpoint, api_key, model, prompt):
        raise JudgeError("no credentials")

    with pytest.raises(JudgeError):
        run_judge(evaluator_id="judge-test-01", model="fake-1",
                  endpoint="http://fake", transport=boom,
                  prompt_path=DATA / "evaluator_prompt.md",
                  blind_path=DATA / "blind_cases.json")


def test_http_transport_requires_credentials_when_no_key():
    """With no key the real transport still raises rather than inventing data."""
    from npc_memory_project.evaluation.llm_runner import http_transport
    with pytest.raises(JudgeError):
        http_transport("http://127.0.0.1:9/v1/chat/completions", "", "m",
                       "prompt", timeout=1)
