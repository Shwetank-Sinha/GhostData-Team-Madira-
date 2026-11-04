# GhostData: AI-Powered Deletion-Audit Agent
**Team Madira** | Automated Data Deletion & Privacy Verification System

---

## 1. Executive Summary & Objective

In modern distributed microservice architectures, executing a user data deletion request ("Right to be Forgotten" under GDPR/CCPA) is notoriously prone to silent failures. As demonstrated by Northstar Shop's \$2.4M incident, primary account deletions often fail because:
1. Replicas, secondary reporting stores, search caches, and attachments quietly retain unredacted PII.
2. Automated synchronization, ETL pipelines, and recurring import jobs actively resurrect deleted records.
3. Unsanitized backup and restore paths present continuous re-exposure risks.

The **GhostData Deletion-Audit Agent** is an autonomous, evidence-driven auditing engine. It treats reported workflow status claims (`reported_status == "Complete"`) purely as unverified assertions. The agent inspects concrete system evidence across distributed stores at a specific timestamp (`audit_at`), resolves complete historical user identity graphs, enforces strict policy rules, identifies data leaks or active recreation vectors, and generates a fully compliant, strictly sorted audit report (`output.csv`).

---

## 2. System Architecture

The system pairs a deterministic verification engine (`ghost/`) with an autonomous AI investigator (`ghost/agent.py`):

```mermaid
flowchart TD
    A["Deletion Requests (deletion_requests.csv)"] --> B["1. Identity Resolution (ghost/identity.py)"]
    C["Identity Records (user_identities.csv, user_audit_log.csv)"] --> B
    B --> D["Resolved Identity Graph (UUIDs, Emails, Aliases, Hashes)"]
    
    D --> E["2. Multi-Modal Evidence Ingestion (ghost/evidence.py, ghost/activity.py)"]
    F["Evidence Files (dataset/evidence/: SQLite, JSON, Logs, PDFs)"] --> E
    G["System Activity Logs (system_activity.csv)"] --> E
    
    E --> H["3. Temporal Policy Evaluation Engine (ghost/policy.py, ghost/state.py)"]
    I["Deletion Rules (deletion_rules.csv at audit_at)"] --> H
    
    H --> J{"Evaluation Outcome"}
    J -->|"No Authorized Request"| K["NOT_APPLICABLE (steps_json: [])"]
    J -->|"Fully Compliant & Protected"| L["COMPLETE (Verification Only)"]
    J -->|"Remnants / Leaks / Sync Risks"| M["INCOMPLETE (Findings + Remediation + Future Verification)"]
    
    K --> N["Planner & Sequence Formatter (ghost/planner.py)"]
    L --> N
    M --> N
    N --> O["output.csv (518 Cases)"]
```

### Core Architecture Components

- **Deterministic Engine (`ghost/`):**
  - **`ghost/intake.py`**: Ingests requests and manifest structures.
  - **`ghost/identity.py`**: Resolves historical aliases, email variations, and account hashes across `user_identities.csv` and `user_audit_log.csv`.
  - **`ghost/evidence.py`**: Multi-format evidence parser (SQLite snapshots, JSON dumps, log files, support attachments/PDFs).
  - **`ghost/activity.py`**: Sync/import and backup risk discovery in `system_activity.csv`.
  - **`ghost/policy.py` & `ghost/state.py`**: Enforces `deletion_rules.csv` at `audit_at`, applying account tombstone rules (preserving `user_id` while stripping direct PII: name, email, phone, email_hash).
  - **`ghost/planner.py`**: Formats and strictly orders steps (`FINDING` $\rightarrow$ `REMEDIATION` $\rightarrow$ `VERIFICATION`).
  - **`ghost/validate.py`**: In-engine compliance gate verifying steps and state transitions.

- **AI Layer (`ghost/agent.py`, `ghost/agent_tools.py`):**
  - Autonomous reasoning agent equipped with read-only inspection tools for ambiguous evidence, unstructured attachments, and cross-system correlation.

- **Visualizer & Utilities (`viz/`):**
  - Inspection utilities for auditing case state transitions and evidence graphs.

---

## 3. Directory Layout

```
.
├── .env.example                  # Environment configuration template
├── README.md                     # System architecture & operational documentation
├── log.txt                       # Append-only interaction transcript
├── validate_submission.py        # Automated submission validation script
├── main.py                       # Main pipeline entry point
├── ghost/                        # Core audit engine & AI agent modules
│   ├── __init__.py
│   ├── intake.py                 # Request and manifest loading
│   ├── identity.py               # Historical identity graph resolution
│   ├── evidence.py               # Multi-modal evidence loader (SQLite, JSON, logs)
│   ├── activity.py               # Active sync & backup restore risk analysis
│   ├── policy.py                 # Deletion policy & tombstone evaluator
│   ├── state.py                  # Temporal state reconstruction at audit_at
│   ├── planner.py                # Deterministic step sequencing & formatting
│   ├── validate.py               # Engine-level step & state validation
│   ├── agent.py                  # AI investigation agent
│   ├── agent_tools.py            # Inspection tool definitions for LLM
│   └── vision.py                 # Visual & document evidence parser
├── evaluation/                   # Evaluation artifacts
│   ├── evaluation_report.md      # Metrics, custom evaluation test cases, & post-mortem
│   └── usage_report.md           # Model calls, token accounting, & cost breakdown
├── tests/                        # Automated unit and integration test suite
└── output.csv                    # Final generated audit results (518 cases)
```

---

## 4. Setup & Installation

### Prerequisites
* **Python:** Version 3.10, 3.11, or 3.12
* **Git:** Configured repository access
* **OS:** Windows, macOS, or Linux

### 1. Clone & Set Up Virtual Environment

```bash
# Clone the repository
git clone https://github.com/GhostData-Team-Madira-/GhostData-Team-Madira-.git
cd GhostData-Team-Madira-

# Create a virtual environment
python -m venv .venv

# Activate the virtual environment
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Linux/macOS:
source .venv/bin/activate

# Upgrade pip and install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

### 2. Environment Configuration

Copy the example environment configuration:

```bash
cp .env.example .env
```

Edit `.env` with your appropriate configuration values:

```ini
LLM_PROVIDER=gemini
LLM_API_KEY=your_actual_api_key_here
LLM_MODEL_NAME=gemini-2.5-pro
DATASET_DIR=./dataset
OUTPUT_FILE=./output.csv
```

> **Security Warning:** Never commit `.env` or any file containing API keys or private credentials to git.

---

## 5. Execution Instructions

### Run the Full Audit Pipeline (All 518 Cases)

To execute the complete audit analysis and generate `output.csv`:

```bash
python main.py --requests dataset/deletion_requests.csv --evidence dataset/evidence_files.csv --output output.csv
```

#### CLI Options
* `--requests <path>`: Path to `deletion_requests.csv` (default: `dataset/deletion_requests.csv`).
* `--rules <path>`: Path to `deletion_rules.csv` (default: `dataset/deletion_rules.csv`).
* `--evidence <path>`: Path to `evidence_files.csv` (default: `dataset/evidence_files.csv`).
* `--identities <path>`: Path to `user_identities.csv` (default: `dataset/user_identities.csv`).
* `--audit-log <path>`: Path to `user_audit_log.csv` (default: `dataset/user_audit_log.csv`).
* `--system-activity <path>`: Path to `system_activity.csv` (default: `dataset/system_activity.csv`).
* `--output <path>`: Path to output CSV file (default: `output.csv`).
* `--limit <n>`: Optional flag to process only the first $N$ cases (useful for dry runs and debugging).

---

## 6. Verification & Quality Assurance

Before packaging deliverables, validate the generated `output.csv` against all contest specifications using the validator script:

```bash
python validate_submission.py --file output.csv
```

The validation suite verifies:
1. **Header & Structure:** Exact column header `case_id,deletion_status,steps_json`.
2. **Row Count:** Exactly 518 data rows, strictly ordered by `case_id` ascending.
3. **Status Integrity:** Only valid statuses (`COMPLETE`, `INCOMPLETE`, `NOT_APPLICABLE`).
4. **`NOT_APPLICABLE` Handling:** Strict verification that `steps_json == "[]"`.
5. **Step Sequence & Numbering:** `step_no` is strictly 1-based and consecutively increasing without gaps.
6. **Phase & Operation Order:** Strict adherence to Phase order (`FINDING` $\rightarrow$ `REMEDIATION` $\rightarrow$ `VERIFICATION`) and intra-phase operation ordering.
7. **Tie-Breaking Determinism:** Verifies ascending sorting on `system_id` then `resource_id`.
8. **Evidence ID Integrity:** Ensures findings and verifications cite valid IDs, while proposed remediations/future verifications pass `""`.

---

## 7. Packaging & Submission

To build the final submission archive `code.zip`:

```bash
# Package files excluding dataset, virtual environments, caches, and local secrets
zip -r code.zip ghost/ evaluation/ tests/ viz/ README.md main.py validate_submission.py requirements.txt .env.example -x "*.pyc" -x "*__pycache__*" -x "*.venv*"
```

Verify that `code.zip` contains:
* Runnable source code (`ghost/`, `main.py`, `validate_submission.py`)
* Comprehensive `README.md` and `.env.example`
* Complete `evaluation/evaluation_report.md` (with metrics and 3 custom test cases)
* Complete `evaluation/usage_report.md` (with token usage and cost analysis)
* **Strictly excludes** `dataset/`, virtual environments, cache files, and API keys.
<!-- test commit on chirag branch -->
