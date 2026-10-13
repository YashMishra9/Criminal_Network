# DOC3 — Contracts & Interfaces
## AI-Powered Criminal Network Analysis System

**Status:** Draft — pending approval
**Depends on:** DOC1 (approved), DOC2 (approved)
**Precedes:** DOC4 — Build Plan

**Purpose:** This document is the binding interface contract between independently implemented components. A developer or AI coding agent implementing one component should be able to do so correctly having read only: `AGENTS.md`, the relevant sections of DOC1/DOC2, and this document — without needing to inspect another component's implementation. Where this document is silent or ambiguous, that is a defect to raise, not a gap to fill by guessing.

All JSON-like schemas below use TypeScript-style type notation for precision (`string`, `number`, `boolean`, `T[]`, `T | null`, `"literal"` unions). All timestamps are ISO-8601 UTC strings unless stated otherwise. All IDs are strings unless stated otherwise.

---

## 1. Common Data Models

These are the canonical shapes used throughout the system. Every component that produces or consumes one of these must conform exactly — do not invent parallel/renamed fields.

### 1.1 RawRecord

The normalized output of any Source Adapter; the sole input to Entity Extraction.

```typescript
RawRecord {
  record_id: string          // globally unique, stable, adapter-assigned
  dataset: "synthetic_demo" | "live_public"   // see Section 2
  source_type: string        // e.g. "FIR", "CDR", "transaction", "vehicle_registry",
                              // "surveillance", "social_media", "rss", "org_registry"
  source_adapter_id: string  // which adapter produced this, e.g. "synthetic_v1", "rss_public_v1"
  occurred_at: string | null // when the underlying event happened, if known (ISO-8601)
  ingested_at: string        // when the adapter fetched/emitted this record (ISO-8601)
  payload: object            // adapter-specific raw content (free-form; extraction reads this)
  payload_text: string | null // flattened text form of payload, for NLP/LLM convenience
}
```

**Invariants:**
- `record_id` is unique per `dataset`. Two records from different datasets may not share a `record_id`.
- `dataset` and `source_type` are set by the adapter and never altered downstream.
- `payload` is opaque to everything except the extraction logic that understands `source_type`.

### 1.2 Source Metadata (Adapter Descriptor)

Static description of a configured adapter, used for config/status reporting (not per-record).

```typescript
AdapterDescriptor {
  adapter_id: string
  source_type: string
  dataset: "synthetic_demo" | "live_public"
  mode: "batch" | "poll"
  enabled: boolean
  poll_interval_seconds: number | null   // required if mode == "poll"
  last_run_at: string | null
  last_run_status: "ok" | "error" | "never_run"
  last_error: string | null
}
```

### 1.3 Extracted Entity / Mention

Output of Entity Extraction; input to Entity Resolution. A "mention" is one occurrence of an entity in one record — not yet resolved to a canonical entity.

```typescript
EntityMention {
  mention_id: string          // unique per mention
  record_id: string           // the RawRecord this mention came from
  dataset: string              // inherited from the record
  entity_type: "Person" | "Phone" | "Vehicle" | "Location" | "Organization"
             | "BankAccount" | "Transaction" | "Event"
  raw_text: string             // the literal text/value extracted (e.g. "R. Sharma", "98XXXXXXXX")
  normalized_value: string | null  // extractor's best-effort normalization (e.g. E.164 phone)
  attributes: object           // type-specific extra fields (e.g. {plate_state: "MH"} for Vehicle)
  extraction_method: "spacy" | "regex" | "llm"
  confidence: number | null    // 0.0–1.0 if the method produces one; null if not applicable
}
```

```typescript
RelationshipMention {
  relationship_mention_id: string
  record_id: string
  dataset: string
  relationship_type: "CALLED" | "OWNS" | "USED" | "TRANSFERRED" | "VISITED"
                    | "MET" | "WORKS_FOR" | "ASSOCIATED_WITH" | "MENTIONED_IN" | "PART_OF"
  from_mention_id: string      // references EntityMention.mention_id
  to_mention_id: string
  occurred_at: string | null   // event time if the record specifies it; else null (falls back to record.occurred_at)
  attributes: object           // e.g. {duration_seconds: 340} for CALLED, {amount: 5000, currency: "INR"} for TRANSFERRED
  extraction_method: "spacy" | "regex" | "llm"
}
```

**Invariant:** Every `EntityMention` and `RelationshipMention` must trace back to exactly one `record_id`. Extraction never merges across records — that is Resolution's job.

### 1.4 Canonical Entity

The resolved, graph-level entity (maps to a Neo4j node — see Section 6).

**Decision (resolves prior ambiguity): `Transaction` is a first-class `CanonicalEntity`.** A transaction can be independently referenced by a `Case` (added as an item of interest) or a `Finding` (e.g., a rapid-transfer pattern), exactly like any other entity — it is not merely an internal graph-only node. It is therefore included in the `entity_type` enum below and follows the same resolution/provenance/evidence rules as every other entity type.

**`Case` is explicitly excluded from `entity_type` (resolves a second prior ambiguity).** A `Case` is a Case Workspace object — created directly by an investigator via `CaseWorkspace.create_case()` (Section 11), with its own `case_id`, lifecycle (`status`), and graph node (Section 6.1). It is never produced by Entity Extraction or Entity Resolution, is never a mention in a source record, and is never folded into `resolved_from`. There is exactly one representation of "Case" in this system — the Case Workspace object defined in Section 1.9 — and `CanonicalEntity`/`EntityMention` must never carry a second, parallel one.

```typescript
CanonicalEntity {
  entity_id: string             // stable graph identity, generated at first resolution
  entity_type: "Person" | "Phone" | "Vehicle" | "Location" | "Organization"
             | "BankAccount" | "Transaction" | "Event"
  dataset: string                // see Section 2.5 — resolution does not cross datasets by default
  display_name: string           // best-representative value for UI
  attributes: object             // merged/canonical attributes
  resolved_from: string[]        // list of mention_id values folded into this entity
  resolution_method: "exact_match" | "fuzzy_match" | "shared_attribute" | "embedding_similarity" | "manual"
  created_at: string
  updated_at: string
}
```

**Provenance path (canonical, exact — see Section 2.5 for the full rule):** `CanonicalEntity.resolved_from` → `ResolutionDecision.mention_ids` (+ parallel `source_record_ids`) → `RawRecord.record_id` → `Evidence.source_id`. This is the only provenance mechanism for entities; no second mechanism is used anywhere in the system.

### 1.5 Relationship (Graph Edge)

The resolved, graph-level relationship (maps to a Neo4j relationship — see Section 6).

```typescript
Relationship {
  relationship_id: string
  relationship_type: "CALLED" | "OWNS" | "USED" | "TRANSFERRED" | "VISITED"
                    | "MET" | "WORKS_FOR" | "ASSOCIATED_WITH" | "MENTIONED_IN" | "PART_OF"
  from_entity_id: string
  to_entity_id: string
  dataset: string
  attributes: object
  valid_from: string             // required — earliest known occurrence (ISO-8601)
  valid_to: string | null        // null if open-ended / not applicable
  evidence_ids: string[]         // Evidence.evidence_id[] — at least one required (see Section 9)
  created_at: string
  updated_at: string
}
```

**Invariant (hard rule, restated from DOC1/DOC2):** A `Relationship` with an empty `evidence_ids` array must never be written to the graph or returned by any API. See Section 15.

### 1.6 Evidence

```typescript
Evidence {
  evidence_id: string
  dataset: string
  source_id: string              // == RawRecord.record_id it was derived from
  source_type: string
  record_timestamp: string | null  // == RawRecord.occurred_at
  ingested_at: string             // == RawRecord.ingested_at
  snippet: string | null          // short human-readable excerpt, if applicable
  pointer: object | null          // adapter-specific pointer back to full original record
}
```

### 1.7 Resolution Decision

Records why mentions were (or were not) merged — satisfies FR10 (inspectable resolution), and is the **canonical, exact provenance mechanism for every `CanonicalEntity`** (see Section 2.5). `ResolutionDecision` is a persisted Neo4j node type (Section 6.1) — not an application-level log outside the graph — so it remains reachable by the Evidence/Provenance Resolver like everything else.

```typescript
ResolutionDecision {
  decision_id: string
  entity_id: string               // the resulting (or candidate) CanonicalEntity
  mention_ids: string[]           // mentions considered together in this decision
  source_record_ids: string[]     // RawRecord.record_id for each entry in mention_ids, same order/length —
                                   // this is what makes the entity → evidence path exact without
                                   // needing to persist EntityMention itself as a graph node
  outcome: "merged" | "rejected"
  method: "exact_match" | "fuzzy_match" | "shared_attribute" | "embedding_similarity" | "manual"
  matched_on: string[]            // e.g. ["phone_number", "name_similarity>0.85"]
  score: number | null            // similarity/confidence score if applicable
  decided_at: string
}
```

**Note on `EntityMention` persistence:** `EntityMention` objects (Section 1.3) are pipeline-transient — passed from Extraction to Resolution in-process — and are **not** independently persisted as Neo4j nodes. `ResolutionDecision.source_record_ids` is what makes their provenance recoverable after the fact without needing a separate mention store; this is a deliberate simplification, not an oversight.

### 1.8 Pattern / Finding

Output of Pattern Detection.

```typescript
Finding {
  finding_id: string
  dataset: string
  rule_id: string                 // which rule produced this, e.g. "bridge_entity_v1"
  rule_name: string                // human-readable, e.g. "Bridge Entity"
  subject_entity_ids: string[]     // entities involved
  subject_relationship_ids: string[]  // relationships involved, if applicable
  explanation: string              // plain-language, specific to this instance
  triggering_values: object        // the actual numbers/thresholds that fired, e.g. {call_count: 17, threshold: 10}
  evidence_ids: string[]           // required — see Section 9
  disclaimer: "This is an investigative lead, not evidence of wrongdoing."  // fixed literal, always present
  detected_at: string
}
```

**Storage / lifecycle (resolves prior ambiguity — `Finding` is a persisted Neo4j node, not ephemeral):** `Finding` is a persisted node type (Section 6.1), written by the Graph Write step of each Pattern Detection run — it is not recomputed on the fly per API request, and `finding_id` must remain stable and resolvable by later calls (e.g., `for_finding(finding_id)`, `GET /evidence?finding_id=`), which requires it to exist as durable graph data, not a transient in-memory result.

- **Identity/upsert key:** a `Finding`'s identity is the composite `(rule_id, dataset, subject_entity_ids sorted, subject_relationship_ids sorted)`. Each Pattern Detection run **upserts** on this key: if a `Finding` with the same key already exists, its `detected_at`, `explanation`, and `triggering_values` are updated in place (same `finding_id`); otherwise a new `Finding` node is created with a freshly generated `finding_id`. This keeps re-running detection (on-demand or scheduled, per DOC2 §10) idempotent rather than accumulating duplicate findings for the same underlying pattern.
- **Graph representation:** `Finding` connects to its subjects and its evidence as direct node-to-node relationships (no `EdgeRef` indirection needed for the *entity* side, since both `Finding` and `CanonicalEntity` are nodes):
  - `(:Finding)-[:CONCERNS]->(:CanonicalEntity)` for each `subject_entity_ids` entry.
  - `(:Finding)-[:CONCERNS]->(:EdgeRef)` for each `subject_relationship_ids` entry — this one *does* go through `EdgeRef`, because the subject is a `Relationship` (an edge), following the same rule as everywhere else a relationship needs to be pointed at (Section 6.5).
  - `(:Evidence)-[:SUPPORTS]->(:Finding)` — direct, since `Finding` is a node; this extends `SUPPORTS`'s existing use (previously only `Evidence → EdgeRef`) to cover any node-shaped thing evidence backs. See Section 6.2/6.5.

### 1.9 Case

```typescript
Case {
  case_id: string
  title: string
  status: "open" | "closed"
  dataset: string                  // the dataset scope this case was created within
  created_at: string
  updated_at: string
}
```

### 1.10 Note

```typescript
Note {
  note_id: string
  case_id: string
  text: string
  about_entity_id: string | null       // optional — one of these "about_*" may be set, or none
  about_edge_ref_id: string | null
  about_evidence_id: string | null
  created_at: string
}
```

**Invariant:** at most one of `about_entity_id` / `about_edge_ref_id` / `about_evidence_id` is non-null at a time (a note is general, or about exactly one specific thing).

### 1.11 EdgeRef

Pointer node type standing in for a `Relationship` wherever something needs to reference an edge as if it were a node (Neo4j relationships cannot be relationship-targets). **Exactly one `EdgeRef` exists per `Relationship`** — created once by the Graph Write Layer at relationship-creation time, then reused by both Evidence (`Evidence -[:SUPPORTS]-> EdgeRef`) and any number of Cases (`Case -[:INCLUDES_EDGE]-> EdgeRef`). See Section 6.5 for the full lifecycle rule.

```typescript
EdgeRef {
  edge_ref_id: string
  relationship_id: string          // the Relationship this points to
  from_entity_id: string           // denormalized for display convenience
  to_entity_id: string
  relationship_type: string
  created_at: string
}
```

### 1.12 Analytics Result

```typescript
AnalyticsResult {
  computed_at: string
  dataset: string
  as_of: string | null             // if computed over a temporal-filtered snapshot; null = full current graph
  centrality: {
    entity_id: string
    degree: number
    betweenness: number
    pagerank: number
  }[]
  communities: {
    entity_id: string
    community_id: string
  }[]
}
```

### 1.13 ID Uniqueness Scopes

Every identifier type below has an explicit, non-negotiable uniqueness scope. Implementers must not assume a different scope.

| ID | Scope | Notes |
|---|---|---|
| `record_id` | Unique **within `dataset`** | Set by the adapter; adapter-assigned IDs from different sources could otherwise collide, so scoping to `dataset` (not global) is required (Section 1.1). |
| `mention_id` | Globally unique | Assigned by Extraction; never persisted as a standalone graph node (Section 1.7), but still must not collide across records/datasets since it appears in `ResolutionDecision.mention_ids`. |
| `entity_id` | Globally unique | Assigned at first resolution. Never reused across datasets even though entities themselves don't cross datasets (Contract Invariant 2). |
| `relationship_id` | Globally unique | Assigned by the Graph Write Layer. |
| `evidence_id` | Globally unique | Assigned when an `Evidence` node is first materialized for a given `(source_id, dataset)` pair; the same `(source_id, dataset)` must resolve to the same `evidence_id` on repeated writes (idempotent), not a new one each time. |
| `decision_id` (`ResolutionDecision`) | Globally unique | Assigned by Entity Resolution. |
| `finding_id` | Globally unique | Assigned on first upsert of a given `(rule_id, dataset, subject_entity_ids, subject_relationship_ids)` key (Section 1.8); stable across re-detection of the same pattern instance. |
| `case_id` | Globally unique | Assigned by Case Workspace. |
| `note_id` | Globally unique | Assigned by Case Workspace. |
| `edge_ref_id` | Globally unique | Assigned by the Graph Write Layer; exactly one per `relationship_id` (Section 6.5) — so while `edge_ref_id` itself is a fresh unique value, the `(relationship_id)` it wraps is what must not be duplicated. |

**Rule of thumb:** everything the system itself generates (all IDs except `record_id`) is globally unique (e.g., UUIDv4) — `record_id` is the sole exception because it is adapter/source-assigned and only needs to be unique within the `dataset` it belongs to.

---

### 2.1 Dataset Identifiers

Exactly two values are valid system-wide. No component may introduce a third without a DOC2/DOC3 amendment:

- `"synthetic_demo"` — the guaranteed, controlled demo dataset.
- `"live_public"` — data from the optional public/live adapter.

### 2.2 Source Types (non-exhaustive, extensible via config — not a closed enum in code)

`"FIR"`, `"police_report"`, `"CDR"`, `"transaction"`, `"vehicle_registry"`, `"surveillance"`, `"social_media"`, `"criminal_history"`, `"org_registry"`, `"rss"`. New source types may be added by new adapters without changing this contract, provided they set `dataset` and `record_id` per Section 1.1.

### 2.3 Synthetic vs. Public/Live

| | `synthetic_demo` | `live_public` |
|---|---|---|
| Adapter mode | `batch` (`fetch_batch()`) | `poll` (`poll()`) |
| Contains | Fabricated demo data only | Public/open, ToS-compliant data only; never private individuals |
| Guaranteed available | Yes — always | No — optional, may be disabled |
| Default API/UI scope | Yes (default) | No — must be explicitly requested |

### 2.4 Timestamps

Every `RawRecord` carries both `occurred_at` (event time, may be null if unknown) and `ingested_at` (always set, adapter-assigned at fetch time). Downstream, `Relationship.valid_from` must be derived from `occurred_at` when available, falling back to `ingested_at` only if `occurred_at` is null — this fallback must be recorded by setting `Relationship.attributes.timestamp_is_fallback = true` so the frontend/Timeline can distinguish approximate from exact temporal placement.

### 2.4A `as_of` Semantics (Network Time Machine — binding rule for all components)

`as_of` is a relationship-level filter; entity visibility is *derived* from it, never filtered independently. Precisely:

1. **Relationships:** a relationship is visible at a given `as_of` if `valid_from <= as_of AND (valid_to IS NULL OR valid_to >= as_of)` (as already stated in Section 7 for Analytics — this is the one rule, referenced from there, not a separate one).
2. **Entities:** an entity is visible at a given `as_of` if **either** (a) it participates in at least one relationship that is visible at that `as_of` per rule 1, **or** (b) it has zero relationships at all in the dataset (an isolated entity is always shown regardless of `as_of` — there is nothing temporal to filter about it). An entity is never excluded by its own `created_at`/`updated_at` timestamp; entities do not carry an independent temporal-visibility rule beyond rule 2.
3. This is a **query-time filter**, not a precomputed snapshot (per DOC2 §11) — every component (Graph/`GET /graph`, Analytics, Ask-the-Network's underlying queries where `as_of` is supplied) implements the identical rule above, not a component-specific interpretation.

This is the exact rule the Graph/Analytics implementation and the Frontend's Timeline component must agree on — there is no second, alternative interpretation.

### 2.5 Provenance Requirements

Every `CanonicalEntity`, `Relationship`, and `Finding` must be traceable to at least one `Evidence`, and every `Evidence` must be traceable to exactly one `RawRecord` via `source_id`. No component may fabricate an `Evidence` record without a backing `RawRecord`.

**Canonical entity provenance path (exact, the only mechanism — do not invent a second one):**
```
CanonicalEntity.resolved_from (mention_ids)
   → ResolutionDecision (matched by entity_id, containing the same mention_ids + parallel source_record_ids)
   → RawRecord (via source_record_ids, one per mention)
   → Evidence (Evidence.source_id == RawRecord.record_id, same dataset)
```
Retrieval is via `EvidenceResolver.for_entity(entity_id)` (Section 9.1), which performs exactly this traversal: find the entity's `ResolutionDecision`(s), read `source_record_ids`, and return the matching `Evidence` nodes (creating/looking up `Evidence` by `source_id` + `dataset` if not already materialized). No other path to an entity's evidence exists.

### 2.6 Dataset Isolation Rules

- All writes (entities, relationships, evidence, findings) carry the `dataset` of the `RawRecord`(s) they were derived from.
- Entity Resolution matches candidates **only within the same `dataset`** by default (Section 5). Cross-dataset resolution is out of scope unless a future contract amendment defines it.
- All read APIs default to `dataset=synthetic_demo` unless the caller explicitly requests otherwise (Section 12).
- The live adapter writes only when `AdapterDescriptor.enabled == true` for the `live_public` adapter; this is a deployment-time configuration value, not something any pipeline component decides at runtime.

---

## 3. Source Adapter Interface

Every adapter (synthetic or live) implements this interface. This is the seam that keeps ingestion source-agnostic per DOC2 §6.

```typescript
interface SourceAdapter {
  descriptor(): AdapterDescriptor

  // Required for mode == "batch". Returns all available records in one call.
  // Must be idempotent: calling it again returns the same records (same record_id values)
  // unless the underlying synthetic dataset itself changed.
  fetch_batch(): RawRecord[]

  // Required for mode == "poll". Returns only records new since the given cursor.
  // Must not return records already returned by a prior poll() call with an equal-or-later cursor.
  poll(cursor: string | null): { records: RawRecord[], next_cursor: string }
}
```

**Cursor/checkpoint behavior:** `poll()` cursors are opaque strings owned entirely by the adapter (e.g., a timestamp, an API-provided pagination token). The Ingestion Orchestrator persists whatever `next_cursor` it receives and passes it back unchanged on the next call. No other component interprets the cursor's internal format.

**Error behavior:**
- `fetch_batch()` on the synthetic adapter must not raise for missing/malformed bundled files without first attempting a clear, loggable failure — but since this is the guaranteed path, a broken synthetic adapter is treated as a build-blocking defect, not a runtime-degradation case.
- `poll()` on the live adapter must catch all network/parsing errors internally and return `{ records: [], next_cursor: <unchanged> }` rather than raising — a failed poll is silent to the rest of the pipeline (logged, not thrown) per DOC2 §6.3. The Ingestion Orchestrator must not treat an empty poll result as an error condition.
- Adapters must update their own `AdapterDescriptor.last_run_status` / `last_error` on every call (success or failure), so status is inspectable via the ingestion status endpoint (Section 12.10) without adapters throwing exceptions across the orchestration boundary.

---

## 4. Entity Extraction Contract

**Input:** one `RawRecord` at a time (stateless — no access to other records or the graph).

**Output:**
```typescript
ExtractionResult {
  record_id: string
  entities: EntityMention[]
  relationships: RelationshipMention[]
}
```

**Entity types produced:** exactly the `entity_type` enum in Section 1.3 — no others.

**Mention representation:** every `EntityMention`/`RelationshipMention` must set `record_id`, `dataset`, and `extraction_method` — these are non-optional regardless of which method (spaCy/regex/LLM) produced the mention.

**Relationship candidates:** a `RelationshipMention` may only reference `mention_id` values present in the same `ExtractionResult.entities` array (extraction never references mentions from other records).

**Provenance:** extraction must not discard `record_id` at any point — every mention it emits carries it forward unchanged from the input `RawRecord`.

**LLM use:** when `extraction_method == "llm"`, the extractor must have first attempted spaCy/regex and only invoked the LLM for genuinely ambiguous cases (per DOC2 §7) — this is a process expectation, not a machine-checkable one, but `extraction_method` on the mention makes downstream auditing of LLM-reliance possible.

---

## 5. Entity Resolution Contract

**Matching inputs:** a set of `EntityMention` objects, scoped to a single `dataset` (Section 2.6). In batch mode this is the full candidate set for that dataset; in incremental mode (live) this is one new mention plus the existing `CanonicalEntity` set for that dataset.

**Candidate representation:** resolution operates over pairs/groups of `EntityMention` (batch) or `(EntityMention, CanonicalEntity)` (incremental), and internally computes a `matched_on` list and `score` before deciding.

**Confidence/decision representation:** every comparison that results in a merge or an explicit rejection above a configurable review threshold produces a `ResolutionDecision` (Section 1.7). Comparisons far below any matching threshold need not each produce a stored decision (to avoid unbounded storage of non-matches), but the applied thresholds must be configuration, not hardcoded (per DOC2 §8).

**Resolution rationale:** `CanonicalEntity.resolved_from` and the associated `ResolutionDecision` records together must let any caller answer "which raw mentions make up this entity, and why were they merged" without consulting resolution source code.

**Batch vs. incremental behavior:**
| | Batch (`synthetic_demo`, primary) | Incremental (`live_public`, best-effort) |
|---|---|---|
| Candidate pool | All mentions for the dataset, compared pairwise/clustered | New mention compared only against existing `CanonicalEntity` records in the same dataset |
| Guarantee | Correctness target for the demo | Best-effort; documented as such (DOC1 FR11) — a live mention that fails to match anything becomes a new `CanonicalEntity` rather than blocking |
| Output | Full `CanonicalEntity` set + `ResolutionDecision` log for the dataset | Incremental additions/updates to the existing `CanonicalEntity` set for `live_public` |

**Invariant:** resolution never merges mentions across `dataset` values (Section 2.6).

---

## 6. Graph Schema Contract (Neo4j)

### 6.1 Node Types

**`CanonicalEntity` node types** (produced by Extraction → Resolution → Graph Write; see Section 1.4):

| Label | Required properties | Notes |
|---|---|---|
| `Person` | `entity_id`, `dataset`, `display_name`, `created_at`, `updated_at` | + `attributes.*` as applicable |
| `Phone` | `entity_id`, `dataset`, `display_name` (normalized number), `created_at`, `updated_at` | |
| `Vehicle` | `entity_id`, `dataset`, `display_name` (plate), `created_at`, `updated_at` | |
| `Location` | `entity_id`, `dataset`, `display_name`, `created_at`, `updated_at` | |
| `Organization` | `entity_id`, `dataset`, `display_name`, `created_at`, `updated_at` | |
| `BankAccount` | `entity_id`, `dataset`, `display_name` (masked), `created_at`, `updated_at` | |
| `Transaction` | `entity_id`, `dataset`, `display_name`, `attributes.amount`, `attributes.currency`, `created_at`, `updated_at` | first-class `CanonicalEntity` (Section 1.4) — carries evidence and may be referenced directly by a `Case` or `Finding`, not just implied by a `TRANSFERRED` edge |
| `Event` | `entity_id`, `dataset`, `display_name`, `occurred_at` | |

**Workspace / structural / derived node types** (never produced directly by Extraction; `Case`/`Note`/`EdgeRef` are Case Workspace objects, `Evidence`/`ResolutionDecision`/`Finding` are provenance and pattern-detection infrastructure — none of these are `CanonicalEntity` and none carry an `entity_type`):

| Label | Required properties | Notes |
|---|---|---|
| `Case` | `case_id`, `title`, `status`, `dataset`, `created_at`, `updated_at` | see Section 11. Created only via `CaseWorkspace.create_case()` — never by Extraction/Resolution. |
| `Evidence` | `evidence_id`, `dataset`, `source_id`, `source_type`, `ingested_at` | see Section 9 |
| `Note` | `note_id`, `case_id`, `text`, `created_at` | see Section 11 |
| `EdgeRef` | `edge_ref_id`, `relationship_id`, `from_entity_id`, `to_entity_id`, `relationship_type`, `created_at` | see Section 6.5 and Section 11 — **exactly one `EdgeRef` per `Relationship`**, created by the Graph Write Layer at relationship-creation time (see 6.5 for full semantics) |
| `ResolutionDecision` | `decision_id`, `entity_id`, `mention_ids`, `source_record_ids`, `outcome`, `method`, `decided_at` | see Section 1.7 — the canonical entity-provenance mechanism |
| `Finding` | `finding_id`, `dataset`, `rule_id`, `explanation`, `disclaimer`, `detected_at` | see Section 1.8 — persisted, upserted per detection run; never a `CanonicalEntity` |

### 6.2 Relationship Types

| Type | Endpoints | Required properties |
|---|---|---|
| `CALLED` | `Person\|Phone → Person\|Phone` | `relationship_id`, `dataset`, `valid_from`, evidence reachable via its `EdgeRef` (see 6.5) |
| `OWNS` | `Person → Vehicle\|BankAccount\|Phone` | same as above |
| `USED` | `Person → Phone\|Vehicle` | same |
| `TRANSFERRED` | `BankAccount → BankAccount` (via `Transaction` node, or direct — see 6.3) | same + `attributes.amount`, `attributes.currency` |
| `VISITED` | `Person → Location` | same |
| `MET` | `Person → Person` | same |
| `WORKS_FOR` | `Person → Organization` | same |
| `ASSOCIATED_WITH` | any → any (fallback/general) | same |
| `MENTIONED_IN` | any entity → `Evidence` (direct source mention — a distinct concept from evidence-*supporting* a relationship, which uses `SUPPORTS`/`EdgeRef`, Section 6.5) | `relationship_id`, `dataset` |
| `PART_OF` | any → `Case`/`Organization` | same |
| `SUPPORTED_BY` | *(retired — not implemented)* | Superseded entirely by `SUPPORTS` (`Evidence → EdgeRef`, Section 6.5). Does not exist as a relationship type anywhere in the implementation. |
| `INCLUDES_ENTITY` | `Case → entity` (any `CanonicalEntity` type) | see Section 11 |
| `INCLUDES_EDGE` | `Case → EdgeRef` | see Section 6.5/11 — points at the single shared `EdgeRef` for the relevant `Relationship`, never a case-specific copy |
| `INCLUDES_EVIDENCE` | `Case → Evidence` | see Section 11 |
| `ABOUT` | `Note → entity\|EdgeRef\|Evidence` | optional, see Section 11 |
| `RESOLVED_FROM` | `CanonicalEntity → ResolutionDecision` | node-to-node (both are Neo4j nodes, so this is a direct relationship, no indirection needed) — see Section 1.7/2.5 |
| `BASED_ON` | `ResolutionDecision → Evidence` | node-to-node, direct — completes the entity provenance path from Section 2.5 |
| `SUPPORTS` | `Evidence → EdgeRef` **or** `Evidence → Finding` | see Section 6.5 (relationships) and Section 1.8 (findings) — the one mechanism by which evidence backs anything, whether the target is edge-shaped (via `EdgeRef`) or node-shaped (`Finding`, direct) |
| `CONCERNS` | `Finding → CanonicalEntity` (direct) or `Finding → EdgeRef` (for a subject relationship) | see Section 1.8 — links a `Finding` to what it's about |

### 6.3 Note on `TRANSFERRED`

Implementers may model a transfer either as a direct `TRANSFERRED` relationship between two `BankAccount` nodes carrying `amount`/`currency`, or via an intermediate `Transaction` node (`BankAccount -[:PART_OF]-> Transaction <-[:PART_OF]- BankAccount`) when a transaction needs its own evidence distinct from the account relationship. **Decision for this project: use the direct `TRANSFERRED` relationship as the default**; the `Transaction` node type exists in the schema for cases where a single transaction needs to be referenced independently (e.g., from a `Case` or `Finding`) — implementers should not build both paths for every transfer.

### 6.4 Required Properties Summary (every domain relationship)

Every relationship of a domain type (`CALLED`, `OWNS`, `USED`, `TRANSFERRED`, `VISITED`, `MET`, `WORKS_FOR`, `ASSOCIATED_WITH`, `PART_OF`) must have `relationship_id`, `dataset`, `valid_from`, **and**:
- exactly one corresponding `EdgeRef` node (created by the Graph Write Layer at the same time as the relationship — Section 6.5), **and**
- at least one `Evidence` node supporting that `EdgeRef` via `Evidence -[:SUPPORTS]-> EdgeRef`.

`SUPPORTED_BY` is retired (Section 6.2) and must not appear as an active implementation relationship type anywhere — the mechanism above (`EdgeRef` + `SUPPORTS`) is the sole, authoritative way a domain relationship is evidence-backed. A relationship missing its `EdgeRef`, or whose `EdgeRef` has no incoming `SUPPORTS` edge, must be rejected by the Graph Write Layer (Section 15).

### 6.5 Evidence / EdgeRef Structure (and EdgeRef Lifecycle — resolves prior ambiguity)

**The problem this section resolves:** Neo4j relationships cannot be the target of another relationship, so nothing can point directly *at* a `CALLED`/`OWNS`/etc. edge. `EdgeRef` is the node-shaped stand-in that both Evidence and Case Workspace point at instead. Both uses must agree on exactly one `EdgeRef`, or two independently-built components (Evidence, Case Workspace) will create incompatible duplicates.

**Rule: `EdgeRef` is a single, reusable pointer per `Relationship` — a 1:1 mapping, not one-per-consumer.**

- The **Graph Write Layer** creates exactly one `EdgeRef` at the moment it creates a `Relationship` (same transaction), keyed by `relationship_id`. No other component ever creates an `EdgeRef`.
- **Evidence supports the underlying `Relationship`, via its `EdgeRef`** — not a case-specific copy: `(:Evidence)-[:SUPPORTS]->(:EdgeRef {relationship_id, ...})`. This happens once, at relationship-creation time, as part of the same write that attaches evidence to the new relationship.
- **Case Workspace reuses the same `EdgeRef`** when an investigator adds that relationship to a case: `(:Case)-[:INCLUDES_EDGE]->(:EdgeRef {relationship_id, ...})` — the *existing* `EdgeRef` for that `relationship_id`, looked up by `relationship_id`, never a newly-created one. Many `Case` nodes may point `INCLUDES_EDGE` at the same `EdgeRef` (a relationship can be added to multiple cases); this is fine and expected.
- **Consequence:** `CaseWorkspace.add_relationship()` (Section 11) never creates an `EdgeRef` — it only creates the `INCLUDES_EDGE` edge. If no `EdgeRef` exists yet for the given `relationship_id` (which should not happen if the Graph Write Layer invariant above is followed), this is a data-integrity error, not a case for Case Workspace to silently create one.

**Structure:**
```
(:Evidence)-[:SUPPORTS]->(:EdgeRef {relationship_id, from_entity_id, to_entity_id, relationship_type})
(:Case)-[:INCLUDES_EDGE]->(same :EdgeRef)
```
**Clarification/correction to DOC2 wording:** DOC2 described evidence attaching directly to a relationship via `SUPPORTED_BY`; the precise, implementable mechanism is `Evidence -[:SUPPORTS]-> EdgeRef` as defined here, reusing the same pointer-node pattern DOC2 §13.1 introduced for the Case Workspace — one mechanism, not two. All prior DOC2/DOC3 references to `SUPPORTED_BY` attaching to a relationship should be read as this mechanism; `SUPPORTED_BY` itself is retired from the schema (Section 6.2).

Every API response that includes a `Relationship` (Section 1.5) resolves its `evidence_ids` by: `Relationship.relationship_id` → its single `EdgeRef` → `SUPPORTS` incoming edges → `Evidence`.

### 6.6 Temporal Properties

`valid_from` (required) and `valid_to` (optional, nullable) on every domain relationship, per Section 2.4. `occurred_at` (nullable) on `Event` and `Transaction` nodes.

### 6.7 Dataset Properties

`dataset` is a required property on every node and relationship type listed above except pure structural/pointer types that don't independently need dataset scoping (`SUPPORTS`, `ABOUT`, `INCLUDES_*` — these inherit scope from the `Case` or `Evidence`/entity they connect).

---

## 7. Analytics Contract

**Supported algorithms:** degree centrality, betweenness centrality, PageRank, community detection (Louvain or equivalent), shortest path.

**Input:**
```typescript
AnalyticsRequest {
  dataset: string           // required, no cross-dataset analytics by default
  as_of: string | null      // optional temporal filter (Section 2.4); null = full current graph
  algorithms: ("degree" | "betweenness" | "pagerank" | "community" | "shortest_path")[]
  shortest_path_from: string | null   // entity_id, required only if "shortest_path" requested
  shortest_path_to: string | null
}
```

**Output:** `AnalyticsResult` (Section 1.12), plus, when `shortest_path` was requested:
```typescript
ShortestPathResult {
  found: boolean
  path_entity_ids: string[]      // ordered
  path_relationship_ids: string[]
}
```

**Graph snapshot/as-of semantics:** governed entirely by Section 2.4A (the single, binding `as_of` rule for relationships and entities) — this is a query-time filter, not a precomputed snapshot.

**Dataset scoping:** analytics never mixes `synthetic_demo` and `live_public` in one computation unless a future contract explicitly adds a combined mode.

---

## 8. Pattern Detection Contract

**Rule interface:**
```typescript
interface PatternRule {
  rule_id: string
  rule_name: string
  evaluate(dataset: string, as_of: string | null): Finding[]
}
```
Each rule is independently pluggable and reads only from the graph + `AnalyticsResult` — never from another rule's output (rules do not chain).

**Finding structure:** exactly `Finding` (Section 1.8) — no rule may omit `evidence_ids`, `explanation`, or `disclaimer`.

**Persistence:** `evaluate()` itself is a pure read/compute step and returns `Finding[]` in memory — it does not write to Neo4j directly. A separate Graph Write step (invoked once per detection run, after all rules have run) **upserts** each returned `Finding` using the identity key defined in Section 1.8 (`rule_id, dataset, subject_entity_ids, subject_relationship_ids`), creating the `CONCERNS` and `SUPPORTS` relationships described there. This mirrors how the rest of the pipeline separates computation from graph writes (Graph Write Layer, DOC2 §3) and keeps `PatternRule` implementations simple and testable in isolation.

**Explanation:** must be a specific, instance-level sentence (e.g., "17 calls between these two numbers over 4 days, exceeding the 10-call/7-day threshold"), not a generic rule description.

**Evidence references:** `Finding.evidence_ids` must resolve to `Evidence` records that back the specific `subject_entity_ids`/`subject_relationship_ids` named in the finding — not arbitrary evidence from the dataset.

**Investigative-lead disclaimer:** every `Finding` carries the fixed literal string defined in Section 1.8, unmodified. No rule, API layer, or frontend component may omit or reword this disclaimer when displaying a finding.

---

## 9. Evidence / Provenance Contract

### 9.1 Retrieval

Any component needing evidence for a `Relationship` or `Finding` calls the Evidence/Provenance Resolver (DOC2 §3, cross-cutting) rather than querying `Evidence` nodes directly, so the retrieval logic (including the `EdgeRef`/`SUPPORTS` traversal in Section 6.5) lives in one place.

```typescript
interface EvidenceResolver {
  for_entity(entity_id: string): Evidence[]    // via ResolutionDecision.source_record_ids — see Section 2.5
  for_relationship(relationship_id: string): Evidence[]   // via the relationship's single EdgeRef — see Section 6.5
  for_finding(finding_id: string): Evidence[]  // via direct Evidence -[:SUPPORTS]-> Finding (node-to-node, no EdgeRef needed — see Section 1.8)
  for_resolution_decision(decision_id: string): Evidence[]   // via decision.source_record_ids directly
  for_case_item(case_id: string, item_type: "entity"|"edge_ref"|"evidence", item_id: string): Evidence[]
}
```

### 9.2 Required Provenance Fields

Every `Evidence` object returned by the resolver must include, at minimum, `source_id`, `source_type`, and `dataset` — `record_timestamp`, `snippet`, and `pointer` are included when available but may be null.

### 9.3 What Qualifies as Evidence

A `RawRecord` (or a specific mention/portion of one) that was actually used to derive the relationship or finding in question. Evidence may never be synthesized after the fact to justify a claim that didn't originate from that record — the causal direction is always record → extraction → resolution/graph-write → (optionally) pattern detection, never the reverse.

### 9.4 Evidence Through APIs

Any API response (Section 12) that includes a `Relationship` or `Finding` object includes either the full `Evidence[]` inline or a stable `evidence_ids` list plus a dedicated `GET /evidence/{relationship_id|finding_id}` the frontend can call — never a relationship/finding with no way to reach its evidence.

---

## 10. Ask-the-Network Contract

**NL question input:**
```typescript
AskRequest {
  question: string
  dataset: string        // defaults to "synthetic_demo" if omitted (Section 2.6)
  as_of: string | null
}
```

**Generated Cypher representation (internal, not returned raw to the frontend):**
```typescript
GeneratedQuery {
  cypher: string
  parameters: object
  generated_by: "llm"
}
```

**Validation requirements (must all pass before execution):**
1. Query must be read-only — no `CREATE`, `MERGE`, `SET`, `DELETE`, `REMOVE`. Reject otherwise.
2. **`CALL` / any procedure invocation is forbidden outright** — this includes read-only procedures (e.g., `apoc.*`, `gds.*`, or any other procedure library), not just mutating ones. No procedure is whitelisted in this version of the contract. A future contract amendment may explicitly whitelist a specific, named procedure for a specific purpose; until then, the validator rejects any query containing a `CALL` clause unconditionally.
3. Only the following Cypher constructs are permitted: `MATCH`, `OPTIONAL MATCH`, `WHERE`, `RETURN`, `WITH`, `ORDER BY`, `LIMIT`, `SKIP`, path functions (e.g. `shortestPath()`), and standard comparison/boolean/string predicate functions. Anything else causes rejection.
4. Query must reference only node labels/relationship types defined in Section 6.
5. Query must include a `dataset` filter matching `AskRequest.dataset` on all matched nodes/relationships (or the validator injects it) — cross-dataset leakage through Ask-the-Network is not permitted.
6. Query must complete within a bounded timeout (configurable); on timeout, treat as a failed generation (LLM-unavailable-style handling below), not a partial result.

A query failing any check is never executed; the service returns a typed `validation_failed` result (not a narrated apology invented by the LLM).

**Allowed query behavior:** exactly the read-only construct set enumerated in requirement 3 above, scoped to the requesting `dataset` — nothing broader.

**Query result structure:**
```typescript
GraphQueryResult {
  entities: CanonicalEntity[]
  relationships: Relationship[]
  paths: { entity_ids: string[], relationship_ids: string[] }[]
}
```

**Evidence attachment:** every `Relationship` in `GraphQueryResult.relationships` has its `evidence_ids` populated via the Evidence/Provenance Resolver (Section 9) before narration.

**Narration input/output:**
```typescript
NarrationInput {
  question: string
  query_result: GraphQueryResult    // already evidence-attached
}
NarrationOutput {
  narration: string     // must only describe entities/relationships/evidence present in query_result
}
```
The LLM call producing `NarrationOutput` receives only `query_result` as factual grounding — it is not given the freedom to consult the graph independently or introduce entities not present in the input.

**LLM-unavailable behavior:**
```typescript
AskResponse =
  | { status: "ok", narration: string, path: GraphQueryResult, evidence: Evidence[] }
  | { status: "llm_unavailable", message: string }
  | { status: "validation_failed", reason: string }
  | { status: "no_result", message: string }   // valid query, empty result
```
Per DOC2 §12A: on LLM failure at either the query-generation or narration step, the service returns `status: "llm_unavailable"` — it never falls back to presenting a raw, un-narrated query result as if it were a complete answer, and never fabricates a narration.

---

## 11. Case Workspace Contract

Data shapes: `Case` (1.9), `Note` (1.10), `EdgeRef` (1.11) — as defined in Section 1, unchanged here.

**Case associations:**
```typescript
interface CaseWorkspace {
  create_case(title: string, dataset: string): Case
  add_entity(case_id: string, entity_id: string): void        // creates INCLUDES_ENTITY; requires entity.dataset == case.dataset
  remove_entity(case_id: string, entity_id: string): void
  add_relationship(case_id: string, relationship_id: string): EdgeRef
    // looks up the *existing* EdgeRef for relationship_id (created by the Graph Write Layer
    // at relationship-creation time — see Section 6.5) and creates INCLUDES_EDGE to it.
    // Never creates a new EdgeRef. Requires relationship.dataset == case.dataset.
  remove_relationship(case_id: string, edge_ref_id: string): void
  add_evidence(case_id: string, evidence_id: string): void     // creates INCLUDES_EVIDENCE; requires evidence.dataset == case.dataset
  add_note(case_id: string, text: string, about?: { type: "entity"|"edge_ref"|"evidence", id: string }): Note
    // Note inherits case.dataset implicitly (Note has no independent dataset field — see 1.10);
    // if `about` is given, the referenced item must belong to the same dataset as the case.
  generate_summary(case_id: string): CaseSummaryResult
}
```

**Dataset isolation (hard requirement — see Contract Invariant 11 in Section 15):** every entity, relationship (via its `EdgeRef`), and evidence item added to a case must share the case's `dataset`. Any attempt to associate an item from a different `dataset` is rejected with `error.type: "dataset_isolation_violation"` (Section 13) — this is enforced by `CaseWorkspace` before any write, not left to the caller to check. Notes have no independent `dataset` field; they belong to their case's dataset by construction, and a note's optional `about` target must likewise share that dataset.

**Summary generation:**
```typescript
CaseSummaryResult =
  | { status: "ok", summary: string, generated_at: string }
  | { status: "llm_unavailable", message: string }
```
The summary is generated from the case's associated entities/relationships/notes, each with evidence resolved via Section 9 — the LLM narrates this assembled context; it is not given open-ended access to the full graph.

**Evidence linkage:** every entity/relationship added to a case remains linked to its original `Evidence` through the normal graph structure (Section 6.5) — a case does not duplicate or re-derive evidence, it references what already exists.

---

## 12. Frontend ↔ Backend API Contracts

All endpoints are prefixed `/api/v1`. All list endpoints support `dataset` (default `"synthetic_demo"`) and, where temporally meaningful, `as_of`.

### 12.1 `GET /entities/search?q=&dataset=&entity_type=`
Response: `{ results: CanonicalEntity[] }`

### 12.2 `GET /entities/{entity_id}`
Response: `{ entity: CanonicalEntity, resolution: ResolutionDecision[] }` or `404`.

### 12.3 `GET /entities/{entity_id}/relationships?dataset=&as_of=`
Response: `{ relationships: (Relationship & { evidence: Evidence[] })[] }`

### 12.4 `GET /graph?dataset=&as_of=&entity_types=&relationship_types=&community=&pattern=`
Response: `{ entities: CanonicalEntity[], relationships: Relationship[] }` (relationships include `evidence_ids`, not full evidence — fetched separately via 12.7 on demand for performance). `as_of` filtering follows Section 2.4A exactly (entity visibility derived from relationship visibility, plus always-shown isolated entities).

### 12.5 `GET /analytics?dataset=&as_of=&algorithms=`
Request maps to `AnalyticsRequest` (Section 7). Response: `AnalyticsResult`.

### 12.6 `GET /patterns?dataset=&as_of=`
Response: `{ findings: Finding[] }` — reads persisted `Finding` nodes (Section 1.8), filtered to those whose subjects are visible at `as_of` per Section 2.4A. Does not trigger a new detection run; detection runs separately (on-demand or scheduled, DOC2 §10) and upserts into the graph.

### 12.7 `GET /evidence?entity_id=|relationship_id=|finding_id=|decision_id=`
Response: `{ evidence: Evidence[] }`

### 12.8 `POST /ask`
Request: `AskRequest`. Response: `AskResponse` (Section 10).

### 12.9 Case Workspace
- `POST /cases` — body `{ title: string, dataset: string }` → `Case`
- `GET /cases/{case_id}` → `{ case: Case, entities: CanonicalEntity[], edge_refs: EdgeRef[], evidence: Evidence[], notes: Note[] }`
- `POST /cases/{case_id}/entities` — body `{ entity_id: string }` → `204`
- `POST /cases/{case_id}/relationships` — body `{ relationship_id: string }` → `EdgeRef`
- `POST /cases/{case_id}/notes` — body `{ text: string, about?: {...} }` → `Note`
- `GET /cases/{case_id}/summary` → `CaseSummaryResult`

### 12.10 Ingestion / Adapter Status
- `POST /ingestion/run?adapter_id=` — triggers `fetch_batch()`/`poll()` for the named adapter (primarily for the synthetic adapter in demo setup; also usable for a manual live-adapter run). Response: `{ status: "ok"|"error", records_ingested: number, message: string | null }`
- `GET /ingestion/status` → `{ adapters: AdapterDescriptor[] }` — reports all configured adapters, including `live_public` if configured, so the frontend/operator can see `enabled`, `last_run_status`, etc., without the live adapter being a demo dependency.

---

## 13. Error Contracts

All API error responses use a consistent envelope:

```typescript
ErrorResponse {
  error: {
    type: "not_found" | "validation_error" | "llm_unavailable" | "dataset_isolation_violation"
        | "graph_unavailable" | "internal_error"
    message: string
    details: object | null
  }
}
```

| HTTP status | `error.type` | When |
|---|---|---|
| 404 | `not_found` | Entity/case/relationship id doesn't exist |
| 400 | `validation_error` | Malformed request, or (Ask-the-Network) generated query failed validation |
| 503 | `llm_unavailable` | Any LLM-dependent call failed per Section 10/12A degradation model |
| 400 | `dataset_isolation_violation` | A request attempted to reference entities/relationships across `dataset` values without an explicit, supported cross-dataset operation |
| 503 | `graph_unavailable` | Neo4j unreachable |
| 500 | `internal_error` | Unclassified server error |

**Rule (no partial-success ambiguity):** if any required sub-operation behind an endpoint fails (e.g., evidence lookup fails while assembling a relationship response), the endpoint returns a non-2xx `ErrorResponse` (Section 13 table) — it never returns 200 with silently-omitted data. An empty array or null field in a 200 response always means "genuinely empty/absent," never "a lookup failed." If a specific endpoint genuinely needs to report partial success in the future (e.g., "9 of 10 records ingested"), that requires an explicit, separately-defined response schema for that endpoint — no endpoint may improvise an ad hoc partial-failure shape.

---

## 14. LLM Interface Contract

```typescript
interface LLMClient {
  generate(prompt: string, context: object, options?: { timeout_ms?: number }): LLMResult
}

LLMResult =
  | { status: "ok", text: string }
  | { status: "unavailable", reason: "timeout" | "provider_error" | "rate_limited" }
```

**Contract rules:**
- No caller of `LLMClient.generate` may treat `status: "unavailable"` as anything other than a typed failure requiring the degradation behavior defined for that caller (Sections 10, 11, and DOC2 §12A). Silently retrying indefinitely, blocking the request, or substituting fabricated text are all contract violations.
- The concrete provider (model name, API endpoint, credentials) is resolved entirely inside the `LLMClient` implementation via configuration — no other component may reference a provider-specific detail.
- Every call site must pass `context` explicitly (never rely on implicit/global state) — this keeps prompts reconstructable and testable.

---

## 15. Contract Invariants

These rules apply across every component and must never be violated by any implementation, track, or task:

1. **No relationship or finding without evidence.** `Relationship.evidence_ids` and `Finding.evidence_ids` must be non-empty before either is written to the graph or returned by any API.
2. **No cross-dataset merging.** Entity Resolution, Analytics, and Ask-the-Network never combine `synthetic_demo` and `live_public` data within a single result unless a future, explicit contract amendment defines a combined mode.
3. **The LLM never originates a factual claim.** Every LLM output that reaches the user is either (a) a Cypher query subject to validation before execution, or (b) a narration/summary constrained to data already retrieved from Neo4j and passed in as context.
4. **The LLM's absence never blocks core functionality.** Ingestion, extraction (via spaCy/regex), graph construction, analytics, and pattern detection all function with the LLM unavailable. Only Ask-the-Network's LLM-driven steps and case-summary generation degrade, and they degrade to an explicit typed status, never a fabricated result.
5. **Every flagged pattern carries the investigative-lead disclaimer, unmodified, every time it is displayed or returned.**
6. **Provenance is queryable graph structure, not a side log.** No component may store evidence/provenance information anywhere the Evidence/Provenance Resolver cannot reach it.
7. **The live adapter is never a dependency of the core demo.** Any endpoint, feature, or test that requires `live_public` data to function is a contract violation; the system must be fully demonstrable with only `synthetic_demo` data and the live adapter disabled.
8. **Source adapters never write directly to the graph.** All writes flow through Extraction → Resolution → Graph Write Layer, regardless of which adapter produced the originating `RawRecord` — no adapter-specific shortcuts.
9. **IDs are immutable and stable.** Once assigned, `entity_id`, `relationship_id`, `evidence_id`, `case_id`, etc. are never reused or reassigned to a different underlying object.
10. **No component reaches into another component's internal data structures.** All cross-component interaction happens through the interfaces defined in this document (Sections 3–14) or the REST API (Section 12) — not through shared in-process state, direct Neo4j queries bypassing the defined schema, or direct calls into another module's private functions.
11. **Case associations never cross datasets.** Every entity, relationship (via its `EdgeRef`), and evidence item added to a `Case` must share that case's `dataset`; every `Note` belongs to its case's dataset and, if scoped via `about`, its target must match too. Violations are rejected with `dataset_isolation_violation` (Section 13), never silently allowed or silently dropped.
12. **`EdgeRef` is 1:1 with `Relationship`.** Exactly one `EdgeRef` exists per `relationship_id`, created once by the Graph Write Layer. No other component — Evidence attachment, Case Workspace — may create a second `EdgeRef` for a relationship that already has one; both consumers reuse the same node (Section 6.5).
13. **`CALL`/procedure invocation is forbidden in all Ask-the-Network-generated Cypher**, without exception, until a future contract amendment explicitly whitelists a specific procedure (Section 10).
14. **`as_of` filtering follows exactly one rule everywhere it is implemented** (Section 2.4A) — relationship visibility by `valid_from`/`valid_to`, entity visibility derived from it (plus always-visible isolated entities). No component may implement a divergent interpretation.
15. **`Finding` is persisted, not recomputed per-request, and is upserted by identity key.** Pattern Detection's `evaluate()` is a pure compute step; a separate write persists/upserts `Finding` nodes using the `(rule_id, dataset, subject_entity_ids, subject_relationship_ids)` key (Section 1.8), so `finding_id` stays stable and resolvable by later calls. No component may treat `Finding` as ephemeral or regenerate a new `finding_id` for the same underlying pattern instance.
16. **`Case` is never a `CanonicalEntity` and is never produced by Extraction or Resolution.** There is exactly one representation of a case (Section 1.9, created only via `CaseWorkspace.create_case()`); no component may introduce a second, parallel notion of "Case" via `entity_type` or any other mechanism.

---

## Corrections Made — Round 1 (prior revision)

1. **Transaction model consistency** — `Transaction` is now explicitly a first-class `CanonicalEntity` (added to the `entity_type` enum in Sections 1.3/1.4, and the Section 6.1 node row now carries the same required properties as any other entity), since it can be independently referenced by a `Case` or `Finding`.
2. **Canonical entity provenance** — Section 2.5 now states the exact, single path: `CanonicalEntity.resolved_from → ResolutionDecision (mention_ids + source_record_ids) → RawRecord → Evidence`, retrievable via a new `EvidenceResolver.for_entity()` method (Section 9.1). No second mechanism was introduced.
3. **`RESOLVED_FROM` defined precisely** — `ResolutionDecision` is now a persisted Neo4j node type (Section 6.1/1.7) with a `source_record_ids` field. `RESOLVED_FROM` is redefined as `CanonicalEntity → ResolutionDecision` (a valid direct node-to-node edge), and a new `BASED_ON` edge (`ResolutionDecision → Evidence`) completes the chain — both are ordinary node-to-node relationships, needing no indirection.
4. **Case dataset isolation strengthened** — Section 11's `CaseWorkspace` interface now states the dataset-matching requirement inline for every association method, and Contract Invariant 11 makes it a hard, enforced rule with a defined rejection error (`dataset_isolation_violation`).
5. **`EdgeRef` semantics clarified** — Section 6.5 now states the exact lifecycle: exactly one `EdgeRef` per `Relationship`, created once by the Graph Write Layer, reused by both `Evidence -[:SUPPORTS]->` and any number of `Case -[:INCLUDES_EDGE]->`. `CaseWorkspace.add_relationship()` looks up the existing `EdgeRef`; it never creates one. Codified as Contract Invariant 12.
6. **Error contract simplified** — Section 13 now states a single rule: any required sub-operation failure is a non-2xx `ErrorResponse`, full stop. The vague "partial-failure field" language was removed.
7. **ID uniqueness scopes made explicit** — new Section 1.13 states, per ID type, whether it's globally unique or dataset-scoped. Only `record_id` is dataset-scoped; every system-generated ID is globally unique.
8. **Ask-the-Network procedure restriction tightened** — Section 10's validation rules now forbid `CALL`/any procedure invocation outright, with only a specific, enumerated set of read-only Cypher constructs permitted. Codified as Contract Invariant 13.
9. **`as_of` semantics defined once, precisely** — new Section 2.4A states the single binding rule, referenced (not restated) from Analytics (Section 7) and the `/graph` endpoint (12.4). Codified as Contract Invariant 14.

## Corrections Made — Round 2 (this revision)

1. **Stale `SUPPORTED_BY` reference removed** — Section 6.4 previously still required "an outgoing `SUPPORTED_BY` edge," contradicting its own retirement in Section 6.2. It now states the authoritative requirement directly: every domain relationship must have exactly one `EdgeRef`, and that `EdgeRef` must have at least one incoming `Evidence -[:SUPPORTS]->` edge. All other lingering mentions of `SUPPORTED_BY` (Section 6.2's `MENTIONED_IN` row, Section 6.7) were reworded to reference `SUPPORTS`/`EdgeRef`; the remaining occurrences of the string `SUPPORTED_BY` in the document are explicitly historical/retirement notes, not live mechanism references.
2. **`Case` separated from `CanonicalEntity`** — `Case` is removed from both the `EntityMention.entity_type` and `CanonicalEntity.entity_type` enums (Sections 1.3/1.4), with an explicit note that `Case` is a Case Workspace object (Section 1.9) created only via `CaseWorkspace.create_case()`, never by Extraction or Resolution — there is exactly one representation of "Case" in the system. Section 6.1's node table is now split into a **`CanonicalEntity` node types** group (Person…Event) and a **Workspace/structural/derived node types** group (Case, Evidence, Note, EdgeRef, ResolutionDecision, Finding), making the distinction structurally explicit, not just prose. Codified as Contract Invariant 16.
3. **`Finding` storage/lifecycle defined** — `Finding` is now an explicitly persisted Neo4j node (Section 1.8, added to the Section 6.1 node table), written via an **upsert** keyed on `(rule_id, dataset, subject_entity_ids, subject_relationship_ids)` so `finding_id` stays stable across repeated detection runs. `PatternRule.evaluate()` remains a pure compute step (Section 8); a separate write step performs the upsert. Graph representation: `Finding -[:CONCERNS]-> CanonicalEntity` (direct) or `Finding -[:CONCERNS]-> EdgeRef` (for a subject relationship), and `Evidence -[:SUPPORTS]-> Finding` (direct, since `Finding` is a node — no `EdgeRef` indirection needed here, unlike for relationships). `EvidenceResolver.for_finding()` and `GET /patterns` were updated to match. Codified as Contract Invariant 15.

No new infrastructure, services, or technologies were introduced by any of the above — every fix was resolved using components already defined in DOC2/DOC3 (the existing monolithic backend, the existing single Neo4j instance, the existing `EdgeRef`/`SUPPORTS` pointer-node pattern extended to cover `Finding`).

**Note — an incomplete item from this request:** your message described four remaining inconsistencies but was cut off after item 3 ("This is ambiguous"), so only three full corrections were specified. I've made this pass address exactly those three, precisely as described. If there was a fourth item, please resend it and I'll fold it into a follow-up pass before this document is approved.

## DOC1/DOC2 Consistency Check

- **DOC1 requirements** (FR1–FR27, NFR1–NFR8): unaffected in substance. FR10 (inspectable resolution), FR11 (best-effort incremental resolution), FR13/FR20 (evidence/provenance required), FR17–FR19 (pattern detection, explanation, disclaimer), FR27 (case workspace) are all still satisfied — both rounds made their *implementation mechanism* precise, not their scope.
- **DOC2 architecture**: no component, data flow, or deployment decision changed. The Evidence/Provenance Resolver remains cross-cutting (DOC2 §3); the Case Workspace remains fully graph-native (DOC2 §13.1) — corrected and completed, not altered. The `SUPPORTED_BY` naming in DOC2 §5.1/§13.1 is superseded by the precise `SUPPORTS`/`EdgeRef` mechanism defined in DOC3 §6.5 (now extended to `Finding` as well); this is a naming/mechanism correction flagged explicitly, and DOC2 does not need to be reopened for it — DOC3 §6.5/§1.8 are the authoritative source.
- **No new infrastructure**: confirmed — zero new services, databases, or technologies across either round. Everything (Transaction as entity, ResolutionDecision/Finding as nodes, EdgeRef reuse, dataset checks, CALL prohibition, as_of rule) is expressed within the existing single-Neo4j, monolithic-FastAPI architecture DOC2 already established.
- **Philosophy preserved**: no microservices, Kafka, RabbitMQ, WebSockets, Kubernetes, or PostgreSQL were introduced or implied by any correction in either round.

---

*End of DOC3. Status: Draft — pending approval. Awaiting approval before proceeding to DOC4 — Build Plan.*
