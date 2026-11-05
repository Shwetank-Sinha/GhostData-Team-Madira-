"""Small shared helpers: project paths, time parsing and identifier normalisation."""
from __future__ import annotations

import hashlib
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

# <root>/code/deletion_audit/common.py -> the project root is two directories up.
REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = REPO_ROOT / "dataset"


def parse_ts(value: str) -> datetime:
    """ISO-8601 text (a trailing Z is accepted) -> timezone-aware UTC datetime."""
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def normalize_email(value: str) -> str:
    """The one form used when comparing emails: NFKC, trimmed, case-folded."""
    return unicodedata.normalize("NFKC", value).strip().casefold()


def normalize_phone(value: str) -> str:
    """Keep the digits and put a '+' in front; no digits at all gives ''.

    Numbers without a country code are not guessed at, they just keep their own digits.
    """
    digits = "".join(ch for ch in value if ch.isdecimal())
    return "+" + digits if digits else ""


def email_hash(email: str) -> str:
    """sha256 of the normalised email, which is how user_identities.csv stores hashes."""
    return hashlib.sha256(normalize_email(email).encode("utf-8")).hexdigest()


def case_sort_key(case_id: str) -> tuple[str, int]:
    """Natural ordering for ids such as case_9 < case_10 (plain text order would flip them).

    The id is split into everything before its trailing digits and those digits as a number.
    An id with no trailing digits sorts by its own text, ahead of numbered ids with that prefix.
    """
    stem = case_id.rstrip("0123456789")
    tail = case_id[len(stem):]
    if not tail:
        return (case_id, -1)
    return (stem, int(tail))
