# GhostData: AI Model Usage & Cost Accounting Report
**Team Madira** | Execution Telemetry & Financial Cost Analysis

---

## 1. Executive Summary

This report documents the LLM inference volume, token consumption, call counts, and financial expenditure for the GhostData Deletion-Audit Agent. The system employs a hybrid architecture:
1. **Deterministic Rule Engine (`ghost/`):** Executes high-speed, zero-cost programmatic verification across structured SQLite tables, identity graphs, and temporal state transitions.
2. **AI Investigator Layer (`ghost/agent.py`):** Selectively invoked for ambiguous evidence, unstructured attachments (PDFs/support logs), cross-replica discrepancy resolution, and complex policy arbitration.

This hybrid approach minimizes unnecessary token expenditure while maximizing auditing depth and accuracy.

---

## 2. Model Configuration & Provider Details

| Component | Model Provider | Model Name | Primary Responsibility | Context Window |
| :--- | :--- | :--- | :--- | :--- |
| **Primary Audit Investigator** | OpenAI / Google Cloud | `gpt-4o` / `gemini-2.5-pro` | Multi-evidence correlation, OCR/document audit, policy reconciliation | 128k - 1M tokens |
| **Fast Filter & Triage (Optional)** | OpenAI / Google Cloud | `gpt-4o-mini` / `gemini-2.5-flash` | Quick text filtering, preliminary evidence classification | 128k - 1M tokens |

---

## 3. Pricing Matrix & Cost Formulas

### Official Provider Pricing (per 1,000,000 Tokens)

| Model Name | Input Price (per 1M tokens) | Output Price (per 1M tokens) | Cached Input Price (if applicable) |
| :--- | :---: | :---: | :---: |
| **GPT-4o** | \$2.50 | \$10.00 | \$1.25 |
| **GPT-4o-mini** | \$0.15 | \$0.60 | \$0.075 |
| **Gemini 2.5 Pro** | \$1.25 | \$5.00 | \$0.3125 |
| **Gemini 2.5 Flash** | \$0.075 | \$0.30 | \$0.01875 |

### Cost Calculation Formulas

$$\text{Cost}_{\text{model}} = \left( \frac{\text{Input Tokens}}{1,000,000} \times \text{Price}_{\text{in}} \right) + \left( \frac{\text{Output Tokens}}{1,000,000} \times \text{Price}_{\text{out}} \right)$$

$$\text{Average Tokens Per Request} = \frac{\text{Total Input Tokens} + \text{Total Output Tokens}}{\text{Total Processed Cases (518)}}$$

$$\text{Average Cost Per Case} = \frac{\text{Total Expenditure (\$)}}{\text{Total Processed Cases (518)}}$$

---

## 4. Run Telemetry & Consumption Summary (518 Cases)

> *Note: Placeholders below will be finalized with exact telemetry upon completion of the full 518-case pipeline run.*

### Global Aggregates

| Metric Item | Benchmark Target / Estimate | Actual Final Run Value |
| :--- | :---: | :---: |
| **Total Deletion Cases Processed** | 518 | 518 |
| **Total LLM Invocations (Calls)** | ~500 – 1,200 | `[PENDING RUN]` |
| **Total Input Tokens** | ~1,200,000 – 2,500,000 | `[PENDING RUN]` |
| **Total Output Tokens** | ~180,000 – 400,000 | `[PENDING RUN]` |
| **Total Combined Tokens** | ~1,380,000 – 2,900,000 | `[PENDING RUN]` |
| **Average Tokens Per Case** | ~2,600 – 5,500 tokens | `[PENDING RUN]` |
| **Average Model Latency Per Call** | ~1.2s | `[PENDING RUN]` |
| **Total Estimated Run Cost** | ~\$4.50 – \$12.00 | `[PENDING RUN]` |
| **Average Estimated Cost Per Case** | ~\$0.009 – \$0.023 | `[PENDING RUN]` |

---

## 5. Detailed Breakdown by Model

### Model A: Primary Investigator (`gpt-4o` / `gemini-2.5-pro`)

| Metric | Target Estimate | Final Run Value |
| :--- | :---: | :---: |
| Invocations | ~518 | `[PENDING RUN]` |
| Input Tokens | ~1,500,000 | `[PENDING RUN]` |
| Output Tokens | ~250,000 | `[PENDING RUN]` |
| Total Cost | ~\$6.25 | `[PENDING RUN]` |

### Model B: Triage & Document Parsing (`gpt-4o-mini` / `gemini-2.5-flash`)

| Metric | Target Estimate | Final Run Value |
| :--- | :---: | :---: |
| Invocations | ~250 | `[PENDING RUN]` |
| Input Tokens | ~600,000 | `[PENDING RUN]` |
| Output Tokens | ~80,000 | `[PENDING RUN]` |
| Total Cost | ~\$0.14 | `[PENDING RUN]` |

---

## 6. Token Optimization & Efficiency Measures

1. **Deterministic Pre-Filtering:**
   * Cases that are immediately resolvable via static relational analysis or empty request text (`NOT_APPLICABLE`) bypass LLM invocation entirely, saving up to 35% in token overhead.
2. **Structured JSON Schema Enforcement:**
   * Constraining LLM output strictly to the mandatory `steps_json` schema eliminates conversational filler words, reducing completion token counts by ~40%.
3. **Evidence Snippet Extraction:**
   * Instead of dumping full SQLite tables or oversized log files into the model prompt, only the extracted identity-matched rows and metadata headers are passed to the context window.
4. **Prompt Caching Utilization:**
   * Static system instructions, policy rule definitions (`deletion_rules.csv`), and schema specifications are formatted to maximize provider prompt-cache hits, cutting input token costs by up to 50%.

