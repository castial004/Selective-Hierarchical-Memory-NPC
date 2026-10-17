"""Tests proving the blind dataset leaks no answer or method information.

The blind export exists so independent annotators (LLMs or humans) can judge cases
without any route to the expected answer. These tests are the guarantee: an
auditor with a deliberately broken payload must catch every leak class, and the
shipped blind_cases.json must audit clean.

If a future change re-introduces a label, a method name, an original case id, a
score, or an engine feature channel, these tests fail.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from npc_memory_project.evaluation.blind_export import (
    BLIND_SCHEMA, FORBIDDEN_KEYS, anonymise_case_id, audit_blind_payload,
    build_blind_payload,
)
from npc_memory_project.evaluation.labelled import author_labelled_cases

REPO_ROOT = Path(__file__).resolve().parents[1]
BLIND = REPO_ROOT / "evaluation_data" / "blind_cases.json"


@pytest.fixture(scope="module")
def payload():
    return build_blind_payload()


# ------------------------------------------------------- the shipped file is clean
def test_shipped_blind_file_audits_clean():
    data = json.loads(BLIND.read_text(encoding="utf-8"))
    assert data["schema"] == BLIND_SCHEMA
    assert audit_blind_payload(data) == []


def test_built_payload_audits_clean(payload):
    assert audit_blind_payload(payload) == []


def test_no_labels_anywhere_in_the_serialized_file():
    text = BLIND.read_text(encoding="utf-8").lower()
    for banned in ("expected_family", "expected_actions", "author_label",
                   "adjudicated_family", "rationale", "label_source",
                   "selected_action", "action_scores", "feature_key"):
        assert banned not in text, f"blind file leaks {banned!r}"


def test_no_method_names_anywhere():
    text = BLIND.read_text(encoding="utf-8").lower()
    for method in ("recency-only", "importance-only", "status-aware",
                   "tiers, status-blind", "shm (this architecture)"):
        assert method not in text, f"blind file leaks method {method!r}"


def test_no_original_case_ids_leak():
    text = BLIND.read_text(encoding="utf-8").lower()
    for case in author_labelled_cases():
        assert case.case_id.lower() not in text, f"leaked original id {case.case_id}"


def test_every_original_case_is_present_under_an_anonymous_id(payload):
    originals = author_labelled_cases()
    assert len(payload["cases"]) == len(originals)
    ids = [c["case_id"] for c in payload["cases"]]
    # ids are the anonymous sequence, in the (shuffled) blind order
    assert ids == [anonymise_case_id(i) for i in range(len(originals))]
    assert len(set(ids)) == len(ids)


def test_blind_order_does_not_mirror_source_order(payload):
    """Position must not reveal which source case a blind case is."""
    blind = [(c["world"]["game_day"], c["world"]["location"], c["npc"]["role"],
              len(c["memories"])) for c in payload["cases"]]
    source = [(c.world.game_day, c.world.location, c.npc.role, len(c.memories))
              for c in author_labelled_cases()]
    assert blind != source, (
        "blind case order matches source order -- a rater who has seen the "
        "repository could map ids back by position"
    )


def test_shuffle_is_reproducible():
    a = build_blind_payload()
    b = build_blind_payload()
    assert [c["case_id"] for c in a["cases"]] == [c["case_id"] for c in b["cases"]]
    assert [c["npc"]["role"] for c in a["cases"]] == [c["npc"]["role"] for c in b["cases"]]


# ------------------------------------------------------- structure is sufficient
def test_blind_cases_keep_what_a_rater_needs(payload):
    for case in payload["cases"]:
        assert case["action_menu"], f"{case['case_id']} has no action menu"
        assert set(case["npc"]) >= {"npc_id", "role", "trust", "personality", "inventory"}
        assert set(case["world"]) >= {"game_day", "location", "player_has_money"}
        for mem in case["memories"]:
            assert set(mem) >= {"event_id", "summary", "tier", "status",
                                "importance", "confidence", "source"}


def test_decisive_memory_citation_is_possible(payload):
    """A rater must be able to cite decisive ids, so ids exist and are unique."""
    for case in payload["cases"]:
        ids = [m["event_id"] for m in case["memories"]]
        assert len(ids) == len(set(ids)), f"{case['case_id']} has duplicate ids"


def test_engine_feature_channel_is_stripped_but_provenance_kept(payload):
    for case in payload["cases"]:
        for mem in case["memories"]:
            assert "feature_key" not in mem["metadata"]
    # provenance must survive somewhere in the dataset
    metas = [m["metadata"] for c in payload["cases"] for m in c["memories"]]
    assert any("claim" in m or "conflict_key" in m or "source_chain" in m for m in metas)


# --------------------------------------------- the auditor must CATCH leaks
def _mutations():
    def add_key(key, value):
        def f(p):
            p["cases"][0][key] = value
        return f

    def add_memory(text):
        def f(p):
            p["cases"][1]["memories"].append({
                "event_id": "inject", "summary": text, "event_type": "x",
                "game_day": 1, "tier": "working", "status": "active",
                "importance": 0.1, "confidence": 0.5, "source": "x", "metadata": {},
            })
        return f

    return [
        ("expected_family", add_key("expected_family", "warm")),
        ("author_label", add_key("author_label", {"expected_family": "warm"})),
        ("rationale", add_key("rationale", "serve the customer")),
        ("selected_action", add_key("selected_action", "trade")),
        ("action_scores", add_key("action_scores", [{"action": "trade", "score": 0.9}])),
        ("method in summary", add_memory("shm (this architecture) decided this")),
        ("label_source top-level", lambda p: p.__setitem__("label_source", "author")),
        ("feature_key", lambda p: p["cases"][1]["memories"][0]["metadata"].__setitem__("feature_key", "theft")),
        ("original case id", lambda p: p["cases"][0].__setitem__("case_id", "fresh-npc-no-history")),
        ("empty menu", lambda p: p["cases"][0].__setitem__("action_menu", [])),
        ("duplicate ids", lambda p: p["cases"][1]["memories"].append(
            dict(p["cases"][1]["memories"][0]))),
    ]


@pytest.mark.parametrize("label,mutate", _mutations())
def test_auditor_catches_each_leak_class(payload, label, mutate):
    broken = copy.deepcopy(payload)
    mutate(broken)
    leaks = audit_blind_payload(broken)
    assert leaks, f"auditor MISSED leak class: {label}"


def test_auditor_does_not_flag_the_clean_payload(payload):
    """Guard against an over-eager auditor that fails everything."""
    assert audit_blind_payload(copy.deepcopy(payload)) == []
