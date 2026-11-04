#!/usr/bin/env python3
"""
validate_submission.py
GhostData Team Madira - Submission Validator

Validates output.csv against all contest constraints, schemas, ordering rules,
and semantic consistency requirements before final submission.
"""

import sys
import json
import csv
import argparse
from typing import List, Dict, Any, Tuple, Optional, Set

# ==============================================================================
# Specification Constants & Rules Matrix
# ==============================================================================

EXPECTED_HEADER = ["case_id", "deletion_status", "steps_json"]
EXPECTED_ROW_COUNT = 518

ALLOWED_STATUSES = {"COMPLETE", "INCOMPLETE", "NOT_APPLICABLE"}

# Phase execution hierarchy
PHASE_ORDER = {
    "FINDING": 1,
    "REMEDIATION": 2,
    "VERIFICATION": 3
}

# Strict intra-phase operation sequence order and required state mapping
ALLOWED_OPERATIONS = {
    "FINDING": {
        "REPORT_REMAINING_RECORD": (1, "PRESENT"),
        "REPORT_EXPOSED_PII": (2, "PRESENT"),
        "REPORT_ACTIVE_DATA_FLOW": (3, "ACTIVE"),
        "REPORT_RESTORE_RISK": (4, "ACTIVE"),
    },
    "REMEDIATION": {
        "DISABLE_DATA_FLOW": (1, "DISABLED"),
        "BLOCK_RESTORE": (2, "BLOCKED"),
        "DELETE_RECORD": (3, "ABSENT"),
        "REDACT_RECORD": (4, "REDACTED"),
        "ANONYMIZE_RECORD": (5, "ANONYMIZED"),
    },
    "VERIFICATION": {
        "VERIFY_RECORD_ABSENT": (1, "ABSENT"),
        "VERIFY_RECORD_PRESENT": (2, "PRESENT"),
        "VERIFY_RECORD_REDACTED": (3, "REDACTED"),
        "VERIFY_RECORD_ANONYMIZED": (4, "ANONYMIZED"),
        "VERIFY_DATA_FLOW_DISABLED": (5, "DISABLED"),
        "VERIFY_RESTORE_BLOCKED": (6, "BLOCKED"),
    }
}

REQUIRED_STEP_KEYS = {
    "step_no",
    "phase",
    "system_id",
    "resource_id",
    "operation",
    "state",
    "evidence_id"
}


# ==============================================================================
# Validation Error Collector
# ==============================================================================

class ValidationIssue:
    def __init__(self, severity: str, case_id: str, message: str):
        self.severity = severity  # 'ERROR' or 'WARNING'
        self.case_id = case_id
        self.message = message

    def __str__(self):
        return f"[{self.severity}] [Case: {self.case_id}] {self.message}"


# ==============================================================================
# Core Validation Engine
# ==============================================================================

def validate_step_schema(step: Dict[str, Any], index: int, case_id: str) -> List[str]:
    """Validate that a step object conforms to the exact schema."""
    errors = []
    
    # Check keys
    actual_keys = set(step.keys())
    missing_keys = REQUIRED_STEP_KEYS - actual_keys
    if missing_keys:
        errors.append(f"Step at index {index} missing keys: {sorted(missing_keys)}")
    
    unexpected_keys = actual_keys - REQUIRED_STEP_KEYS
    if unexpected_keys:
        errors.append(f"Step at index {index} has extra keys: {sorted(unexpected_keys)}")
        
    # Check step_no
    expected_step_no = index + 1
    if step.get("step_no") != expected_step_no:
        errors.append(
            f"Step at index {index} has step_no={step.get('step_no')}, expected {expected_step_no}"
        )
        
    # Check string fields
    for field in ["system_id", "resource_id"]:
        val = step.get(field)
        if not isinstance(val, str) or not val.strip():
            errors.append(f"Step {expected_step_no} field '{field}' must be a non-empty string, got: {val!r}")
            
    # Check phase
    phase = step.get("phase")
    if phase not in PHASE_ORDER:
        errors.append(f"Step {expected_step_no} invalid phase: {phase!r}. Must be one of {list(PHASE_ORDER.keys())}")
        return errors
        
    # Check operation and state matching
    op = step.get("operation")
    phase_ops = ALLOWED_OPERATIONS.get(phase, {})
    if op not in phase_ops:
        errors.append(
            f"Step {expected_step_no} invalid operation '{op}' for phase '{phase}'. Allowed: {list(phase_ops.keys())}"
        )
    else:
        expected_state = phase_ops[op][1]
        actual_state = step.get("state")
        if actual_state != expected_state:
            errors.append(
                f"Step {expected_step_no} ({op}) has state '{actual_state}', required state is '{expected_state}'"
            )
            
    return errors


def validate_step_order(steps: List[Dict[str, Any]], case_id: str) -> List[str]:
    """
    Validate strict sorting:
    1. Phase order (FINDING -> REMEDIATION -> VERIFICATION)
    2. Operation sequence order within Phase
    3. system_id ascending
    4. resource_id ascending
    """
    errors = []
    if len(steps) <= 1:
        return errors

    def sort_key(s: Dict[str, Any]) -> Tuple:
        phase = s.get("phase", "")
        phase_num = PHASE_ORDER.get(phase, 99)
        op = s.get("operation", "")
        op_num = ALLOWED_OPERATIONS.get(phase, {}).get(op, (99, ""))[0]
        sys_id = str(s.get("system_id", ""))
        res_id = str(s.get("resource_id", ""))
        return (phase_num, op_num, sys_id, res_id)

    for i in range(len(steps) - 1):
        curr = steps[i]
        nxt = steps[i + 1]
        k_curr = sort_key(curr)
        k_nxt = sort_key(nxt)

        if k_curr > k_nxt:
            errors.append(
                f"Order violation between Step {curr.get('step_no')} "
                f"({curr.get('phase')}:{curr.get('operation')}:{curr.get('system_id')}:{curr.get('resource_id')}) "
                f"and Step {nxt.get('step_no')} "
                f"({nxt.get('phase')}:{nxt.get('operation')}:{nxt.get('system_id')}:{nxt.get('resource_id')}). "
                f"Steps must be strictly sorted by Phase -> Operation -> system_id ASC -> resource_id ASC."
            )
            
    return errors


def validate_evidence_ids(steps: List[Dict[str, Any]], status: str, case_id: str) -> List[str]:
    """
    Validate evidence_id conventions:
    - INCOMPLETE:
        - FINDING: must cite a non-empty evidence_id (file_id, activity_id, audit_id)
        - REMEDIATION: must be empty string ""
        - VERIFICATION (future check): must be empty string ""
    - COMPLETE:
        - VERIFICATION: must cite a non-empty evidence_id
    """
    errors = []
    for step in steps:
        s_no = step.get("step_no")
        phase = step.get("phase")
        ev_id = step.get("evidence_id")
        
        if not isinstance(ev_id, str):
            errors.append(f"Step {s_no} evidence_id must be a string, got: {type(ev_id).__name__}")
            continue

        if status == "COMPLETE":
            # COMPLETE contains verification steps only, must cite evidence proving current state
            if not ev_id.strip():
                errors.append(
                    f"Step {s_no} (COMPLETE verification) has empty evidence_id. Must cite valid proof."
                )
        elif status == "INCOMPLETE":
            if phase == "FINDING":
                if not ev_id.strip():
                    errors.append(
                        f"Step {s_no} (FINDING) has empty evidence_id. Must cite evidence discovering the issue."
                    )
            elif phase in ("REMEDIATION", "VERIFICATION"):
                if ev_id != "":
                    errors.append(
                        f"Step {s_no} (INCOMPLETE {phase}) must have evidence_id == '', but got '{ev_id}'."
                    )
                    
    return errors


def validate_case(
    case_id: str,
    status: str,
    steps_json_str: str,
    known_evidence_ids: Optional[Set[str]] = None
) -> List[ValidationIssue]:
    """Validate a single case record."""
    issues = []
    
    # Check deletion_status
    if status not in ALLOWED_STATUSES:
        issues.append(
            ValidationIssue("ERROR", case_id, f"Invalid deletion_status '{status}'. Must be one of {ALLOWED_STATUSES}")
        )
        return issues
        
    # Parse JSON
    try:
        steps = json.loads(steps_json_str)
    except Exception as e:
        issues.append(ValidationIssue("ERROR", case_id, f"Failed to parse steps_json as JSON: {e}"))
        return issues

    if not isinstance(steps, list):
        issues.append(ValidationIssue("ERROR", case_id, f"steps_json must be a JSON array, got {type(steps).__name__}"))
        return issues

    # Status-specific content rules
    if status == "NOT_APPLICABLE":
        if len(steps) != 0:
            issues.append(
                ValidationIssue(
                    "ERROR",
                    case_id,
                    f"NOT_APPLICABLE status must have empty steps_json ([]), found {len(steps)} steps."
                )
            )
        return issues

    if status == "COMPLETE":
        if len(steps) == 0:
            issues.append(
                ValidationIssue(
                    "ERROR",
                    case_id,
                    "COMPLETE status must contain verification steps proving current state, found 0 steps."
                )
            )
        for s in steps:
            if s.get("phase") != "VERIFICATION":
                issues.append(
                    ValidationIssue(
                        "ERROR",
                        case_id,
                        f"COMPLETE status must only contain VERIFICATION phase steps, found phase '{s.get('phase')}' in step {s.get('step_no')}."
                    )
                )

    if status == "INCOMPLETE":
        if len(steps) == 0:
            issues.append(
                ValidationIssue(
                    "ERROR",
                    case_id,
                    "INCOMPLETE status must contain findings, remediation, and verification steps, found 0 steps."
                )
            )
        phases_present = {s.get("phase") for s in steps}
        # Ideally should have findings, remediation, and verification
        if "FINDING" not in phases_present:
            issues.append(
                ValidationIssue("WARNING", case_id, "INCOMPLETE case has no FINDING phase steps.")
            )
        if "REMEDIATION" not in phases_present:
            issues.append(
                ValidationIssue("WARNING", case_id, "INCOMPLETE case has no REMEDIATION phase steps.")
            )
        if "VERIFICATION" not in phases_present:
            issues.append(
                ValidationIssue("WARNING", case_id, "INCOMPLETE case has no VERIFICATION phase steps.")
            )

    # Validate individual step schemas
    for idx, step in enumerate(steps):
        schema_errors = validate_step_schema(step, idx, case_id)
        for err in schema_errors:
            issues.append(ValidationIssue("ERROR", case_id, err))

    # Validate step order
    order_errors = validate_step_order(steps, case_id)
    for err in order_errors:
        issues.append(ValidationIssue("ERROR", case_id, err))

    # Validate evidence IDs
    ev_errors = validate_evidence_ids(steps, status, case_id)
    for err in ev_errors:
        issues.append(ValidationIssue("ERROR", case_id, err))

    # Optional: cross-check evidence IDs against known manifest
    if known_evidence_ids:
        for step in steps:
            ev_id = step.get("evidence_id", "")
            if ev_id and ev_id not in known_evidence_ids:
                issues.append(
                    ValidationIssue(
                        "WARNING",
                        case_id,
                        f"Step {step.get('step_no')} cites unknown evidence_id '{ev_id}' not found in manifest."
                    )
                )

    return issues


def validate_output_file(
    filepath: str,
    requests_path: Optional[str] = None,
    evidence_manifest_path: Optional[str] = None,
    expected_rows: int = EXPECTED_ROW_COUNT
) -> Tuple[bool, List[ValidationIssue], Dict[str, Any]]:
    """
    Validate the entire output.csv file.
    Returns (is_valid, issues, summary_stats).
    """
    issues: List[ValidationIssue] = []
    stats = {
        "total_rows": 0,
        "complete_count": 0,
        "incomplete_count": 0,
        "not_applicable_count": 0,
        "total_steps": 0,
        "errors": 0,
        "warnings": 0
    }

    # Optional: load known evidence IDs
    known_evidence_ids: Optional[Set[str]] = None
    if evidence_manifest_path:
        try:
            with open(evidence_manifest_path, mode="r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                known_evidence_ids = {row["file_id"] for row in reader if "file_id" in row}
        except Exception as e:
            issues.append(ValidationIssue("WARNING", "GLOBAL", f"Could not load evidence manifest: {e}"))

    # Optional: load expected case_ids
    expected_case_ids: Optional[List[str]] = None
    if requests_path:
        try:
            with open(requests_path, mode="r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                expected_case_ids = [row["case_id"] for row in reader if "case_id" in row]
        except Exception as e:
            issues.append(ValidationIssue("WARNING", "GLOBAL", f"Could not load requests file: {e}"))

    try:
        with open(filepath, mode="r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            try:
                header = next(reader)
            except StopIteration:
                issues.append(ValidationIssue("ERROR", "GLOBAL", "The file is completely empty."))
                stats["errors"] += 1
                return False, issues, stats

            # 1. Header Check
            if header != EXPECTED_HEADER:
                issues.append(
                    ValidationIssue(
                        "ERROR",
                        "GLOBAL",
                        f"Invalid header {header!r}. Expected exact: {EXPECTED_HEADER!r}"
                    )
                )

            seen_case_ids = []
            row_idx = 1
            for row in reader:
                row_idx += 1
                if not row:
                    continue  # skip empty lines

                if len(row) != 3:
                    issues.append(
                        ValidationIssue(
                            "ERROR",
                            f"Row {row_idx}",
                            f"Expected exactly 3 columns, found {len(row)}: {row!r}"
                        )
                    )
                    continue

                case_id, status, steps_json_str = row[0].strip(), row[1].strip(), row[2].strip()
                seen_case_ids.append(case_id)
                stats["total_rows"] += 1

                if status == "COMPLETE":
                    stats["complete_count"] += 1
                elif status == "INCOMPLETE":
                    stats["incomplete_count"] += 1
                elif status == "NOT_APPLICABLE":
                    stats["not_applicable_count"] += 1

                # Validate case
                case_issues = validate_case(case_id, status, steps_json_str, known_evidence_ids)
                issues.extend(case_issues)

                # Count steps
                try:
                    steps = json.loads(steps_json_str)
                    if isinstance(steps, list):
                        stats["total_steps"] += len(steps)
                except Exception:
                    pass

    except FileNotFoundError:
        issues.append(ValidationIssue("ERROR", "GLOBAL", f"File not found: {filepath}"))
        stats["errors"] += 1
        return False, issues, stats
    except Exception as e:
        issues.append(ValidationIssue("ERROR", "GLOBAL", f"Unexpected read error: {e}"))
        stats["errors"] += 1
        return False, issues, stats

    # 2. Row Count Check
    if expected_rows is not None and stats["total_rows"] != expected_rows:
        issues.append(
            ValidationIssue(
                "ERROR",
                "GLOBAL",
                f"Row count mismatch: found {stats['total_rows']} data rows, expected exactly {expected_rows}."
            )
        )

    # 3. Case ID Ordering & Duplicates
    if seen_case_ids:
        # Check duplicates
        if len(seen_case_ids) != len(set(seen_case_ids)):
            duplicates = [c for c in seen_case_ids if seen_case_ids.count(c) > 1]
            issues.append(
                ValidationIssue("ERROR", "GLOBAL", f"Found duplicate case_ids: {sorted(set(duplicates))}")
            )

        # Check sorting
        sorted_ids = sorted(seen_case_ids)
        if seen_case_ids != sorted_ids:
            issues.append(
                ValidationIssue("ERROR", "GLOBAL", "Rows are not sorted by case_id ascending.")
            )

        # Check matching expected case_ids
        if expected_case_ids:
            if seen_case_ids != sorted(expected_case_ids):
                missing = set(expected_case_ids) - set(seen_case_ids)
                extra = set(seen_case_ids) - set(expected_case_ids)
                if missing:
                    issues.append(ValidationIssue("ERROR", "GLOBAL", f"Missing expected case_ids: {sorted(missing)[:5]}..."))
                if extra:
                    issues.append(ValidationIssue("ERROR", "GLOBAL", f"Unexpected extra case_ids: {sorted(extra)[:5]}..."))

    # Tally errors vs warnings
    stats["errors"] = sum(1 for i in issues if i.severity == "ERROR")
    stats["warnings"] = sum(1 for i in issues if i.severity == "WARNING")
    is_valid = (stats["errors"] == 0)

    return is_valid, issues, stats


# ==============================================================================
# CLI Entry Point
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="GhostData Deletion-Audit Submission Validator"
    )
    parser.add_argument(
        "--file", "-f",
        default="output.csv",
        help="Path to the output CSV file to validate (default: output.csv)"
    )
    parser.add_argument(
        "--requests", "-r",
        default=None,
        help="Path to deletion_requests.csv to verify exact case_ids"
    )
    parser.add_argument(
        "--evidence", "-e",
        default=None,
        help="Path to evidence_files.csv to verify evidence_id cross-references"
    )
    parser.add_argument(
        "--expected-rows", "-n",
        type=int,
        default=EXPECTED_ROW_COUNT,
        help=f"Expected row count (default: {EXPECTED_ROW_COUNT})"
    )

    args = parser.parse_args()

    print("================================================================================")
    print("          GhostData Submission Validation Suite (Team Madira)")
    print("================================================================================")
    print(f"Target File:           {args.file}")
    print(f"Expected Rows:         {args.expected_rows}")
    print(f"Requests Path:         {args.requests or 'Not provided'}")
    print(f"Evidence Path:         {args.evidence or 'Not provided'}")
    print("--------------------------------------------------------------------------------")

    is_valid, issues, stats = validate_output_file(
        filepath=args.file,
        requests_path=args.requests,
        evidence_manifest_path=args.evidence,
        expected_rows=args.expected_rows
    )

    # Print summary stats
    print(f"Total Rows Scanned:    {stats['total_rows']}")
    print(f"  - COMPLETE:          {stats['complete_count']}")
    print(f"  - INCOMPLETE:        {stats['incomplete_count']}")
    print(f"  - NOT_APPLICABLE:    {stats['not_applicable_count']}")
    print(f"Total Steps Scanned:   {stats['total_steps']}")
    print(f"Errors Found:          {stats['errors']}")
    print(f"Warnings Found:        {stats['warnings']}")
    print("--------------------------------------------------------------------------------")

    if issues:
        print("\nDetailed Issues:")
        for issue in issues[:30]:  # Cap display at first 30
            print(f"  {issue}")
        if len(issues) > 30:
            print(f"  ... and {len(issues) - 30} more issues omitted.")
        print()

    if is_valid:
        print("[SUCCESS] Output file strictly complies with all contest specifications!")
        sys.exit(0)
    else:
        print("[FAILURE] Output file failed validation. Fix errors above before submitting.")
        sys.exit(1)


if __name__ == "__main__":
    main()

