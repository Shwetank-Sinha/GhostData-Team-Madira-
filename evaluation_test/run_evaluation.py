"""Write a new timestamped evaluation report on its own, without producing output.csv.

    python evaluation_test/run_evaluation.py

`python code/main.py run` does this too, right after it writes output.csv.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))

from deletion_audit.data import load_dataset  # noqa: E402
from deletion_audit.evaluation import write_report  # noqa: E402
from deletion_audit.pipeline import Pipeline  # noqa: E402


def main() -> int:
    dataset = load_dataset()
    samples, checks, report_path = write_report(dataset, Pipeline(dataset))
    print(f"samples: status {samples['status_correct']}/{samples['cases']}, exact {samples['cases_exact']}/{samples['cases']}, "
          f"F1 {samples['full_steps']['f1']}")
    print(f"requests: {dict(checks['counts'])}, {checks['steps']} steps, {len(checks['problems'])} contract problems")
    print(f"report written to {report_path}")
    return 1 if checks["problems"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
