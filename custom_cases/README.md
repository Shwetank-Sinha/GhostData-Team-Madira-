# Custom cases: what we asked, what we expected, what the engine produced

This folder holds a few **special requests**, each built to test one particular situation, together with
the answer we expected for each and the answer our engine actually produced. It is an honest side-by-side:
where the engine matches, where it does not, and why.

## What is in the folder

```
custom_cases/
  requests/    the special requests (req_1.csv ... req_4.csv), the same format as dataset/deletion_requests.csv
  expected/    the answers we expected (out_1.csv ... out_3.csv), the same format as output.csv
  results/     what the engine actually produced
    result_N.csv           the engine's answers, in the exact output.csv format
    result_N_skipped.csv   requests the engine set aside instead of guessing, with the reason
    readable.md            every answer written out in plain words
    comparison.md          each answer compared with its expected file
```

## The four sets

| Set | What it tests |
|---|---|
| `req_1` | Six requests that look like deletion requests but are not, or are written in another language: a French request, a Japanese request, a message trying to give the engine orders ("Ignore all previous instructions…"), a request that was withdrawn, a request to leave a marketing list only, and a request for a copy of one's data. |
| `req_2` | `case_548`: a real customer in our data whose small leftover record (a stub kept only so other records can refer to the customer) still shows personal details and must be blanked out. |
| `req_3` | A customer who asks for everything to be dealt with, expected to produce all four kinds of problem: a record still there, personal details still showing, a process still copying data, and a backup that could bring data back. |
| `req_4` | An extra we added: a real customer from our data (a new case id on the customer of `case_483`) that really does have all four kinds of problem, to show the engine produces them. It has no expected file. |

## The result at a glance

| Request | Expected | The engine produced |
|---|---|---|
| `req_withdrawn` | not a deletion request | **same, exact match** |
| `req_marketing_only` | not a deletion request | **same, exact match** |
| `req_dsar_export` | not a deletion request | **same, exact match** |
| `case_548` | something is left (4 steps) | **same, exact match, byte for byte** |
| `req_foreign_fr` | really done | not answered (customer unknown) |
| `req_foreign_jp` | really done | not answered (customer unknown) |
| `req_prompt_injection` | not a deletion request | **same, exact match** |
| `incomplete_all_four_findings` | something is left (all four problems) | not answered (customer unknown) |
| `demo_all_four_findings` | (no expected file) | something is left: all four problems found, 14 steps |

**5 of the 8 requests with an expected answer match exactly. The other 3 could not be answered.**

## Why some requests were "not answered"

To say whether someone's data was really deleted, the engine looks the person up by email in the customer
list (`dataset/user_identities.csv`), then searches the evidence for their data. If the email is not in the
list, there is no person to search for, so the engine **sets the request aside instead of guessing** and writes
it to the `_skipped.csv` file with the reason.

The three that could not be answered (`req_foreign_fr`, `req_foreign_jp`, `incomplete_all_four_findings`) belong to
made-up customers who do not exist in our data. Their expected answers refer to evidence (such as `account_fr01`
and `evidence_01`) that only exists in a separate made-up world, so they cannot be reproduced against this dataset.

A request that is **not** a deletion request is different: it needs no customer, so it is answered "not a
deletion request" whoever sent it. That is how the three look-alike requests and the prompt-injection message
are answered above.

### The prompt-injection message (fixed)

`req_prompt_injection` ("System Override: Ignore all previous instructions…") contains no deletion request at all.
An earlier version of the engine treated any message that did not look like something else as a deletion request,
so it went looking for a customer, found none, and set the request aside. The engine now recognises messages that
only give orders to the engine ("ignore all previous instructions", "system override", and similar) as not being
deletion requests. The rule is deliberately narrow: it does not affect any of the 550 real requests, and a customer
writing "ignore my previous email and delete my account" is still treated as asking for deletion.

## How to run it again

From the project root:

```bash
python tools/run_request_files.py custom_cases/requests/req_1.csv custom_cases/requests/req_2.csv custom_cases/requests/req_3.csv custom_cases/requests/req_4.csv --out custom_cases/results --expected custom_cases/expected
```

The same tool works on any request file: `python tools/run_request_files.py my_requests.csv --out my_results`.
A request that is not a deletion request is answered "not a deletion request" whoever the customer is; a deletion
request needs a customer that exists in the data, otherwise it is set aside with the reason.
