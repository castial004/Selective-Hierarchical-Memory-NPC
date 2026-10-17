"""Run the blind evaluator prompt through an LLM and capture annotations.

Why this module exists
---------------------
The human-evaluation protocol needs 3+ genuinely independent annotators. Human
raters are one path; blind LLM judges are another, provided they never see the
repository, the author labels, the tested system's outputs, or another judge's
answers. This module operationalises the LLM path:

  1. load evaluation_data/blind_cases.json   (the answer-free instrument)
  2. load evaluation_data/evaluator_prompt.md (the fixed role prompt)
  3. fill the two placeholders and call an OpenAI-compatible chat endpoint
  4. extract the JSON, validate it against the blind cases
  5. write llm_labels_run_<n>.json with annotator_type="llm_blind"

Design constraints
------------------
* Zero third-party dependencies -- uses urllib, so it runs without installing
  anything. pyproject keeps "dependencies = []".
* A pluggable transport makes the whole pipeline testable without network: the
  tests inject a fake transport that returns canned JSON.
* The written file is tagged llm_blind / blind=true. It is NEVER human ground
  truth, and check_dataset_purity refuses to merge it with a human file.
* This module never fabricates annotations. If there is no endpoint, no key, or
  the call fails, it raises; it does not invent labels.

Blindness is a property of the INVOCATION, not of this code. Run each judge in a
fresh context with no repository access, and do not reuse one judge's output as
another's input. The module cannot enforce that for you; the tests only prove the
prompt it sends contains no answer information.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from npc_memory_project.evaluation.annotation import validate_annotations

PROMPT_PATH = Path("evaluation_data/evaluator_prompt.md")
BLIND_PATH = Path("evaluation_data/blind_cases.json")

#: A transport takes (endpoint, api_key, model, prompt) and returns the raw
#: assistant message text. Injectable so tests run offline.
Transport = Callable[[str, str, str, str], str]


class JudgeError(RuntimeError):
    """Raised when a judge run cannot be completed honestly."""


def load_prompt(path: Path = PROMPT_PATH) -> str:
    text = path.read_text(encoding="utf-8")
    if "{{EVALUATOR_ID}}" not in text or "{{EVALUATION_CASES_JSON}}" not in text:
        raise JudgeError(f"{path}: prompt template is missing its placeholders")
    return text


def load_blind_cases(path: Path = BLIND_PATH) -> Dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not data.get("cases"):
        raise JudgeError(f"{path}: no cases")
    return data


def build_prompt(template: str, evaluator_id: str, cases: Dict[str, object]) -> str:
    """Fill the two placeholders. The cases payload is the blind instrument."""
    return (
        template
        .replace("{{EVALUATOR_ID}}", evaluator_id)
        .replace("{{EVALUATION_CASES_JSON}}", json.dumps(cases, indent=2))
    )


def extract_json(text: str) -> Dict[str, object]:
    """Pull the first JSON object out of a model reply.

    Models sometimes wrap output in prose or code fences despite instructions.
    We take the first balanced {...} block and parse it; if that fails, raise
    rather than guess.
    """
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    start = stripped.find("{")
    if start == -1:
        raise JudgeError("model reply contains no JSON object")
    depth = 0
    for i in range(start, len(stripped)):
        if stripped[i] == "{":
            depth += 1
        elif stripped[i] == "}":
            depth -= 1
            if depth == 0:
                block = stripped[start:i + 1]
                try:
                    return json.loads(block)
                except json.JSONDecodeError as exc:
                    raise JudgeError(f"could not parse JSON block: {exc}") from exc
    raise JudgeError("unbalanced JSON object in model reply")


def http_transport(
    endpoint: str, api_key: str, model: str, prompt: str, *, timeout: int = 120,
) -> str:
    """POST an OpenAI-compatible chat completion and return the message text."""
    body = json.dumps({
        "model": model,
        "temperature": 0.0,
        "messages": [
            {"role": "system", "content": "You are an independent blind evaluator. "
                                          "Return JSON only."},
            {"role": "user", "content": prompt},
        ],
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise JudgeError(f"HTTP {exc.code} from {endpoint}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise JudgeError(f"could not reach {endpoint}: {exc.reason}") from exc
    try:
        return payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise JudgeError(f"unexpected response shape from {endpoint}: {exc}") from exc


@dataclass
class JudgeRun:
    evaluator_id: str
    model: str
    endpoint: str
    labels: Dict[str, object]
    raw_reply: str
    output_path: Optional[Path] = None


def run_judge(
    *,
    evaluator_id: str,
    model: str,
    endpoint: str,
    api_key: str = "",
    transport: Optional[Transport] = None,
    prompt_path: Path = PROMPT_PATH,
    blind_path: Path = BLIND_PATH,
) -> JudgeRun:
    """Run one blind judge and return validated, tagged labels.

    Raises JudgeError on any failure. Never returns fabricated labels.
    """
    transport = transport or http_transport
    template = load_prompt(prompt_path)
    cases = load_blind_cases(blind_path)
    prompt = build_prompt(template, evaluator_id, cases)

    raw = transport(endpoint, api_key, model, prompt)
    if not raw or not raw.strip():
        raise JudgeError("model returned an empty reply")

    parsed = extract_json(raw)
    if parsed.get("evaluator_id") in (None, ""):
        parsed["evaluator_id"] = evaluator_id
    if parsed.get("evaluator_id") != evaluator_id:
        raise JudgeError(
            f"reply evaluator_id {parsed.get('evaluator_id')!r} does not match "
            f"requested {evaluator_id!r}"
        )

    # validate against the blind instrument before tagging and saving
    validate_annotations(parsed, cases)

    parsed["annotator_type"] = "llm_blind"
    parsed["blind"] = True
    parsed["judge_model"] = model
    parsed["judge_endpoint"] = endpoint
    parsed["instrument"] = "evaluation_data/blind_cases.json"
    parsed["prompt"] = "evaluation_data/evaluator_prompt.md"
    parsed["ground_truth"] = False
    parsed["note"] = (
        "Blind LLM judge. NOT human ground truth. Keep separate from "
        "human_labels.json; check_dataset_purity refuses to merge them."
    )
    return JudgeRun(evaluator_id, model, endpoint, parsed, raw)


def save_run(run: JudgeRun, path: Path) -> Path:
    path.write_text(json.dumps(run.labels, indent=2), encoding="utf-8")
    return path


def run_judges(
    runs: Sequence[Dict[str, str]],
    *,
    out_dir: Path = Path("evaluation_data"),
    transport: Optional[Transport] = None,
) -> List[Path]:
    """Execute several judge configurations and write run_1, run_2, ... files."""
    written: List[Path] = []
    for index, config in enumerate(runs, start=1):
        result = run_judge(
            evaluator_id=config["evaluator_id"],
            model=config["model"],
            endpoint=config["endpoint"],
            api_key=config.get("api_key", ""),
            transport=transport,
        )
        path = out_dir / f"llm_labels_run_{index}.json"
        save_run(result, path)
        written.append(path)
    return written
