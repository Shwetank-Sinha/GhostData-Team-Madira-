# Ghost Data Deletion Audit

A command-line tool that checks whether a person's data was really deleted after they asked a company to delete it. A workflow dashboard saying "Complete" is treated as a claim. The tool rebuilds the true state from the supplied evidence and writes one answer per request.

For each request it decides:

1. Does the request text actually ask for deletion? Access, correction, export and marketing opt-out do not, so those cases are `NOT_APPLICABLE` with no steps.
2. Who is the person? It rebuilds the current and past emails, phones, email hashes and user id from the identity snapshot and the change log.
3. What was the state of each of that person's records at `audit_at`? Only evidence dated at or before that time counts.
4. What does `deletion_rules.csv` require for each record, and in what safe order should the fixes happen?

Each answer is `COMPLETE`, `INCOMPLETE` or `NOT_APPLICABLE`, plus an ordered list of findings, remediation steps and verification checks.

## Requirements

* Python 3.10 or newer (developed on 3.12). The engine uses only the standard library; there is nothing to `pip install`.
* `tesseract` (reads the screenshot evidence) and `pdftotext` from poppler (reads the PDF evidence). The run stops with an error if either is missing, because a partial evidence index would give wrong answers.
  * Windows: `winget install UB-Mannheim.TesseractOCR` and `winget install oschwartz10612.Poppler`, then open a new terminal so PATH refreshes. The Tesseract installer may not add itself to PATH; if `tesseract` is not found, add `C:\Program Files\Tesseract-OCR` to PATH.
  * macOS: `brew install tesseract poppler`
  * Debian/Ubuntu: `sudo apt install tesseract-ocr poppler-utils`
* The `dataset/` folder next to `code/` (already present in this project).

## Run

From the project root:

```bash
python code/main.py run                 # answers every request, writes ./output.csv AND a new evaluation report
python code/main.py run --output X.csv  # write the answers somewhere else
python code/main.py run --no-report     # write output.csv only
python code/main.py run --no-readings   # ignore the stored screenshot readings (to see their effect)
python code/main.py identities          # check every request email resolves to a user
python code/main.py index               # index all evidence files and print a summary
python evaluation_test/run_evaluation.py   # write only a new report, without producing output.csv
```

Every run creates a new evaluation report and a new usage report named after the date and time, for example
`evaluation_test/evaluation_report_2026-11-05_08-15-30.md` and `evaluation_test/usage_report_2026-11-05_08-15-30.md`.
Existing reports are never overwritten.

To build the submission files (`submission/code.zip` and `submission/output.csv`), run the engine and then:

```bash
python tools/package_submission.py
```

The zip holds only the README, `code/`, `evaluation_test/run_evaluation.py` and an `evaluation/` folder with the newest evaluation and usage reports. It never holds the dataset, caches or run output, and the script stops if it finds a nested archive or anything that looks like a key.

`run` checks every row against the output rules before writing anything. If any row fails, the file is not written. The file is written to a temporary name and renamed at the end, so an interrupted run never leaves a half-written `output.csv`.

A run also writes `runs/audit.jsonl`, one line per case with the resources found and why the case came out the way it did.

## Output format

`output.csv` has the columns `case_id,deletion_status,steps_json`, one row per request in `dataset/deletion_requests.csv`, sorted by case number (`case_9` before `case_10`).

Each step in `steps_json` has `step_no, phase, system_id, resource_id, operation, state, evidence_id`.

| Phase | Operations (state) |
|---|---|
| FINDING | `REPORT_REMAINING_RECORD` (PRESENT), `REPORT_EXPOSED_PII` (PRESENT), `REPORT_ACTIVE_DATA_FLOW` (ACTIVE), `REPORT_RESTORE_RISK` (ACTIVE) |
| REMEDIATION | `DISABLE_DATA_FLOW` (DISABLED), `BLOCK_RESTORE` (BLOCKED), `DELETE_RECORD` (ABSENT), `REDACT_RECORD` (REDACTED), `ANONYMIZE_RECORD` (ANONYMIZED) |
| VERIFICATION | `VERIFY_RECORD_ABSENT`, `VERIFY_RECORD_PRESENT`, `VERIFY_RECORD_REDACTED`, `VERIFY_RECORD_ANONYMIZED`, `VERIFY_DATA_FLOW_DISABLED`, `VERIFY_RESTORE_BLOCKED` |

* `COMPLETE`: verification steps only, each citing the evidence that proves the state.
* `INCOMPLETE`: findings (citing evidence), the full remediation plan, then the checks to run afterwards. Remediation and future checks leave `evidence_id` empty. Data flows and restores are stopped before records change.
* `NOT_APPLICABLE`: `[]`.

## How it works

```
dataset/ ──► loader ──► identity resolver ─┐
evidence ──► indexer ───────────────────────┼─► linking ─► state ─► ledger ─► planner ─► row verifier ─► output.csv
request text ─► rule classifier ────────────┘                                  ▲
activity log ─► workflow matching (anonymous resources) ───────────────────────┘
```

* **Loader** (`data.py`): validates headers, ids, enums, timestamps and file paths, and reports every problem at once.
* **Identity** (`identity.py`): builds a timeline per user and field from the snapshot plus the change log. At `audit_at` it returns the current and historical identifiers. Names never link anything, and identifiers that only took effect after `audit_at` are ignored.
* **Evidence index** (`evidence.py`): reads SQL snapshots (through an in-memory sqlite with a restrictive authorizer), JSON, several log formats, text, PDFs and screenshots. Absence is proved only by a snapshot that covers the system and does not contain the record. OCR-garbled emails are repaired only when exactly one real email is close enough.
* **Linking and state** (`linking.py`, `state.py`): a resource belongs to a person when a record carrying one of their identifiers names it. Each record is read into a state for its resource type (present, absent, identifiable, anonymized, redacted, active, disabled, blocked). A record dated after `audit_at` never counts.
* **Ledger** (`ledger.py`): the latest admissible observation wins; on an exact tie, the reading where data still exists wins. Citations must come from files captured by `audit_at`.
* **Workflow matching** (`workflow.py`): a few resources, such as a deleted account, carry no identifier anywhere. They are tied to cases through the deletion worker's activity rows, and only when the match is forced in every consistent assignment.
* **Policy and planner** (`policy.py`, `planner.py`): the data category's required action and the observed state give the finding, remediation and verification, sorted by phase, operation order, `system_id`, `resource_id`.
* **Row verifier** (`verify.py`): checks keys, numbering, order, allowed operation and state pairs, evidence timing and that a cited file really names the resource.

Every decision is made by deterministic code, and the run itself calls no model. The same inputs give a byte-identical `output.csv`, regardless of `PYTHONHASHSEED`.

### Screenshot readings (the AI part)

OCR cannot always turn a console screenshot into a state ("Ready", "Continuous sync"). For the few resources where that was the only gap, a model viewed the screenshots and wrote down what each page shows in `code/readings/screenshot_readings.json`, with a quote from the page. `readings.py` checks every reading against the evidence before use (file in the manifest, resource id really on that page, known state) and applies it only for a case audited after the capture time and before any expiry the page states. A reading never links a resource to a person; it only supplies the state of a resource that identifiers already tie to the case.

Four readings are used. They change four cases (`case_35`, `case_39`, `case_50`, `case_52`) from COMPLETE to INCOMPLETE, each with a finding, a fix and a check. One screenshot (`backup_9287`) shows no restore status, so nothing was recorded for it, and `export_1260` is not applied to `case_33` because the page says it expired before that case's audit date.

`gemini.py` and `openai_client.py` (with `llm_common.py`) are ready-made clients with a cache and a usage ledger, for reading screenshots or checking request texts live. They read their keys from `GEMINI_API_KEY` or `OPENAI_API_KEY` and `main.py run` does not call them.

## Project layout

```
code/
  main.py                 command line (run, identities, index)
  deletion_audit/
    data.py models.py common.py     loading, typed rows, shared helpers
    identity.py                     who the person is, as of audit_at
    evidence.py                     evidence indexer
    linking.py state.py             record -> person, record -> state
    workflow.py                     links anonymous resources through the activity log
    ledger.py policy.py planner.py  per-case ledger, rules, ordered steps
    classifier.py                   does the text ask for deletion?
    verify.py scoring.py pipeline.py  row checks, sample scoring, orchestration
    evaluation.py                   scores the samples, checks all requests, writes the report
    readings.py                     loads and checks the stored screenshot readings
    llm_common.py gemini.py openai_client.py   optional model clients (cache, usage ledger)
  readings/screenshot_readings.json   states read from screenshots, with quotes
evaluation_test/
  run_evaluation.py       writes only the report (main.py run does it too)
  evaluation_report_<date>_<time>.md   evaluation report of a run
  usage_report_<date>_<time>.md        usage report of a run
tools/
  package_submission.py   builds submission/code.zip and submission/output.csv
  measure_gaps.py         read-only analysis: where the engine's gaps show up in the evidence
dataset/                  input data (read only)
output.csv                generated answers
runs/ .cache/             generated locally; not committed, safe to delete
```

## Results

Measured by the evaluation step of `python code/main.py run`; see the newest `evaluation_test/evaluation_report_*.md` for the full tables.

| Check | Result |
|---|---|
| Public samples (32), status accuracy | 32/32 |
| Samples with every step exactly right | 20/32 |
| Step precision / recall / F1 | 1.0 / 0.9275 / 0.9624 |
| All 518 requests | 160 COMPLETE, 348 INCOMPLETE, 10 NOT_APPLICABLE, 2983 steps |
| Contract problems in the 518 rows | 0 |

The 32 public samples are the only cases with reference answers, so accuracy on the 518 requests is not measured and may be lower.

## Known limits

* The `condition` column of `deletion_rules.csv` is not evaluated; the required action per data category is used.
* A resource that evidence does not tie to a case is left out instead of guessed. All 14 missing sample steps are of this kind (verification steps for anonymized analytics profiles, deleted accounts and audit records).
* 26 resources linked to a case are left out of its answer because their state is unreadable at the audit time (most are evidenced only after `audit_at`) or no allowed operation applies. They are listed in `runs/audit.jsonl` under `dropped` and `unplanned`.
* Two cases (`case_61`, `case_63`) have no identifiable resource in admissible evidence and are answered `COMPLETE` with no steps.
* The workflow matching infers links from timing; it is a statistical inference, not proof.
* An analytics record whose identifier columns are empty but whose free-text note holds an email is treated as anonymized.
* Resource ids are ordered as plain text (`account_1000` before `account_999`).
