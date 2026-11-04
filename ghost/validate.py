"""
ghost.validate
Module for validating step objects, ordering, and audit output consistency.
Re-exports core validation routines from validate_submission.
"""

from typing import List, Dict, Any, Tuple, Optional, Set
import sys
import os

# Import core validators from root validate_submission
from validate_submission import (
    ALLOWED_STATUSES,
    PHASE_ORDER,
    ALLOWED_OPERATIONS,
    REQUIRED_STEP_KEYS,
    ValidationIssue,
    validate_step_schema,
    validate_step_order,
    validate_evidence_ids,
    validate_case,
    validate_output_file,
)

__all__ = [
    "ALLOWED_STATUSES",
    "PHASE_ORDER",
    "ALLOWED_OPERATIONS",
    "REQUIRED_STEP_KEYS",
    "ValidationIssue",
    "validate_step_schema",
    "validate_step_order",
    "validate_evidence_ids",
    "validate_case",
    "validate_output_file",
]

