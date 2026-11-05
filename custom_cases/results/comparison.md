# Results compared with the expected outputs

Each request file was run through the engine and its answer was compared with the matching expected file.

## req_1.csv

| Request | Expected | Got | Result |
|---|---|---|---|
| req_foreign_fr | COMPLETE | - | Could not be answered |
| req_foreign_jp | COMPLETE | - | Could not be answered |
| req_prompt_injection | NOT_APPLICABLE | NOT_APPLICABLE | Matches the expected output exactly |
| req_withdrawn | NOT_APPLICABLE | NOT_APPLICABLE | Matches the expected output exactly |
| req_marketing_only | NOT_APPLICABLE | NOT_APPLICABLE | Matches the expected output exactly |
| req_dsar_export | NOT_APPLICABLE | NOT_APPLICABLE | Matches the expected output exactly |

**req_foreign_fr** — Could not be answered.
Why: This email is not in the customer list.

**req_foreign_jp** — Could not be answered.
Why: This email is not in the customer list.

## req_2.csv

| Request | Expected | Got | Result |
|---|---|---|---|
| case_548 | INCOMPLETE | INCOMPLETE | Matches the expected output exactly |

## req_3.csv

| Request | Expected | Got | Result |
|---|---|---|---|
| incomplete_all_four_findings | INCOMPLETE | - | Could not be answered |

**incomplete_all_four_findings** — Could not be answered.
Why: This email is not in the customer list.

## req_4.csv

No expected file was found to compare with.

## Summary

* Matches the expected output exactly: 5
* Same verdict, steps differ: 0
* Different verdict: 0
* Could not be answered: 3
