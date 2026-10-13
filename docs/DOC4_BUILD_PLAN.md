# DOC4 — Build Plan
## AI-Powered Criminal Network Analysis System

**Status:** Draft — pending approval
**Depends on:** Phase 0, DOC1, DOC2, DOC3 (all approved)
**Precedes:** Task Decomposition (`docs/tasks/<track>/<TaskID>.md`)

**Purpose:** This document turns the approved architecture (DOC2) and contracts (DOC3) into a concrete, parallelizable engineering plan. Every task below references the exact DOC3 section(s) that define its interface — an implementation agent should never need to invent an interface DOC3 already specifies, and should treat a genuine gap as a defect to raise, not a decision to make silently.

---

## 1. Implementation Strategy

### 1.1 Guiding Rule

Nothing here introduces new technology, infrastructure, or architectural patterns beyond DOC2/DOC3. This document sequences and assigns work; it does not redesign anything. Where a task looks like it needs a new interface, the correct action is to point back to DOC3, not invent one.

### 1.2 Dependency Structure (why the order below)

- **Track A (Backend/Foundation)** has no dependencies and blocks substantive work on every backend track. It produces the shared contract types (DOC3 §1), the FastAPI skeleton, the Neo4j connection, the config system, and the `LLMClient` interface (DOC3 §14) — every other backend track imports these rather than redefining them.
- **Synthetic dataset creation (Track H, task H1)** has no dependencies either and should start in parallel with Track A — Track B needs it to ingest against, and nothing about designing the dataset requires the backend to exist yet.
- **Track B (Data Pipeline)** depends on Track A being minimally usable ("A-ready," Sync 1) and on H1 (synthetic files to adapt). Internally, Extraction depends on Ingestion, and Resolution depends on Extraction (DOC3 §3→§4→§5, a strict pipeline order).
- **Track C (Neo4j/Graph/Evidence)** depends on A-ready (Neo4j connection, contracts) and can be built **in parallel with Track B** against the DOC3 §1/§6 type contracts alone — C does not need B's actual running code, only the shapes B will eventually produce. Real integration between B and C happens at Sync 2.
- **Track D (Analytics/Pattern/Time Machine)** depends on Track C's schema and Graph Write Layer being usable, and in practice needs a populated graph to test against meaningfully — so it starts in earnest at/after Sync 2.
- **Track E (Frontend)** can scaffold immediately against the DOC3 §12 API contracts using mocked responses, starting in parallel with Track A. Real integration with live endpoints happens incrementally as each backend track lands (C's read endpoints first, then D, F, G).
- **Track F (Ask-the-Network)** depends on A (`LLMClient`) and C (Evidence/Provenance Resolver, graph read access) — starts at/after Sync 2.
- **Track G (Case Workspace)** depends on C (`EdgeRef`, `Evidence`, Graph Write Layer) — starts at/after Sync 2.
- **Track H (Integration/Testing/Deployment)** is continuous from day one (environment/deployment setup, synthetic dataset) but its integration and demo-rehearsal work intensifies as other tracks land, and its final tasks gate the whole project.

### 1.3 Recommended Order (phases, not strict calendar time)

```
Phase 0:  A (start)  +  H1 (synthetic dataset)  +  H2 (deployment scaffolding)  +  E1 (frontend scaffold, mocked data)
             │
             ▼  [SYNC 1 — "A-ready": contracts, API skeleton, Neo4j connection, LLMClient, config all usable]
             │
Phase 1:  B (ingestion → extraction → resolution)   ∥   C (graph schema → write layer → evidence resolver)
             │                                              │
             └──────────────────┬───────────────────────────┘
                                 ▼  [SYNC 2 — "Pipeline-to-Graph integration": synthetic data flows
                                    end-to-end through B → C into a populated, evidence-complete graph]
                                 │
Phase 2:  D (analytics/patterns/time machine)  ∥  F (Ask-the-Network)  ∥  G (Case Workspace)  ∥  E (continues, wiring real endpoints)
                                 │
                                 ▼  [SYNC 3 — "Full-stack integration": all API endpoints live,
                                    frontend fully wired, LLM-degradation paths verified]
                                 │
Phase 3:  H (final integration testing, demo rehearsal, deployment)
                                 │
                                 ▼  [SYNC 4 — "Demo readiness": DOC1 §11 success-criteria narrative
                                    runs end-to-end with the live adapter disabled]
```

### 1.4 Which Tracks Are Independent

- **A** must lead; nothing substantive starts before Sync 1.
- **B** and **C** are independent of each other (both depend only on A) and should run in parallel.
- **D**, **F**, and **G** are independent of each other (all depend only on C) and should run in parallel once C is usable.
- **E** runs continuously across all phases, with its own internal sequencing (scaffold → mock-wired components → real-wired components) rather than waiting for any single sync point.
- **H1** (dataset) and **H2** (deployment scaffolding) run in parallel with A from day one; the rest of H is genuinely last.

---

## 2. Repository Structure

Single monorepo, consistent with the monolithic FastAPI + Next.js architecture (DOC2 §2.2) — no per-service repos.

```
/
├── AGENTS.md                          # instructions for coding agents: read order (this doc → DOC1-3 → assigned task)
├── README.md
├── docs/
│   ├── DOC1_PROJECT_SPECIFICATION.md
│   ├── DOC2_ARCHITECTURE.md
│   ├── DOC3_CONTRACTS.md
│   ├── DOC4_BUILD_PLAN.md             # this document
│   └── tasks/                         # created during Task Decomposition (after DOC4 approval)
│       ├── A/  B/  C/  D/  E/  F/  G/  H/
│
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI app entrypoint, router registration
│   │   ├── config.py                  # env/config: LLM provider, adapter enablement, default dataset (DOC3 §2)
│   │   ├── api/                       # routers — one file per DOC3 §12 endpoint group
│   │   │   ├── entities.py            # §12.1–12.3
│   │   │   ├── graph.py               # §12.4
│   │   │   ├── analytics.py           # §12.5
│   │   │   ├── patterns.py            # §12.6
│   │   │   ├── evidence.py            # §12.7
│   │   │   ├── ask.py                 # §12.8
│   │   │   ├── cases.py               # §12.9
│   │   │   └── ingestion.py           # §12.10
│   │   ├── contracts/                 # DOC3 §1 data models (pydantic) — the single source of truth types
│   │   │   ├── raw_record.py          # §1.1–1.2
│   │   │   ├── mention.py             # §1.3
│   │   │   ├── entity.py              # §1.4
│   │   │   ├── relationship.py        # §1.5
│   │   │   ├── evidence.py            # §1.6
│   │   │   ├── resolution.py          # §1.7
│   │   │   ├── finding.py             # §1.8
│   │   │   ├── case.py                # §1.9–1.11
│   │   │   ├── analytics.py           # §1.12
│   │   │   └── errors.py              # §13 ErrorResponse envelope
│   │   ├── ingestion/
│   │   │   ├── adapter_base.py        # SourceAdapter interface — §3
│   │   │   ├── synthetic_adapter.py
│   │   │   ├── live_public_adapter.py
│   │   │   └── orchestrator.py
│   │   ├── extraction/
│   │   │   ├── extractor.py           # entrypoint — §4
│   │   │   ├── spacy_extractor.py
│   │   │   ├── regex_extractor.py
│   │   │   └── llm_extractor.py
│   │   ├── resolution/
│   │   │   ├── resolver.py            # batch + incremental — §5
│   │   │   ├── matching_rules.py
│   │   │   └── thresholds.py          # configuration, not hardcoded (DOC2 §8)
│   │   ├── graph/
│   │   │   ├── connection.py          # Neo4j driver/session management
│   │   │   ├── schema.py              # constraints/indexes for §6.1/6.2 node & relationship types
│   │   │   ├── write_layer.py         # Graph Write Layer — §6.4/6.5 invariant enforcement
│   │   │   └── queries.py             # reusable Cypher fragments (as_of filter §2.4A, dataset scoping)
│   │   ├── evidence/
│   │   │   └── resolver.py            # EvidenceResolver — §9.1
│   │   ├── analytics/
│   │   │   └── service.py             # §7
│   │   ├── patterns/
│   │   │   ├── engine.py              # rule runner + upsert — §8
│   │   │   └── rules/
│   │   │       ├── frequency_rule.py
│   │   │       ├── shared_attribute_rule.py
│   │   │       ├── bridge_entity_rule.py
│   │   │       └── temporal_convergence_rule.py
│   │   ├── ask/
│   │   │   ├── service.py             # §10 orchestration
│   │   │   ├── query_generator.py     # NL → Cypher via LLMClient
│   │   │   ├── validator.py           # §10 validation rules 1–6
│   │   │   └── narrator.py            # result → narration via LLMClient
│   │   ├── cases/
│   │   │   └── workspace.py           # CaseWorkspace — §11
│   │   └── llm/
│   │       └── client.py              # LLMClient — §14, provider resolved via config only
│   ├── tests/
│   │   ├── unit/                      # per-module, mocked dependencies
│   │   ├── integration/               # real Neo4j (test instance), real pipeline runs
│   │   └── contract/                  # asserts DOC3 §15 invariants hold (evidence-required, dataset isolation, etc.)
│   ├── requirements.txt
│   └── Dockerfile                     # for Render/Railway deployment
│
├── frontend/
│   ├── app/                           # Next.js app router
│   ├── components/
│   │   ├── NetworkView/               # Cytoscape.js canvas — DOC2 §4
│   │   ├── EntityPanel/
│   │   ├── EvidencePanel/
│   │   ├── Timeline/
│   │   ├── AnalyticsPanel/
│   │   ├── FiltersAndSearch/
│   │   ├── AskTheNetwork/
│   │   └── CaseWorkspace/
│   ├── lib/
│   │   ├── api-client.ts              # typed client matching DOC3 §12 exactly
│   │   └── types.ts                   # TS types mirroring DOC3 §1 (hand-kept in sync; see Track E notes)
│   ├── state/                         # minimal shared view-state (filters, selected entity, as_of) — DOC2 §4
│   ├── tests/
│   └── package.json
│
├── data/
│   └── synthetic/                     # bundled synthetic demo dataset — the guaranteed path (DOC1 §9)
│       ├── fir/
│       ├── police_report/
│       ├── cdr/
│       ├── transactions/
│       ├── vehicles/
│       ├── surveillance/
│       └── README.md                  # documents intentional messiness/aliases for the entity-resolution demo
│
├── config/
│   ├── .env.example                   # LIVE_ADAPTER_ENABLED, LLM provider/key, Neo4j URI, default dataset
│   └── adapters.yaml                  # AdapterDescriptor-shaped static config
│
└── scripts/
    ├── seed_demo.py                   # runs synthetic ingestion → extraction → resolution → graph write, end to end
    ├── run_pattern_detection.py       # manual trigger for the pattern-detection upsert run
    └── reset_graph.py                 # dev convenience — wipes and reseeds the synthetic_demo dataset only
```

**Shared contracts note:** backend types live in `backend/app/contracts/` (pydantic, generated from/matching DOC3 §1 exactly) and frontend types live in `frontend/lib/types.ts` (hand-kept TypeScript mirrors). No code-generation pipeline is introduced for this (would be infrastructure DOC1/DOC2 didn't ask for) — instead, **Track H owns a contract-drift check** (a test or script that fails CI if the two diverge) as the simplest guard against the two falling out of sync. This is scoped as task H5.

---

## 3. Engineering Tracks

The suggested track structure from your prompt maps cleanly onto DOC2's component boundaries, so it is used as-is (Section 1.4 above explains the actual dependency/parallelism structure, which doesn't perfectly match the letter order — e.g., C and B are parallel, not sequential).

### Track A — Backend / Foundation

- **Objective:** Stand up the shared backend scaffold every other backend track depends on: FastAPI app, config/env loading, Neo4j connection, the `LLMClient` interface, the DOC3 §1 contract types, and the error envelope.
- **Responsibilities:** `backend/app/main.py`, `config.py`, `contracts/`, `graph/connection.py`, `llm/client.py`, `api/` router registration (routers themselves are filled in by their owning tracks).
- **Dependencies:** none.
- **Milestones:** "A-ready" (Sync 1) — FastAPI app runs, connects to Neo4j, `LLMClient.generate()` works against a configured provider and returns a typed `LLMResult`, all DOC3 §1 types exist as pydantic models, `ErrorResponse` envelope is wired into FastAPI's exception handling.
- **Integration points:** everything imports from here; A does not import from other tracks.
- **Definition of Done:** a minimal end-to-end request (e.g., a health-check endpoint that round-trips through Neo4j) succeeds; `LLMClient` demonstrably returns `{status: "unavailable"}` when the provider is unreachable (testable by pointing config at a bad endpoint), never throwing an unhandled exception.

### Track B — Data Pipeline / Extraction / Resolution

- **Objective:** Implement Source Adapters, the Ingestion Orchestrator, Entity Extraction, and Entity Resolution (batch + incremental) per DOC3 §3–§5.
- **Dependencies:** A-ready (Sync 1); H1 (synthetic dataset files to adapt).
- **Internal order:** Ingestion → Extraction → Resolution (strict — each stage's output is the next stage's input, DOC3 §3→§4→§5).
- **Milestones:** synthetic adapter reads bundled files into valid `RawRecord[]`; extraction turns those into `EntityMention[]`/`RelationshipMention[]`; batch resolution turns those into `CanonicalEntity[]` + `ResolutionDecision[]` for `synthetic_demo`.
- **Integration points:** hands `CanonicalEntity`/`ResolutionDecision`/`Relationship`-candidate data to Track C's Graph Write Layer at Sync 2. Can be developed and unit-tested against DOC3 types alone before C exists.
- **Definition of Done:** running the full synthetic dataset through Ingestion → Extraction → Resolution produces a `CanonicalEntity` set with correctly merged aliases (per the intentionally-messy synthetic data, DOC1 §13-equivalent) and a complete `ResolutionDecision` log satisfying DOC3 §1.7/§2.5's provenance path.

### Track C — Neo4j / Graph / Evidence

- **Objective:** Implement the Neo4j schema (constraints/indexes), the Graph Write Layer, and the Evidence/Provenance Resolver per DOC3 §6, §9.
- **Dependencies:** A-ready (Sync 1). Can proceed in parallel with Track B against DOC3 types.
- **Milestones:** schema constraints exist for every node/relationship type in DOC3 §6.1/§6.2; Graph Write Layer correctly enforces DOC3 §6.4 (every relationship gets exactly one `EdgeRef`, at least one `SUPPORTS` edge) and §15 Invariant 1 (rejects relationship writes with no evidence); `EvidenceResolver` implements all five methods in DOC3 §9.1 (`for_entity`, `for_relationship`, `for_finding`, `for_resolution_decision`, `for_case_item`).
- **Integration points:** consumes Track B's output at Sync 2 (writes B's resolved entities/relationships into the graph with evidence attached); is depended on by D, F, G.
- **Definition of Done:** writing a `Relationship` with empty `evidence_ids` is rejected (test this explicitly); `EvidenceResolver.for_entity()` correctly walks `CanonicalEntity → ResolutionDecision → RawRecord-derived Evidence` (DOC3 §2.5) end-to-end against real seeded data.

### Track D — Analytics / Pattern Detection / Time Machine

- **Objective:** Implement the Analytics Service, Pattern Detection Engine (+ rules), and the `as_of` query-time temporal filter per DOC3 §7, §8, §2.4A.
- **Dependencies:** Track C usable and (in practice) a populated graph — starts in earnest after Sync 2.
- **Milestones:** all five algorithms (degree, betweenness, PageRank, community, shortest path) return correct `AnalyticsResult`/`ShortestPathResult` shapes; each `PatternRule` implementation returns valid `Finding[]` with non-empty `evidence_ids`/`explanation`/`disclaimer`; the Finding upsert mechanism (DOC3 §1.8, §8) is idempotent on re-run; `as_of` filtering matches DOC3 §2.4A exactly for both relationships and entities.
- **Integration points:** exposes data consumed by `api/analytics.py`, `api/patterns.py`, and by Track E's `AnalyticsPanel`/`Timeline` components.
- **Definition of Done:** running pattern detection twice on unchanged data produces the same `finding_id`s (no duplication); an `as_of` query for a date before any relationship existed returns only isolated entities (per §2.4A rule 2) and zero relationships.

### Track E — Frontend / Investigation UI

- **Objective:** Build the Next.js dashboard: `NetworkView`, `EntityPanel`, `EvidencePanel`, `Timeline`, `AnalyticsPanel`, `FiltersAndSearch`, wired to the DOC3 §12 API.
- **Dependencies:** none to scaffold (can build against mocked DOC3-shaped responses from day one, in parallel with Track A); real integration depends incrementally on C (read endpoints), D (analytics/patterns), F (ask), G (case workspace) as each lands.
- **Milestones:** scaffold + mock-wired components (Phase 0); real-wired `NetworkView`/`EntityPanel`/`EvidencePanel`/`FiltersAndSearch` against live C endpoints (Sync 2); `AnalyticsPanel`/`Timeline` against live D endpoints (Phase 2).
- **Integration points:** the only track that touches every other backend track's API surface; owns `frontend/lib/api-client.ts` and `types.ts` (kept in sync with DOC3 §1/§12 — see Track H's contract-drift check, H5).
- **Definition of Done:** every relationship/finding rendered in the UI has a working "view evidence" path (no claim without a way to reach its evidence, per DOC3 §9.4); filters/search/timeline all round-trip correctly against real backend state.

### Track F — Ask-the-Network / LLM

- **Objective:** Implement NL→Cypher generation, the Cypher validator, execution, evidence attachment, and narration per DOC3 §10, plus the `AskTheNetwork` frontend component.
- **Dependencies:** A (`LLMClient`) and C (`EvidenceResolver`, graph read) — starts after Sync 2.
- **Milestones:** validator correctly rejects every category in DOC3 §10 (mutating clauses, `CALL`/procedures, out-of-schema labels, cross-dataset queries, timeout); narration is demonstrably grounded-only (test: narration never mentions an entity absent from `query_result`); `llm_unavailable` status returned correctly when the LLM is down, at both the query-generation and narration steps.
- **Integration points:** consumes Track C's `EvidenceResolver`; frontend component consumes `POST /ask`.
- **Definition of Done:** a deliberately adversarial NL question (e.g., one that would naturally prompt a `CALL apoc...` or a write clause) is rejected by the validator, never executed; the two-call LLM design (DOC2 §12) is verifiable in code review — the narration call receives only `query_result`, nothing else.

### Track G — Case Workspace

- **Objective:** Implement `CaseWorkspace` (create/associate/note/summarize) per DOC3 §11, plus the `CaseWorkspace` frontend component.
- **Dependencies:** Track C (`EdgeRef`, `Evidence`, Graph Write Layer) — starts after Sync 2.
- **Milestones:** all `CaseWorkspace` interface methods implemented with dataset-isolation enforcement (DOC3 §11, Contract Invariant 11); `add_relationship()` correctly reuses the existing `EdgeRef` and never creates a duplicate (Contract Invariant 12); `generate_summary()` degrades correctly per DOC3 §11/DOC2 §12A when the LLM is unavailable.
- **Integration points:** consumes Track C's graph primitives directly; frontend component consumes `api/cases.py`.
- **Definition of Done:** attempting to add an entity/relationship/evidence item from a different `dataset` to a case is rejected with `dataset_isolation_violation` (test this explicitly, per Contract Invariant 11).

### Track H — Integration / Testing / Deployment

- **Objective:** Own the synthetic dataset, deployment scaffolding, cross-track integration testing, the contract-drift check, and final demo rehearsal.
- **Dependencies:** H1/H2 have none and start immediately; remaining tasks depend on the tracks they integrate.
- **Milestones:** see task breakdown below (H1–H6).
- **Integration points:** touches everything, by design — this is the track responsible for the system working as a whole, not just as parts.
- **Definition of Done:** the full DOC1 §11 success-criteria narrative (fragmented sources → resolved graph → analytics → patterns → evidence → Time Machine → Ask-the-Network → case summary) runs live, end-to-end, with `LIVE_ADAPTER_ENABLED=false`, with no external dependency required (Contract Invariant 7).

---

## 4. Task Breakdown

Every task lists: **ID · Title · Track · Objective · Why it exists · Dependencies · Inputs · Outputs · Files/modules expected to touch.** DOC3 section references are the binding interface for that task — implementers should not deviate from them.

### Track A

**A1 · FastAPI App Skeleton · Track A**
- *Objective:* Stand up `main.py` with router registration stubs for all DOC3 §12 endpoint groups.
- *Why:* Every other backend track needs somewhere to register its routes.
- *Dependencies:* none.
- *Inputs:* DOC3 §12 endpoint list.
- *Outputs:* running FastAPI app, empty/stub routers.
- *Files:* `backend/app/main.py`, `backend/app/api/*.py` (stubs).

**A2 · Config & Environment Loading · Track A**
- *Objective:* Implement config loading for `LIVE_ADAPTER_ENABLED`, default `dataset`, Neo4j URI/credentials, LLM provider settings, per DOC2 §15/§6.5.
- *Why:* Every track needs configuration without hardcoding values.
- *Dependencies:* none.
- *Inputs:* DOC2 §15 (deployment/config), DOC3 §2.1/§2.6.
- *Outputs:* `Config` object usable throughout the app.
- *Files:* `backend/app/config.py`, `config/.env.example`, `config/adapters.yaml`.

**A3 · Shared Contract Types · Track A**
- *Objective:* Implement every DOC3 §1 data model as a pydantic model, exactly matching field names/types/nullability.
- *Why:* This is the single source of truth every other track imports — inconsistent hand-rolled types would silently break contracts.
- *Dependencies:* none.
- *Inputs:* DOC3 §1 (full), §1.13 (ID scopes).
- *Outputs:* importable pydantic models.
- *Files:* `backend/app/contracts/*.py`.

**A4 · Neo4j Connection Layer · Track A**
- *Objective:* Implement driver/session management, connection pooling, and a health-check.
- *Why:* Every track that touches the graph depends on this.
- *Dependencies:* A2.
- *Inputs:* DOC2 §15 (Neo4j Aura/self-hosted).
- *Outputs:* `get_session()`-style accessor.
- *Files:* `backend/app/graph/connection.py`.

**A5 · LLMClient Interface & Degradation Handling · Track A**
- *Objective:* Implement `LLMClient.generate()` per DOC3 §14, with timeout/retry-once-then-fail behavior and typed `LLMResult`.
- *Why:* This is the single choke point DOC2 §12A relies on for consistent LLM degradation across Extraction, Ask-the-Network, and Case Workspace.
- *Dependencies:* A2.
- *Inputs:* DOC3 §14, DOC2 §12A.
- *Outputs:* `LLMClient` importable by Tracks B, F, G.
- *Files:* `backend/app/llm/client.py`.

**A6 · Error Envelope & Exception Handling · Track A**
- *Objective:* Implement the `ErrorResponse` envelope (DOC3 §13) as FastAPI exception handlers, covering all six `error.type` values.
- *Why:* Consistent, contract-correct error responses are required across every endpoint; this must exist before any router does real work.
- *Dependencies:* A1, A3.
- *Inputs:* DOC3 §13.
- *Outputs:* global exception handlers producing `ErrorResponse` bodies with correct HTTP status codes.
- *Files:* `backend/app/contracts/errors.py`, `backend/app/main.py` (handler registration).

---

### Track B

**B1 · SourceAdapter Interface · Track B**
- *Objective:* Define the abstract `SourceAdapter` base per DOC3 §3.
- *Why:* Both adapters (and any future ones) must conform to one interface.
- *Dependencies:* A3.
- *Inputs:* DOC3 §3.
- *Outputs:* `SourceAdapter` ABC.
- *Files:* `backend/app/ingestion/adapter_base.py`.

**B2 · Synthetic Adapter · Track B**
- *Objective:* Implement `fetch_batch()` reading bundled synthetic files (H1's output) into `RawRecord[]`.
- *Why:* This is the guaranteed demo path (DOC1 constraint) — must be built and correct independent of the live adapter.
- *Dependencies:* B1, H1.
- *Inputs:* `data/synthetic/*`, DOC3 §1.1.
- *Outputs:* valid `RawRecord[]` per source type.
- *Files:* `backend/app/ingestion/synthetic_adapter.py`.

**B3 · Public/Live Adapter (optional capability) · Track B**
- *Objective:* Implement `poll()` against one chosen public/open source (e.g., RSS/news), with cursor handling and silent-failure behavior per DOC3 §3.
- *Why:* Demonstrates the source-adapter extensibility DOC1/DOC2 committed to, without being a demo dependency.
- *Dependencies:* B1.
- *Inputs:* DOC3 §3 error-behavior rules, DOC2 §6.3.
- *Outputs:* `RawRecord[]` tagged `dataset: "live_public"`.
- *Files:* `backend/app/ingestion/live_public_adapter.py`.

**B4 · Ingestion Orchestrator · Track B**
- *Objective:* Coordinate calling configured adapters, persist cursors, tag records, hand off to Extraction.
- *Why:* Central place enforcing "adapters never write directly to the graph" (Contract Invariant 8).
- *Dependencies:* B2, B3, A5 (config for enablement).
- *Inputs:* `AdapterDescriptor` config.
- *Outputs:* stream of `RawRecord` handed to Extraction.
- *Files:* `backend/app/ingestion/orchestrator.py`.

**B5 · Entity/Relationship Extraction (spaCy + regex) · Track B**
- *Objective:* Implement non-LLM extraction methods per DOC3 §4.
- *Why:* Core ingestion must not depend on the LLM (Contract Invariant 4/DOC2 §12A) — this path must work standalone.
- *Dependencies:* B4, A3.
- *Inputs:* `RawRecord`, DOC3 §4.
- *Outputs:* `EntityMention[]`/`RelationshipMention[]` with `extraction_method: "spacy"|"regex"`.
- *Files:* `backend/app/extraction/spacy_extractor.py`, `regex_extractor.py`.

**B6 · LLM-Assisted Extraction · Track B**
- *Objective:* Implement the LLM fallback path for ambiguous mentions, only invoked after B5 per DOC2 §7.
- *Why:* Improves extraction quality on ambiguous free text without making extraction LLM-dependent.
- *Dependencies:* B5, A5.
- *Inputs:* DOC3 §4 ("LLM use" clause).
- *Outputs:* additional `EntityMention[]`/`RelationshipMention[]` with `extraction_method: "llm"`.
- *Files:* `backend/app/extraction/llm_extractor.py`, `extractor.py` (orchestration).

**B7 · Batch Entity Resolution · Track B**
- *Objective:* Implement full-dataset clustering/resolution for `synthetic_demo` per DOC3 §5.
- *Why:* This is the correctness-target resolution path the guaranteed demo depends on.
- *Dependencies:* B6.
- *Inputs:* `EntityMention[]` for the dataset, configurable thresholds.
- *Outputs:* `CanonicalEntity[]` + `ResolutionDecision[]` (with `source_record_ids`, DOC3 §1.7).
- *Files:* `backend/app/resolution/resolver.py`, `matching_rules.py`, `thresholds.py`.

**B8 · Incremental Entity Resolution (best-effort) · Track B**
- *Objective:* Implement the incremental-against-existing-graph resolution path for `live_public`, per DOC3 §5's batch-vs-incremental table.
- *Why:* Required only for the optional live capability; explicitly best-effort, not correctness-guaranteed (DOC1 FR11).
- *Dependencies:* B7 (shares matching rules).
- *Inputs:* new `EntityMention`, existing `CanonicalEntity` set for `live_public`.
- *Outputs:* new/updated `CanonicalEntity` + `ResolutionDecision`.
- *Files:* `backend/app/resolution/resolver.py` (incremental path).

---

### Track C

**C1 · Neo4j Schema (Constraints & Indexes) · Track C**
- *Objective:* Create uniqueness constraints/indexes for every ID field in DOC3 §1.13 and every node/relationship type in §6.1/§6.2.
- *Why:* Enforces ID-uniqueness invariants at the database level, not just in application code.
- *Dependencies:* A4.
- *Inputs:* DOC3 §6.1, §6.2, §1.13.
- *Outputs:* applied Neo4j schema.
- *Files:* `backend/app/graph/schema.py`.

**C2 · Graph Write Layer — Entities & Relationships · Track C**
- *Objective:* Implement writes for `CanonicalEntity`/`Relationship`, including the `EdgeRef` creation step (exactly one per relationship, DOC3 §6.5) and `dataset` tagging.
- *Why:* Central enforcement point for Contract Invariant 1 (no relationship without evidence) and Invariant 12 (`EdgeRef` 1:1).
- *Dependencies:* C1.
- *Inputs:* DOC3 §6.4, §6.5.
- *Outputs:* `write_entity()`, `write_relationship()` functions that reject invalid writes.
- *Files:* `backend/app/graph/write_layer.py`.

**C3 · Graph Write Layer — Evidence & ResolutionDecision · Track C**
- *Objective:* Implement `Evidence` node materialization (idempotent per `(source_id, dataset)`, DOC3 §1.13) and `ResolutionDecision` persistence with `RESOLVED_FROM`/`BASED_ON` edges (DOC3 §6.2, §2.5).
- *Why:* This is the mechanism that makes entity provenance (Section 2.5's exact path) actually queryable.
- *Dependencies:* C2.
- *Inputs:* DOC3 §1.6, §1.7, §2.5.
- *Outputs:* `write_evidence()`, `write_resolution_decision()`.
- *Files:* `backend/app/graph/write_layer.py`.

**C4 · Evidence/Provenance Resolver · Track C**
- *Objective:* Implement all five `EvidenceResolver` methods per DOC3 §9.1.
- *Why:* This is the cross-cutting capability every other component (Pattern Detection, Ask-the-Network, Case Workspace, API layer) depends on for evidence lookups.
- *Dependencies:* C3.
- *Inputs:* DOC3 §9.1, §2.5, §6.5.
- *Outputs:* `EvidenceResolver` implementation.
- *Files:* `backend/app/evidence/resolver.py`.

**C5 · `as_of` Query Filter · Track C**
- *Objective:* Implement the exact §2.4A rule as reusable Cypher (relationship visibility by `valid_from`/`valid_to`; entity visibility derived + isolated-entity exception).
- *Why:* Must be implemented once and shared, so Analytics, `/graph`, and Ask-the-Network never diverge (Contract Invariant 14).
- *Dependencies:* C2.
- *Inputs:* DOC3 §2.4A.
- *Outputs:* reusable query fragment/function.
- *Files:* `backend/app/graph/queries.py`.

**C6 · Graph & Entity API Endpoints · Track C**
- *Objective:* Implement `api/entities.py` and `api/graph.py` (DOC3 §12.1–12.4).
- *Why:* First real read surface for Track E to integrate against.
- *Dependencies:* C4, C5.
- *Inputs:* DOC3 §12.1–12.4.
- *Outputs:* working endpoints.
- *Files:* `backend/app/api/entities.py`, `graph.py`.

---

### Track D

**D1 · Analytics Service · Track D**
- *Objective:* Implement all five algorithms (degree, betweenness, PageRank, community, shortest path) via Neo4j GDS/NetworkX, per DOC3 §7.
- *Why:* Feeds Pattern Detection and the frontend's `AnalyticsPanel`.
- *Dependencies:* C5 (as_of filter), C6.
- *Inputs:* DOC3 §7 (`AnalyticsRequest`/`AnalyticsResult`).
- *Outputs:* `AnalyticsResult`, `ShortestPathResult`.
- *Files:* `backend/app/analytics/service.py`.

**D2 · Pattern Rules — Frequency & Shared-Attribute · Track D**
- *Objective:* Implement `FrequencyRule` and `SharedAttributeRule` per DOC3 §8.
- *Why:* Core investigative-lead detection (DOC1 FR17).
- *Dependencies:* D1.
- *Inputs:* DOC3 §8, §1.8.
- *Outputs:* `Finding[]` (in-memory, pre-write).
- *Files:* `backend/app/patterns/rules/frequency_rule.py`, `shared_attribute_rule.py`.

**D3 · Pattern Rules — Bridge Entity & Temporal Convergence · Track D**
- *Objective:* Implement the remaining two rules, using D1's centrality/community output.
- *Why:* Completes the DOC1 §6 pattern list.
- *Dependencies:* D1, D2 (shares rule-runner scaffolding).
- *Inputs:* DOC3 §8.
- *Outputs:* `Finding[]`.
- *Files:* `backend/app/patterns/rules/bridge_entity_rule.py`, `temporal_convergence_rule.py`.

**D4 · Pattern Detection Engine & Finding Persistence · Track D**
- *Objective:* Implement the rule runner and the upsert-on-identity-key write step per DOC3 §1.8/§8.
- *Why:* This is what makes `finding_id` stable across re-runs (Contract Invariant 15).
- *Dependencies:* D2, D3, C3 (graph write patterns), C4 (evidence attachment).
- *Inputs:* DOC3 §1.8 identity key, §6.1/§6.2 (`Finding`, `CONCERNS`, `SUPPORTS`).
- *Outputs:* persisted, upserted `Finding` nodes.
- *Files:* `backend/app/patterns/engine.py`.

**D5 · Analytics & Patterns API Endpoints · Track D**
- *Objective:* Implement `api/analytics.py` and `api/patterns.py` (DOC3 §12.5–12.6).
- *Why:* Exposes D1–D4 to the frontend.
- *Dependencies:* D4.
- *Inputs:* DOC3 §12.5–12.6.
- *Outputs:* working endpoints.
- *Files:* `backend/app/api/analytics.py`, `patterns.py`.

---

### Track E

**E1 · Frontend Scaffold & Mock API Layer · Track E**
- *Objective:* Set up the Next.js app, `api-client.ts`/`types.ts` against DOC3 §1/§12, and a mock-data mode.
- *Why:* Lets UI work start immediately without waiting on the backend.
- *Dependencies:* none.
- *Inputs:* DOC3 §1, §12.
- *Outputs:* running frontend shell with mocked data.
- *Files:* `frontend/app/`, `frontend/lib/*`.

**E2 · NetworkView (Cytoscape.js) · Track E**
- *Objective:* Implement pan/zoom/select/filter/highlight-path canvas.
- *Why:* Core investigator workflow (DOC1 W1/W2).
- *Dependencies:* E1; real-wiring depends on C6.
- *Inputs:* `GET /graph` response shape.
- *Outputs:* interactive canvas component.
- *Files:* `frontend/components/NetworkView/`.

**E3 · EntityPanel & EvidencePanel · Track E**
- *Objective:* Entity detail + resolution rationale view; evidence chain view for any relationship/finding.
- *Why:* Directly implements the "no claim without a way to reach its evidence" requirement (DOC3 §9.4).
- *Dependencies:* E1; real-wiring depends on C6, C4 (via `GET /evidence`).
- *Inputs:* DOC3 §12.2, §12.3, §12.7.
- *Outputs:* two components.
- *Files:* `frontend/components/EntityPanel/`, `EvidencePanel/`.

**E4 · Timeline & AnalyticsPanel · Track E**
- *Objective:* Timeline slider driving `as_of`; analytics/community/pattern summaries.
- *Why:* Implements the Network Time Machine (DOC1 W4) and analytics surfacing (W3).
- *Dependencies:* E1; real-wiring depends on D5.
- *Inputs:* DOC3 §12.4 (`as_of`), §12.5, §12.6.
- *Outputs:* two components.
- *Files:* `frontend/components/Timeline/`, `AnalyticsPanel/`.

**E5 · FiltersAndSearch · Track E**
- *Objective:* Entity-type/relationship-type/date/source/community/pattern filters; search.
- *Why:* Required dashboard capability (DOC1 FR26).
- *Dependencies:* E1; real-wiring depends on C6.
- *Inputs:* DOC3 §12.1, §12.4.
- *Outputs:* filter/search component wired into shared view state.
- *Files:* `frontend/components/FiltersAndSearch/`, `frontend/state/`.

**E6 · AskTheNetwork Component · Track E**
- *Objective:* Chat-style NL question input, narration + path + evidence display, explicit unavailable/validation-failed states.
- *Why:* DOC1 W5; must visibly surface `llm_unavailable`/`validation_failed`, never hide them.
- *Dependencies:* E1; real-wiring depends on F4.
- *Inputs:* DOC3 §12.8 (`AskResponse` union).
- *Outputs:* component handling all four `AskResponse` variants.
- *Files:* `frontend/components/AskTheNetwork/`.

**E7 · CaseWorkspace Component · Track E**
- *Objective:* Case creation, entity/relationship/evidence association, notes, summary view (with `llm_unavailable` state).
- *Why:* DOC1 W6.
- *Dependencies:* E1; real-wiring depends on G3.
- *Inputs:* DOC3 §12.9.
- *Outputs:* component.
- *Files:* `frontend/components/CaseWorkspace/`.

---

### Track F

**F1 · Cypher Query Generator · Track F**
- *Objective:* Build the schema-constrained prompt and call `LLMClient` to produce `GeneratedQuery` per DOC3 §10.
- *Why:* First half of the two-call Ask-the-Network design (DOC2 §12).
- *Dependencies:* A5, C6 (schema awareness).
- *Inputs:* DOC3 §10 (`AskRequest`, `GeneratedQuery`).
- *Outputs:* candidate Cypher + parameters.
- *Files:* `backend/app/ask/query_generator.py`.

**F2 · Cypher Validator · Track F**
- *Objective:* Implement all six validation rules from DOC3 §10, including the outright `CALL`/procedure prohibition (Contract Invariant 13).
- *Why:* This is the safety boundary preventing the LLM from executing anything unsafe or out-of-scope.
- *Dependencies:* F1.
- *Inputs:* DOC3 §10 validation rules, §6 (schema).
- *Outputs:* accept/reject decision + `validation_failed` reason.
- *Files:* `backend/app/ask/validator.py`.

**F3 · Query Execution, Evidence Attachment & Narration · Track F**
- *Objective:* Execute validated queries, attach evidence via C4, call `LLMClient` again for narration-only-over-results.
- *Why:* Second half of the two-call design; the structural guarantee that the LLM never originates a fact (Contract Invariant 3).
- *Dependencies:* F2, C4.
- *Inputs:* DOC3 §10 (`GraphQueryResult`, `NarrationInput`/`Output`).
- *Outputs:* narrated, evidence-attached result.
- *Files:* `backend/app/ask/service.py`, `narrator.py`.

**F4 · Ask API Endpoint · Track F**
- *Objective:* Implement `POST /ask` (DOC3 §12.8), returning the full `AskResponse` union including `llm_unavailable`/`no_result`.
- *Why:* Exposes F1–F3 to the frontend.
- *Dependencies:* F3.
- *Inputs:* DOC3 §12.8.
- *Outputs:* working endpoint.
- *Files:* `backend/app/api/ask.py`.

---

### Track G

**G1 · CaseWorkspace Core (Case/Note/EdgeRef Associations) · Track G**
- *Objective:* Implement `create_case`, `add_entity`/`remove_entity`, `add_relationship`/`remove_relationship` (reusing existing `EdgeRef`, never creating one — Contract Invariant 12), `add_evidence`, `add_note`, all with dataset-isolation checks (Contract Invariant 11).
- *Why:* Core case-building workflow (DOC1 W6).
- *Dependencies:* C2, C3, C4.
- *Inputs:* DOC3 §11, §6.5.
- *Outputs:* `CaseWorkspace` implementation (minus summary).
- *Files:* `backend/app/cases/workspace.py`.

**G2 · Case Summary Generation · Track G**
- *Objective:* Implement `generate_summary()` — assembles case context, calls `LLMClient`, handles `llm_unavailable` per DOC2 §12A.
- *Why:* DOC1 W6's final step; must degrade gracefully like every other LLM-dependent feature.
- *Dependencies:* G1, A5.
- *Inputs:* DOC3 §11 (`CaseSummaryResult`).
- *Outputs:* summary generation with typed failure mode.
- *Files:* `backend/app/cases/workspace.py` (summary method).

**G3 · Case Workspace API Endpoints · Track G**
- *Objective:* Implement `api/cases.py` (DOC3 §12.9).
- *Why:* Exposes G1–G2 to the frontend.
- *Dependencies:* G2.
- *Inputs:* DOC3 §12.9.
- *Outputs:* working endpoints.
- *Files:* `backend/app/api/cases.py`.

---

### Track H

**H1 · Synthetic Demo Dataset · Track H**
- *Objective:* Design and produce the bundled synthetic dataset — intentionally fragmented, with deliberate aliases (per DOC1's "R. Sharma"/"Rahul Sharma" example) across the required source types.
- *Why:* The guaranteed demo path depends entirely on this; nothing else in Track B can be tested meaningfully without it. No dependency on any other track — start immediately.
- *Dependencies:* none.
- *Inputs:* DOC1 §2 (data sources list), DOC1 §13-equivalent (messiness requirement).
- *Outputs:* files under `data/synthetic/`, with a README documenting the intentional aliases/messiness for later verification.
- *Files:* `data/synthetic/**`.

**H2 · Deployment Scaffolding · Track H**
- *Objective:* Set up Vercel (frontend), Render/Railway (backend), Neo4j Aura (graph) deployment configs, per DOC2 §15.
- *Why:* Avoids a last-minute scramble; can be done in parallel with Track A.
- *Dependencies:* none.
- *Inputs:* DOC2 §15.
- *Outputs:* working deploy pipelines (even if pointed at empty/stub apps initially).
- *Files:* `backend/Dockerfile`, deployment config files, `README.md` deployment section.

**H3 · Pipeline-to-Graph Integration Test (Sync 2 gate) · Track H**
- *Objective:* Run H1's dataset through the full B→C pipeline and assert the result satisfies DOC3 invariants (every relationship has evidence, every entity has a resolvable `ResolutionDecision` chain, correct alias merging).
- *Why:* This is the actual gate for Sync 2 — the point where D/F/G can start real integration work.
- *Dependencies:* B7, C4.
- *Inputs:* seeded `synthetic_demo` graph.
- *Outputs:* passing integration test suite; a reliably seedable demo graph via `scripts/seed_demo.py`.
- *Files:* `backend/tests/integration/`, `scripts/seed_demo.py`.

**H4 · Cross-Track Contract Tests · Track H**
- *Objective:* Implement automated tests asserting each DOC3 §15 Contract Invariant holds (empty-evidence rejection, dataset isolation, `CALL` prohibition, `as_of` consistency, `EdgeRef` 1:1, `Finding` upsert stability, `Case` never a `CanonicalEntity`, etc.).
- *Why:* These invariants are the actual safety net for independent-agent implementation; they must be continuously verified, not just documented.
- *Dependencies:* runs continuously as each track lands; meaningful once C, D, F, G each have something to test.
- *Inputs:* DOC3 §15 (all 16 invariants).
- *Outputs:* `backend/tests/contract/` suite, one test (or group) per invariant.
- *Files:* `backend/tests/contract/*.py`.

**H5 · Contract-Drift Check (Frontend/Backend Type Sync) · Track H**
- *Objective:* Implement a check (script or test) that fails if `frontend/lib/types.ts` diverges from `backend/app/contracts/*.py`/DOC3 §1.
- *Why:* Section 2's noted risk — hand-kept types on both sides will drift without an explicit guard.
- *Dependencies:* A3, E1.
- *Outputs:* CI-runnable drift check.
- *Files:* `scripts/` (drift-check script) or a `backend/tests/contract/` entry.

**H6 · Full Demo Rehearsal (Sync 4 gate) · Track H**
- *Objective:* Execute the complete DOC1 §11 success-criteria narrative live, with `LIVE_ADAPTER_ENABLED=false`, timing it and fixing any rough edges.
- *Why:* This is the actual definition of "done" for the whole project — everything else is in service of this working.
- *Dependencies:* all other tracks complete or feature-complete for demo purposes.
- *Inputs:* DOC1 §11 (10-point success criteria).
- *Outputs:* a rehearsed, reliable, fully-offline-capable demo.
- *Files:* none (process/validation task); may produce a demo script/runbook under `docs/`.

---

## 5. Synchronization Points Summary

| Sync | Gate condition | Unblocks |
|---|---|---|
| **Sync 1 — "A-ready"** | A1–A6 complete | Substantive work on B, C, F, G (E can start earlier, mocked) |
| **Sync 2 — "Pipeline-to-Graph integration"** | H3 passes (B7 + C4 output verified against DOC3 invariants) | D, F, G real integration; E's real-wiring for C-dependent components |
| **Sync 3 — "Full-stack integration"** | D5, F4, G3 all live; E fully real-wired | H6 |
| **Sync 4 — "Demo readiness"** | H6 passes | Project complete |

---

*End of DOC4. Status: Draft — pending approval. Task Decomposition (individual `docs/tasks/<track>/<TaskID>.md` files, per the process this project follows) begins only after explicit approval of this document.*
