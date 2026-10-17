"""Tests for the dataset-separation guard and annotation validator.

The human-evaluation protocol keeps human and LLM labels in separate files so no
reader can mistake an LLM set for human ground truth. These tests enforce that
separation and validate the shipped llm_labels.json.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from npc_memory_project.evaluation.annotation import (
    ANNOTATOR_TYPES, check_dataset_purity, dataset_kind, validate_annotations,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA = REPO_ROOT / "evaluation_data"


def test_dataset_kind_reads_annotator_type_then_label_source():
    assert dataset_kind({"annotator_type": "human"}) == "human"
    assert dataset_kind({"label_source": "author"}) == "author"
    assert dataset_kind({}) == "unknown"


def test_mixing_human_and_llm_is_refused():
    human = {"annotator_type": "human", "cases": []}
    llm = {"annotator_type": "llm_repo_aware", "cases": []}
    with pytest.raises(SystemExit) as exc:
        check_dataset_purity([("h.json", human), ("l.json", llm)])
    assert "refusing to mix" in str(exc.value).lower()


def test_single_kind_passes_purity():
    llm = {"annotator_type": "llm_repo_aware", "cases": []}
    result = check_dataset_purity([("a.json", llm), ("b.json", llm)])
    assert result["kind"] == "llm_repo_aware"
    assert result["files"] == ["a.json", "b.json"]


def test_shipped_llm_labels_are_disclosed_and_not_blind():
    """The LLM set must declare that it is not blind and not human."""
    payload = json.loads((DATA / "llm_labels.json").read_text(encoding="utf-8"))
    assert payload["annotator_type"] == "llm_repo_aware"
    assert payload["blind"] is False
    assert "not blind" in payload["bias_disclosure"].lower() or            "violated" in payload["bias_disclosure"].lower()


def test_shipped_llm_labels_validate_against_cases():
    labels = json.loads((DATA / "llm_labels.json").read_text(encoding="utf-8"))
    cases = json.loads((DATA / "llm_judge_cases.json").read_text(encoding="utf-8"))
    result = validate_annotations(labels, cases)
    assert result["valid"] is True
    assert result["cases"] == len(cases["cases"])


def test_validator_catches_preferred_not_in_acceptable():
    cases = {"cases": [{"case_id": "c1", "action_menu": ["trade", "warn_player"], "memories": []}]}
    labels = {"cases": [{
        "case_id": "c1", "acceptable_actions": ["trade"], "preferred_action": "warn_player",
        "confidence": 0.5, "contradiction_present": False, "contradiction_summary": None,
        "decisive_memory_ids": [],
    }]}
    with pytest.raises(SystemExit):
        validate_annotations(labels, cases)


def test_validator_catches_action_not_in_menu():
    cases = {"cases": [{"case_id": "c1", "action_menu": ["trade"], "memories": []}]}
    labels = {"cases": [{
        "case_id": "c1", "acceptable_actions": ["arrest_player"], "preferred_action": "arrest_player",
        "confidence": 0.5, "contradiction_present": False, "contradiction_summary": None,
        "decisive_memory_ids": [],
    }]}
    with pytest.raises(SystemExit):
        validate_annotations(labels, cases)


def test_validator_catches_unknown_memory_id():
    cases = {"cases": [{"case_id": "c1", "action_menu": ["trade"],
                        "memories": [{"event_id": "real-1"}]}]}
    labels = {"cases": [{
        "case_id": "c1", "acceptable_actions": ["trade"], "preferred_action": "trade",
        "confidence": 0.5, "contradiction_present": False, "contradiction_summary": None,
        "decisive_memory_ids": ["fake-9"],
    }]}
    with pytest.raises(SystemExit):
        validate_annotations(labels, cases)
