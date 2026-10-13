# Synthetic Demo Dataset — Operation Falcon

**Task:** H1 — Synthetic Demo Dataset  
**Version:** 1.0  
**Status:** Complete  
**For use by:** B2 (ingestion), B7 (entity resolution), H3 (integration test)

> **All data is entirely synthetic and fabricated. No real individuals, organisations, or law-enforcement records are represented. Any resemblance to real people, accounts, or events is coincidental and unintentional.**

---

## Scenario Overview

**Operation Falcon** — a fictional financial fraud investigation involving four primary suspects, a shell company, and a chain of layered transactions across six source types.

| Entity | Type | Role |
|---|---|---|
| Rahul Sharma | Person | Primary orchestrator |
| Priya Mehta | Person | Financial routing / layering |
| Devendra Khanna | Person | Corporate cover (Director, Khanna Enterprises) |
| Rajan Patel | Person | Field operative / courier |
| Khanna Enterprises Pvt Ltd | Organization | Shell company |
| Global Trading FZE | Organization | Offshore counterparty (Dubai) |

---

## Source Files

| Folder | Source Type (DOC3 §2.2) | Records | Format |
|---|---|---|---|
| `fir/` | `FIR` | 3 (individual .json files) | One file per FIR |
| `police_report/` | `police_report` | 2 (individual .json files) | One file per report |
| `cdr/` | `CDR` | 10 (array in records.json) | All calls in one file |
| `transactions/` | `transaction` | 6 (array in records.json) | All transactions in one file |
| `vehicles/` | `vehicle_registry` | 3 (array in records.json) | All registrations in one file |
| `surveillance/` | `surveillance` | 4 (array in records.json) | All observations in one file |
| `social_media/` | `social_media` | 3 (array in records.json) | All posts in one file |

**Total records:** 31 raw records spanning January – March 2024.

---

## Intentional Aliases and Messiness

This is the core entity-resolution challenge. The following aliases appear across different source types and **must** be resolved to the same canonical entity by B7.

### Alias Group 1 — Rahul Sharma ⚠️ Most aliases

| Alias | Source | Record ID |
|---|---|---|
| `Rahul Sharma` | FIR | fir_001, fir_002 |
| `Rahul S.` | FIR | fir_002 (accused[1]) |
| `R. Sharma` | Police Report | pr_001 |
| `SHARMA R` | Police Report | pr_002 |
| `R. Sharma` | Transaction | txn_003 (to_account_holder) |
| `Rahul Sharma` | Transaction | txn_004 (to_account_holder) |
| `SHARMA R` | Transaction | txn_006 (from_account_holder) |
| `R. Sharma` | Surveillance | surv_001 |
| `Rahul Sharma` | Surveillance | surv_003 |
| `SHARMA R` | Surveillance | surv_004 |

**Resolution keys available:** shared phone `9876543210`, shared vehicle `MH-01-AB-1234`, shared bank account `HDFC-PRIV-1234`, shared PAN `ABCPS1234D`.

### Alias Group 2 — Priya Mehta

| Alias | Source | Record ID |
|---|---|---|
| `Priya Mehta` | FIR | fir_001, fir_003 |
| `Priya M.` | Police Report | pr_001 (known_associates) |
| `P. Mehta` | Police Report | pr_002 |
| `Priya Mehta` | Transaction | txn_001, txn_002 |
| `P. Mehta` | Transaction | txn_004 |
| `Priya M.` | Surveillance | surv_002 |
| `Priya M.` | Social Media | sm_002 (display_name) |

**Resolution keys available:** shared bank account `SBI-SAVE-5678`, CDR phone `8765432109`.

**Temporal corroboration:** `surv_002` (2024-02-14 12:30) and `sm_002` (2024-02-14 19:30) are on the same day at the same location (Hotel Blue Star, Bandra) — strong evidence these refer to the same person.

### Alias Group 3 — Devendra Khanna

| Alias | Source | Record ID |
|---|---|---|
| `Devendra Khanna` | FIR | fir_003 |
| `Dev Khanna` | FIR | fir_003 (alias field) |
| `D. Khanna` | Police Report | pr_001 |
| `Devendra Khanna` | Police Report | pr_002 |
| `D. Khanna` | Surveillance | surv_001 |
| `Devendra Khanna` | Surveillance | surv_003 |
| `Devendra Khanna` | Social Media | sm_003 |

**Resolution keys available:** shared phone `9988776655`, shared company affiliation (Khanna Enterprises Pvt Ltd across all sources).

### Alias Group 4 — Rajan Patel

| Alias | Source | Record ID |
|---|---|---|
| `Rajan Patel` | FIR | fir_002 |
| `R. Patel` | FIR | fir_002 (alias field) |
| `Rajan Patel` | Police Report | pr_002 |
| `R. Patel` | Vehicle Registry | veh_002 (registered_owner) |
| `Rajan Patel` | Transaction | txn_005 |
| `Rajan Patel` | Surveillance | surv_002 |

**Resolution keys available:** shared vehicle `DL-05-CD-5678`, shared phone `9123456789`.

### Alias Group 5 — Khanna Enterprises Pvt Ltd

| Alias | Source | Record ID |
|---|---|---|
| `Khanna Enterprises Pvt Ltd` | FIR | fir_001 |
| `Khanna Enterprises` | FIR | fir_003 (shortened) |
| `Khanna Enterprises Pvt Ltd` | Police Report | pr_001, pr_002 |
| `Khanna Enterprises Pvt Ltd` | Transaction | txn_001 |
| `Khanna Enterprises` | Transaction | txn_002 (shortened) |
| `Khanna Enterprises Pvt Ltd` | Vehicle | veh_003 |
| `Khanna Enterprises Pvt Ltd` | Social Media | pr_report_001, sm_003 |

**Resolution keys available:** shared bank account `SBI-CORP-9012`, CIN `U74999MH2018PTC123456`.

---

## Timeline of Key Events

```
2024-01-05   First call Rahul → Dev Khanna (cdr_001)
2024-01-08   Call Dev Khanna → Rahul (cdr_002)
2024-01-10   Khanna Ent. → Priya Mehta: INR 8L transfer (txn_001); Call Rahul → Priya (cdr_003)
2024-01-15   Rahul calls Rajan Patel (cdr_004); vehicle MH-01-AB-1234 seen at complainant office
2024-01-20   FIR/2024/001 filed — fraud complaint (fir_001)
2024-01-22   Call Priya → Khanna (cdr_005)
2024-01-25   Khanna Ent. → Priya Mehta: INR 3.2L transfer (txn_002)
2024-01-27   Priya → Rahul: INR 2L transfer (txn_003); Call Rahul → Khanna (cdr_006)
2024-01-28   Rahul meets Dev Khanna, Hotel Sunrise (surv_001); Call Rahul → Khanna (cdr_006)
2024-01-30   Khanna Ent. social media: MoU with Global Trading FZE (pr_report_001)
2024-02-01   Police progress report PR/AE/2024/012 (pr_001)
2024-02-03   Call Rahul → Khanna (cdr_007)
2024-02-05   Priya → Rahul: INR 4.5L transfer (txn_004)
2024-02-10   FIR/2024/029 filed — KYC fraud (fir_003); Call Rajan → Rahul (cdr_008)
2024-02-12   Call Rajan → Rahul (cdr_008)
2024-02-14   Priya meets Rajan at Hotel Blue Star (surv_002); Priya social media post Hotel Blue Star (sm_002)
2024-02-16   Devendra Khanna LinkedIn post (sm_003)
2024-02-20   Call Priya → Rajan (cdr_009)
2024-02-28   Rajan cash deposit INR 5.5L to Rahul's HDFC account (txn_005); FIR/2024/047 filed (fir_002)
2024-03-01   Rahul meets Devendra at Khanna Ent. office, Nariman Point (surv_003); Call Rahul → Khanna (cdr_010)
2024-03-02   Call Rahul → Khanna (cdr_010)
2024-03-05   FIR/2024/047 chargesheeted (fir_002 update)
2024-03-08   SHARMA R ATM withdrawal INR 40K HDFC Bandra (surv_004)
2024-03-10   Rahul wire transfer INR 9L to Global Trading FZE Dubai (txn_006)
2024-03-15   Consolidated police report PR/BD/2024/031 (pr_002)
```

---

## Answer Key

The machine-readable file `answer_key.json` contains:
- **`canonical_entities`** — all expected canonical entities with their aliases and resolution signals
- **`expected_relationships`** — all expected graph edges with evidence record IDs
- **`intentional_messiness_summary`** — quick-reference per alias group for reviewers

**B7 validation:** B7's resolution output should produce exactly the canonical entity groupings listed in `answer_key.json`. The answer key is the ground truth for H3.

---

## File Format for B2

Each record file (or array element in `records.json`) contains:

```json
{
  "record_id":    "string — unique per source type, stable",
  "occurred_at":  "ISO-8601 UTC — event time (never null in this dataset)",
  "payload":      { ... source-type-specific structured fields ... },
  "payload_text": "string — flattened text for NLP/LLM extraction"
}
```

B2's `SyntheticAdapter` reads each file and adds:
- `dataset: "synthetic_demo"` (fixed)
- `source_type`: derived from folder name (fir → "FIR", police_report → "police_report", cdr → "CDR", transactions → "transaction", vehicles → "vehicle_registry", surveillance → "surveillance", social_media → "social_media")
- `source_adapter_id: "synthetic_v1"` (fixed)
- `ingested_at`: timestamp of the read call

---

## Coverage Check (DOC1 §2 / DOC3 §2.2)

| DOC3 §2.2 source type | Folder | Covered |
|---|---|---|
| `FIR` | `fir/` | YES — 3 records |
| `police_report` | `police_report/` | YES — 2 records |
| `CDR` | `cdr/` | YES — 10 records |
| `transaction` | `transactions/` | YES — 6 records |
| `vehicle_registry` | `vehicles/` | YES — 3 records |
| `surveillance` | `surveillance/` | YES — 4 records |
| `social_media` | `social_media/` | YES — 3 records |
| `criminal_history` | — | Not included (no DOC1 requirement; can be added) |
| `org_registry` | — | Org data embedded in FIR/PR payloads instead |
| `rss` | — | Live adapter only (B3, not synthetic) |

---

## Constraints Satisfied

- **NFR6:** All data is entirely synthetic. No real individuals. No real law-enforcement data.
- **Contract Invariant 7:** Zero external network dependency — all files are local.
- **DOC3 §1.1:** All `record_id` values are unique within `synthetic_demo` dataset.
- **DOC3 §2.3:** `dataset` is always `"synthetic_demo"`, `mode` is `"batch"`.
- **H1 §11:** Deliberate aliases across at least two source types for 5 entity groups.
- **H1 §11:** Machine-readable answer key (`answer_key.json`) provided for B7/H3.
