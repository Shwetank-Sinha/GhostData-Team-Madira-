"""
Unit tests for validate_submission.py and ghost.validate
"""

import unittest
import json
import tempfile
import os
import csv
from validate_submission import (
    validate_case,
    validate_output_file,
    validate_step_order,
    validate_step_schema,
    validate_evidence_ids,
)

class TestSubmissionValidator(unittest.TestCase):

    def test_not_applicable_valid(self):
        issues = validate_case("case_001", "NOT_APPLICABLE", "[]")
        self.assertEqual(len(issues), 0)

    def test_not_applicable_invalid_non_empty(self):
        non_empty = json.dumps([{"step_no": 1, "phase": "VERIFICATION"}])
        issues = validate_case("case_001", "NOT_APPLICABLE", non_empty)
        self.assertTrue(any("empty steps_json" in i.message for i in issues))

    def test_complete_valid(self):
        steps = [
            {
                "step_no": 1,
                "phase": "VERIFICATION",
                "system_id": "account_service",
                "resource_id": "account_001",
                "operation": "VERIFY_RECORD_ABSENT",
                "state": "ABSENT",
                "evidence_id": "ev_01"
            }
        ]
        issues = validate_case("case_002", "COMPLETE", json.dumps(steps))
        self.assertEqual(len(issues), 0)

    def test_complete_invalid_finding_phase(self):
        steps = [
            {
                "step_no": 1,
                "phase": "FINDING",
                "system_id": "account_service",
                "resource_id": "account_001",
                "operation": "REPORT_REMAINING_RECORD",
                "state": "PRESENT",
                "evidence_id": "ev_01"
            }
        ]
        issues = validate_case("case_002", "COMPLETE", json.dumps(steps))
        self.assertTrue(any("only contain VERIFICATION" in i.message for i in issues))

    def test_incomplete_valid(self):
        steps = [
            {
                "step_no": 1,
                "phase": "FINDING",
                "system_id": "account_service",
                "resource_id": "account_001",
                "operation": "REPORT_REMAINING_RECORD",
                "state": "PRESENT",
                "evidence_id": "ev_01"
            },
            {
                "step_no": 2,
                "phase": "REMEDIATION",
                "system_id": "account_service",
                "resource_id": "account_001",
                "operation": "DELETE_RECORD",
                "state": "ABSENT",
                "evidence_id": ""
            },
            {
                "step_no": 3,
                "phase": "VERIFICATION",
                "system_id": "account_service",
                "resource_id": "account_001",
                "operation": "VERIFY_RECORD_ABSENT",
                "state": "ABSENT",
                "evidence_id": ""
            }
        ]
        issues = validate_case("case_003", "INCOMPLETE", json.dumps(steps))
        errors = [i for i in issues if i.severity == "ERROR"]
        self.assertEqual(len(errors), 0)

    def test_strict_ordering_violation(self):
        # Remediation placed before Finding
        steps = [
            {
                "step_no": 1,
                "phase": "REMEDIATION",
                "system_id": "account_service",
                "resource_id": "account_001",
                "operation": "DELETE_RECORD",
                "state": "ABSENT",
                "evidence_id": ""
            },
            {
                "step_no": 2,
                "phase": "FINDING",
                "system_id": "account_service",
                "resource_id": "account_001",
                "operation": "REPORT_REMAINING_RECORD",
                "state": "PRESENT",
                "evidence_id": "ev_01"
            }
        ]
        errors = validate_step_order(steps, "case_004")
        self.assertTrue(len(errors) > 0)
        self.assertTrue(any("Order violation" in e for e in errors))

    def test_state_mismatch(self):
        # REPORT_REMAINING_RECORD with state ABSENT instead of PRESENT
        step = {
            "step_no": 1,
            "phase": "FINDING",
            "system_id": "account_service",
            "resource_id": "account_001",
            "operation": "REPORT_REMAINING_RECORD",
            "state": "ABSENT",  # Should be PRESENT
            "evidence_id": "ev_01"
        }
        errors = validate_step_schema(step, 0, "case_005")
        self.assertTrue(any("required state is 'PRESENT'" in e for e in errors))


if __name__ == "__main__":
    unittest.main()

