"""Score predicted answers against reference answers (the public samples).

Views reported, because the grader's exact formula is not known:
  status accuracy      the predicted deletion_status equals the reference
  step precision/recall/F1
                       steps compared as (phase, system_id, resource_id, operation, state, evidence_id)
                       tuples with order ignored; the "identity" variant leaves evidence_id out
  field accuracy       for each reference step that has a counterpart with the same
                       (phase, operation, system_id, resource_id): do state and evidence_id also match
  sequence accuracy    the ordered (phase, operation, system_id, resource_id) list is identical;
                       the mean similarity of those lists is reported as well
"""
from __future__ import annotations

from collections import Counter
from difflib import SequenceMatcher

FULL_FIELDS = ("phase", "system_id", "resource_id", "operation", "state", "evidence_id")
IDENTITY_FIELDS = ("phase", "system_id", "resource_id", "operation", "state")
POSITION_FIELDS = ("phase", "operation", "system_id", "resource_id")


def _pick(step: dict, fields: tuple[str, ...]) -> tuple:
    return tuple(step.get(name, "") for name in fields)


def score_case(pred_status: str, pred_steps: list[dict], gold_status: str, gold_steps: list[dict]) -> dict:
    """Every measurement for one case."""
    result: dict = {"status_ok": pred_status == gold_status}

    for label, fields in (("full", FULL_FIELDS), ("identity", IDENTITY_FIELDS)):
        predicted = Counter(_pick(s, fields) for s in pred_steps)
        expected = Counter(_pick(s, fields) for s in gold_steps)
        result[f"{label}_tp"] = sum((predicted & expected).values())
        result[f"{label}_pred"] = sum(predicted.values())
        result[f"{label}_gold"] = sum(expected.values())

    by_position = {_pick(s, POSITION_FIELDS): s for s in pred_steps}
    aligned = 0
    agreeing: Counter = Counter()
    for gold in gold_steps:
        counterpart = by_position.get(_pick(gold, POSITION_FIELDS))
        if counterpart is None:
            continue
        aligned += 1
        for name in ("state", "evidence_id"):
            if counterpart.get(name) == gold.get(name):
                agreeing[name] += 1
    result["matched_steps"], result["field_ok"] = aligned, agreeing

    pred_order = [_pick(s, POSITION_FIELDS) for s in pred_steps]
    gold_order = [_pick(s, POSITION_FIELDS) for s in gold_steps]
    result["sequence_exact"] = pred_order == gold_order
    result["lcs_ratio"] = (SequenceMatcher(None, pred_order, gold_order, autojunk=False).ratio()
                           if (pred_order or gold_order) else 1.0)

    numbered = ("step_no",) + FULL_FIELDS
    result["case_exact"] = result["status_ok"] and (
        [_pick(s, numbered) for s in pred_steps] == [_pick(s, numbered) for s in gold_steps])
    return result


def _ratio(part: int, whole: int) -> float:
    return round(part / whole, 4) if whole else 1.0


def summarize(results: list[dict]) -> dict:
    """Totals over many cases."""
    count = len(results)
    summary = {
        "cases": count,
        "status_correct": sum(r["status_ok"] for r in results),
        "cases_exact": sum(r["case_exact"] for r in results),
        "sequence_exact": sum(r["sequence_exact"] for r in results),
        "mean_lcs_ratio": round(sum(r["lcs_ratio"] for r in results) / count, 4) if count else 1.0,
    }
    for label in ("full", "identity"):
        tp = sum(r[f"{label}_tp"] for r in results)
        predicted = sum(r[f"{label}_pred"] for r in results)
        expected = sum(r[f"{label}_gold"] for r in results)
        precision, recall = _ratio(tp, predicted), _ratio(tp, expected)
        summary[f"{label}_steps"] = {
            "tp": tp, "pred": predicted, "gold": expected, "precision": precision, "recall": recall,
            "f1": round(2 * precision * recall / (precision + recall), 4) if tp else 0.0,
        }
    aligned = sum(r["matched_steps"] for r in results)
    summary["matched_steps"] = aligned
    summary["field_accuracy"] = {name: _ratio(sum(r["field_ok"][name] for r in results), aligned)
                                 for name in ("state", "evidence_id")}
    return summary
