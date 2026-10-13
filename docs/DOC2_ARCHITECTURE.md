# DOC2 — Technical Architecture
## AI-Powered Criminal Network Analysis System

**Status:** Draft — pending approval
**Depends on:** DOC1 — Project Specification (approved)
**Precedes:** DOC3 — Contracts & Interfaces

---

## 1. Architectural Principles

These principles govern every decision below and should be used to resolve any ambiguity during implementation:

1. **Simplicity over sophistication.** The architecture must satisfy DOC1, not impress with technology choices. A monolithic backend with a well-structured internal pipeline beats a distributed system for this prototype.
2. **Synthetic data is the guaranteed path.** The system must run fully, reliably, and demo-ready using only synthetic data, with zero calls to external services required.
3. **Live/public data is an adapter, not a dependency.** It plugs into the same pipeline through a defined interface and can be absent without degrading the core system.
4. **Evidence is structural and cross-cutting, not a pipeline stage.** Provenance is carried as graph data and is queried by every component that produces a claim — entity resolution, pattern detection, Ask-the-Network, Case Workspace, and the dashboard — not computed once and handed down a linear chain.
5. **The LLM is a component behind an interface, never the source of truth.** It narrates and translates; Neo4j and source records are authoritative.
6. **One graph database, one source of structural truth.** Neo4j holds entities, relationships, and evidence links. A second (relational) store is introduced only if a concrete need is identified (see Section 5.2).
7. **No infrastructure the requirements don't demand.** No microservices, no message brokers, no Kubernetes, no streaming platforms, no WebSockets — until a specific, documented requirement forces the issue (none currently do).

---

## 2. System Overview

### 2.1 High-Level Architecture Diagram

```
                        ┌─────────────────────────────┐
                        │        FRONTEND (SPA)        │
                        │  Next.js + React + TS +      │
                        │  Tailwind + Cytoscape.js     │
                        │  (Evidence views everywhere) │
                        └───────────────▲──────────────┘
                                        │ REST/JSON (HTTPS)
                                        │
                        ┌───────────────┴──────────────────────────┐
                        │            BACKEND (Monolith)              │
                        │             Python + FastAPI               │
                        │                                             │
                        │  ┌───────────────────────────────────────┐  │
                        │  │   Ingestion Layer                     │  │
                        │  │  (Source Adapter Interface)           │  │
                        │  │  - Synthetic Adapter                  │  │
                        │  │  - Public/Live Adapter* (opt, polling)│  │
                        │  └───────────────┬───────────────────────┘  │
                        │                  ▼                          │
                        │  ┌───────────────────────────────────────┐  │
                        │  │  Entity Extraction (spaCy+regex+LLM)  │  │
                        │  └───────────────┬───────────────────────┘  │
                        │                  ▼                          │
                        │  ┌───────────────────────────────────────┐  │
                        │  │  Entity Resolution (fuzzy+rules+embed)│  │
                        │  └───────────────┬───────────────────────┘  │
                        │                  ▼                          │
                        │  ┌───────────────────────────────────────┐  │
                        │  │  Graph Write Layer                    │  │
                        │  │  (MERGE entities/relationships,       │  │
                        │  │   MERGE Evidence + SUPPORTED_BY)      │  │
                        │  └───────────────┬───────────────────────┘  │
                        │                  ▼                          │
                        │           ┌─────────────┐                   │
                        │           │   Neo4j     │                   │
                        │           │ (+ GDS)     │                   │
                        │           │ entities +  │                   │
                        │           │ relations + │                   │
                        │           │ Evidence    │                   │
                        │           └──────┬──────┘                   │
                        │                  │                          │
                        │        ┌─────────┼──────────┬──────────┐    │
                        │        ▼         ▼          ▼          ▼    │
                        │  ┌─────────┐┌──────────┐┌────────┐┌────────┐│
                        │  │Analytics││ Pattern  ││ Ask-the││  Case  ││
                        │  │Service  ││Detection ││Network ││Worksp. ││
                        │  └────┬────┘└────┬─────┘└───┬────┘└───┬────┘│
                        │       └──────────┴───────────┴─────────┘    │
                        │                     │                       │
                        │                     ▼                       │
                        │   ══════════════════════════════════════   │
                        │   ║  EVIDENCE / PROVENANCE RESOLVER       ║  │
                        │   ║  (cross-cutting — reads Evidence      ║  │
                        │   ║   nodes for: relationships, entity-   ║  │
                        │   ║   resolution rationale, flagged       ║  │
                        │   ║   patterns, Ask-the-Network results,  ║  │
                        │   ║   Case items; every API response      ║  │
                        │   ║   that carries a claim routes         ║  │
                        │   ║   through this before reaching the    ║  │
                        │   ║   frontend)                           ║  │
                        │   ══════════════════════════════════════   │
                        │                     │                       │
                        │                     ▼  (API Layer, §14)     │
                        │                                             │
                        │  ┌───────────────────────────────────────┐  │
                        │  │  LLM Client Interface (provider-       │  │
                        │  │  agnostic) ─────────► External LLM API │  │
                        │  └───────────────────────────────────────┘  │
                        └─────────────────────────────────────────────┘
```

The double-ruled **Evidence/Provenance Resolver** box is drawn separately from the linear pipeline on purpose: it is not a stage that data passes through once, but a shared capability that Entity Resolution, the Graph Write Layer, Analytics, Pattern Detection, Ask-the-Network, Case Workspace, and the frontend's evidence views all call into directly. See Section 5.1 (provenance is stored as graph structure, not a log) and Section 3 for how each component uses it.

### 2.2 Why a Monolith

A single FastAPI backend process hosts ingestion, extraction, resolution, graph access, analytics, pattern detection, Ask-the-Network, and case workspace as **internal modules with clean boundaries**, not separate services. This is a deliberate architectural decision, not a shortcut:

- All of these stages are called sequentially or on related triggers; there is no independent scaling or independent-failure requirement that justifies network boundaries between them.
- A monolith is trivially deployable for a hackathon demo (one process, one deployment target).
- Internal module boundaries (see Section 3) still enforce separation of concerns, so this can be decomposed into services later **if a real requirement ever demands it** — nothing here is designed to make that harder than necessary, but nothing is built prematurely for it either.

---

## 3. Backend Components & Responsibilities

| Component | Responsibility | Depends on |
|---|---|---|
| **Source Adapter Interface** | Defines a common contract (`fetch()` / `poll()` → normalized raw records) that any source must implement | — |
| **Synthetic Adapter** | Reads bundled synthetic files (FIR, CDR, transactions, etc.) and emits normalized raw records | Source Adapter Interface |
| **Public/Live Adapter (optional)** | Polls a public/open source (e.g., RSS/news) on a schedule and emits normalized raw records in the same shape | Source Adapter Interface |
| **Ingestion Orchestrator** | Pulls from all configured adapters, tags each record with source metadata, hands records to Extraction | Adapters |
| **Entity Extraction Module** | Runs spaCy/regex/LLM over each raw record; outputs candidate entities + mentions, tied to the source record ID | Ingestion Orchestrator, LLM Client |
| **Entity Resolution Module** | Matches candidate entities against each other (batch) or against existing graph entities (incremental case), decides merge/no-merge, records resolution rationale | Entity Extraction |
| **Graph Write Layer** | Translates resolved entities/relationships into Neo4j `MERGE` operations; attaches evidence/provenance nodes/properties | Entity Resolution, Neo4j |
| **Analytics Service** | Runs centrality/PageRank/community/shortest-path over the current graph snapshot, on demand or on a schedule | Neo4j + GDS |
| **Pattern Detection Engine** | Applies transparent rules (frequency thresholds, shared-attribute checks, bridge-entity checks, temporal convergence) against graph + analytics output; produces flagged items, each referencing supporting Evidence via the Evidence/Provenance Resolver | Neo4j, Analytics Service, Evidence/Provenance Resolver |
| **Evidence/Provenance Resolver** *(cross-cutting)* | Not a pipeline stage — a shared query capability called by every component that needs to justify a claim: resolves the `Evidence` chain behind a relationship, an entity-resolution merge decision, a flagged pattern, an Ask-the-Network result, or a Case item. Called directly by Entity Resolution, Pattern Detection, Ask-the-Network, Case Workspace, and the API Layer/frontend. | Neo4j |
| **Ask-the-Network Service** | Converts NL questions to Cypher (LLM-assisted, schema-constrained), executes against Neo4j, retrieves evidence via the Evidence/Provenance Resolver, produces narrated answer | Neo4j, LLM Client, Evidence/Provenance Resolver |
| **Case Workspace Service** | CRUD for cases; associates entities/relationships/evidence/notes with a case (see Section 13 for the explicit data model); generates summary text; every associated item carries its evidence via the Evidence/Provenance Resolver | Neo4j, LLM Client (for summary generation), Evidence/Provenance Resolver |
| **LLM Client Interface** | Single abstraction (`generate(prompt, context) -> text`) behind which any provider sits; raises a distinguishable "LLM unavailable" error rather than failing silently (see Section 12A) | External LLM API |
| **API Layer (FastAPI routers)** | Exposes REST endpoints for the frontend: search, entity detail, graph queries, analytics, patterns, timeline, ask, case workspace; ensures every response carrying a claim (relationship, pattern, resolution rationale, Ask-the-Network answer, case item) includes its evidence via the Evidence/Provenance Resolver before returning | All of the above |

---

## 4. Frontend Architecture

- **Framework:** Next.js + React + TypeScript + Tailwind, as a single-page application consuming the backend's REST API.
- **Structure (by concern, not by microfrontend):**
  - `NetworkView` — Cytoscape.js canvas: renders nodes/edges from the current query/filter/time state, supports pan/zoom/select/highlight-path.
  - `EntityPanel` — detail view for a selected entity (attributes, resolution rationale, connected relationships).
  - `EvidencePanel` — supporting source records for a selected relationship or flagged pattern.
  - `Timeline` — slider control; changes the "as-of" timestamp sent to the backend, which returns the graph state at that point.
  - `AnalyticsPanel` — centrality/community/pattern summaries for the current graph.
  - `FiltersAndSearch` — entity type/relationship type/date/source/community/pattern filters; search by entity/phone/vehicle/etc.
  - `AskTheNetwork` — chat-style input; displays narrated answer + path + evidence.
  - `CaseWorkspace` — case creation, entity/evidence association, notes, generated summary view.
- **State management:** kept simple — component-local state plus a lightweight shared store (e.g., React context or a minimal state library) for the current "graph view state" (filters, selected entity, as-of time). No need for complex global state infrastructure at this scale.
- **Data refresh:** for the guaranteed synthetic demo path, data is essentially static once loaded, so no live-refresh mechanism is required. If the optional live adapter is active, the dashboard can simply re-fetch on a manual "refresh" action or a coarse interval poll (see Section 6.4) — no push infrastructure needed.

---

## 5. Data Architecture

### 5.1 Neo4j as System of Record

Neo4j stores the knowledge graph and, per the evidence requirement, the provenance data needed to justify every relationship and pattern.

**Node labels:**
`Person`, `Phone`, `Vehicle`, `Location`, `Organization`, `BankAccount`, `Transaction`, `Case`, `Event`, `Evidence`, `Note`, `EdgeRef` (the latter two support the Case Workspace data model — see Section 13.1)

**Relationship types:**
`CALLED`, `OWNS`, `USED`, `TRANSFERRED`, `VISITED`, `MET`, `WORKS_FOR`, `ASSOCIATED_WITH`, `MENTIONED_IN`, `PART_OF`

**Provenance model:**
Every substantive relationship between two domain entities is linked to one or more `Evidence` nodes via a `SUPPORTED_BY` relationship. Each `Evidence` node carries: `source_id`, `source_type` (e.g., `CDR`, `FIR`, `synthetic`, `rss`), `record_timestamp`, `ingested_at`, and a pointer/snippet back to the original record. This means provenance is queryable graph structure, not an external log — asking "why does this edge exist" is a graph traversal, not a lookup elsewhere.

**Temporal model:**
Relationships carry a `valid_from` (and where applicable `valid_to` / `occurred_at`) property derived from the source record's timestamp. The Timeline feature queries the graph with a `WHERE r.occurred_at <= $asOf` style filter (or an equivalent GDS-friendly approach) to reconstruct state as of a given point — this is a **query-time filter over a single current graph**, not a versioned/multi-snapshot database. This is the simplest approach that satisfies FR21 without building temporal-graph infrastructure.

**Resolution rationale:**
Entity Resolution decisions (which raw mentions were merged into a canonical entity, and why) are stored either as properties on the entity node (e.g., `resolved_from: [record_ids]`, `resolution_method`) or as lightweight `RESOLVED_FROM` relationships to mention-level records — kept as graph data so FR10 (inspectable resolution) is satisfiable directly via query, not via a separate audit system.

### 5.2 Do We Need a Second Database?

**Decision: No, not initially.** Case metadata, notes, and case-entity associations are naturally graph-shaped and Neo4j handles this without strain at this scale. The explicit representation is defined in Section 13.

A relational store (PostgreSQL/Supabase) would only be justified if, during implementation, a concrete need emerges that Neo4j handles awkwardly — e.g., complex relational reporting queries, full-text search at a scale Neo4j's indexes don't comfortably cover, or user-account data if authentication is later added. **None of these are current requirements.** This decision should be revisited explicitly (per the DOC1 constraint) only if such a need is documented — not introduced preemptively.

### 5.3 Data Flow Summary

```
Raw record (with source_id, timestamp)
   → Extraction (entities + mentions, still tagged to source_id)
   → Resolution (mentions → canonical entity, rationale recorded)
   → Graph write (MERGE entity/relationship nodes, attach Evidence via SUPPORTED_BY)
   → Analytics (computed over current graph, cached/recomputed on demand)
   → Pattern Detection (reads graph + analytics, writes flagged-pattern nodes/records with explanation + evidence links)
   → API layer exposes all of the above to the frontend, always joined with evidence
```

---

## 6. Ingestion Architecture

### 6.1 Source Adapter Interface

A minimal, stable contract every source must implement (exact schema defined in DOC3):

- `adapter_id` / `source_type`
- `fetch_batch()` — for bounded sources (synthetic files): returns all available records once.
- `poll()` — for live sources: returns records new since last poll (cursor/timestamp-based).
- Every record returned is normalized to a common raw-record shape: `{source_id, source_type, timestamp, payload}`.

### 6.2 Synthetic Adapter (guaranteed path)

Reads bundled synthetic data files (per source type: FIR, CDR, transactions, vehicles, surveillance, etc.) from local storage, normalizes them, and feeds the Ingestion Orchestrator. No network calls, no external dependency — this is what the live demo relies on by default.

### 6.3 Public/Live Adapter (optional path)

Implements the same interface against a chosen public/open source (e.g., an RSS/news feed) using **scheduled polling** (a simple interval-based background task within the same backend process — not a separate worker service, not a queue). If the source is unreachable, the adapter fails gracefully (logs, skips) and the rest of the system is unaffected — this satisfies the "not a dependency" requirement structurally, not just by convention.

### 6.4 Why Polling, Not Streaming

Per DOC1 NFR7 and the live-data analysis in Phase 0: the realistic public sources for this domain (open datasets, RSS/news, public APIs) are not high-frequency streams — polling every few minutes is both sufficient and honest to the actual data cadence. Introducing Kafka/RabbitMQ/WebSockets here would add operational complexity with no corresponding requirement. If the frontend needs to reflect newly polled data, a manual refresh action or a simple periodic REST poll from the frontend is sufficient — no server push infrastructure is introduced.

### 6.5 Dataset Isolation (Synthetic vs. Live)

The live adapter must never contaminate the controlled demo dataset. This is achieved with a **tagging strategy inside the single existing Neo4j database and pipeline** — not a second database, not separate Neo4j instances:

- Every raw record, and every entity/relationship/evidence node written from it, carries a `dataset` property (e.g., `dataset: "synthetic_demo"` or `dataset: "live_public"`), set once at ingestion time by the adapter that produced it and propagated automatically through Extraction → Resolution → Graph Write.
- **Enablement is independent and config-driven:** an environment flag (e.g., `LIVE_ADAPTER_ENABLED=false`) controls whether the live adapter runs at all. The guaranteed demo path runs with this flag off — the live adapter's code exists and is testable, but performs zero writes unless explicitly enabled.
- **Query-time scoping:** the default dataset the frontend/API operates against is `synthetic_demo`. All core read endpoints (Section 14) accept an implicit or explicit `dataset` scope; the demo UI is pointed at `synthetic_demo` by default so a live experiment run in the background (if ever enabled) cannot visibly alter what the audience sees unless the investigator deliberately switches scope or filters to include `live_public`.
- **Same schema, same pipeline, filtered views:** node labels, relationship types, and the entire extraction/resolution/graph/analytics/pattern pipeline are identical for both datasets — isolation is achieved purely through the `dataset` tag and query-time filtering, not through code or schema duplication. This satisfies the requirement to reuse the same pipeline while still preventing accidental cross-contamination of the demo view.
- **Entity resolution stays within a dataset by default:** resolution candidates are matched only within the same `dataset` tag unless a future requirement explicitly calls for cross-dataset resolution — this avoids, for example, a live news mention accidentally merging into a synthetic demo entity.
- This is a minimal, single-property convention, deliberately chosen over a second database or separate Neo4j instance, consistent with the "no infrastructure the requirements don't demand" principle (Section 1.7) — it fully satisfies the isolation goal (prevent an experiment from altering the main demo) without adding operational surface area.

---

## 7. Entity Extraction Architecture

- Implemented as a pipeline stage that takes one normalized raw record at a time (stateless per record), making it naturally reusable for both batch (synthetic) and incremental (live) ingestion without separate code paths.
- Uses spaCy pipelines/NER for structured entity spotting, regex for well-formed identifiers (phone numbers, vehicle plates, account numbers), and the LLM Client for harder cases (ambiguous mentions, relationship phrases in free text) — the LLM is one tool among several here, not the sole extractor.
- Output: a list of candidate entities and candidate relationship mentions, each still tagged with the originating `source_id`, ready for Resolution.

---

## 8. Entity Resolution Architecture

- **Batch mode (primary, guaranteed):** Given the full synthetic dataset's extracted candidates, resolution runs as a bounded clustering process — normalize names, compare shared attributes (phone/vehicle/address/case), apply fuzzy string matching, and optionally sentence-embedding similarity for ambiguous cases — producing canonical entities with recorded rationale. This is well-suited to a batch job since the candidate set is fixed and known in advance.
- **Incremental mode (optional, best-effort — per DOC1 FR11):** When a live adapter is active, new candidates are compared against **already-resolved canonical entities** rather than the full raw candidate pool, keeping the operation cheap, but explicitly accepting that resolution quality against a growing graph is a bounded, demo-level capability, not a production-grade guarantee. This constraint is surfaced in the UI/explanation layer, not hidden.
- Resolution thresholds and rules are configuration, not hardcoded, so they can be tuned against the synthetic dataset without code changes.

---

## 9. Analytics Architecture

- Runs via Neo4j GDS (preferred, since it operates directly on the graph already in Neo4j) or NetworkX (as a fallback for algorithms GDS doesn't conveniently cover) — degree centrality, betweenness centrality, PageRank, community detection (e.g., Louvain), and shortest path.
- Computed **on demand** (triggered by dashboard load or explicit "recompute" action) or on a simple schedule if the live adapter is active. This avoids building incremental-graph-algorithm infrastructure, which is unnecessary complexity for a prototype (per DOC1 FR16 and the live-data analysis).
- Results are cached in-process (or written back as node/relationship properties) for the current snapshot until the next recompute, avoiding redundant computation on every dashboard interaction.

---

## 10. Pattern Detection Architecture

- Implemented as a set of independent, transparent rule modules (e.g., `FrequencyRule`, `SharedAttributeRule`, `BridgeEntityRule`, `TemporalConvergenceRule`), each of which reads graph + analytics data and emits zero or more flagged items.
- Each flagged item includes: the entities/relationships involved, the specific rule/threshold that triggered it, a plain-language explanation, and links to supporting `Evidence` nodes.
- Explicitly rule-based rather than ML-based, per DOC1 FR17 — this keeps every flag explainable by construction, which is a core product requirement (NFR1), not just an implementation convenience.
- All flagged items are consistently surfaced through the API/UI with **investigative-lead language**, never wrongdoing language (enforced at the data-shape level: flagged items carry an explanation field and a fixed disclaimer, not a "guilt score").

---

## 11. Temporal ("Network Time Machine") Architecture

- Built entirely on the timestamp properties already attached to relationships/evidence (Section 5.1) — no separate temporal database or event-sourcing system.
- The API exposes a `GET /graph?asOf=<timestamp>` style endpoint (exact contract in DOC3) that filters relationships/entities to those valid at or before the given time.
- The frontend's Timeline component simply re-queries this endpoint as the slider moves; for a demo-sized dataset this is fast enough to compute at query time without precomputed snapshots.
- Granularity is day-level or event-level, matching source-record timestamps, per DOC1 assumption — no sub-day precision engineering is required.

---

## 12. Ask-the-Network Architecture

Flow:
1. Frontend sends the investigator's NL question to `POST /ask`.
2. Ask-the-Network Service constructs a schema-constrained prompt (graph schema, node/relationship types, and a few example Q→Cypher pairs) and calls the LLM Client to produce a candidate Cypher query.
3. The candidate query is **validated** before execution (e.g., restricted to read-only operations, checked against the known schema) — this guardrail exists specifically because LLM-generated Cypher is a known failure point (per the earlier feasibility analysis).
4. The validated query executes against Neo4j; results (paths, nodes, relationships) are retrieved.
5. The Evidence/Provenance Resolver attaches supporting evidence to the result.
6. The LLM Client is called a second time, this time only to **narrate** the already-retrieved, already-validated graph result in natural language — it does not get to introduce facts not present in the query result.
7. The API returns `{narration, path, evidence}` to the frontend.

This two-call design (query generation, then narration-over-results) is the key architectural safeguard for DOC1 NFR2 ("LLM is never the source of truth") — the LLM's second call is structurally prevented from being the origin of any factual claim, since it is only summarizing data already fetched from Neo4j.

---

## 12A. LLM Degradation Model (Cross-Cutting)

The LLM is used in exactly three places: Entity Extraction (assistive only), Ask-the-Network (query generation + narration), and Case-summary generation. This section defines what happens when the LLM provider is slow, erroring, or unavailable, and applies consistently across all three:

| Component | Behavior without LLM |
|---|---|
| **Entity Extraction** | spaCy and regex extraction continue to run unaffected — these do not call the LLM. Only the LLM-assisted step (ambiguous mentions, free-text relationship phrases) is skipped for that record; the record is still ingested and graphed using whatever spaCy/regex extracted. **Core ingestion and graph construction never depend entirely on the LLM being available**, satisfying the requirement directly. |
| **Ask-the-Network** | The `LLM Client Interface` raises a distinguishable "LLM unavailable" error. The Ask-the-Network Service catches this and returns a clear, explicit response (e.g., `{status: "llm_unavailable", message: "The AI assistant is temporarily unavailable. Try exploring the graph directly, or retry shortly."}`) rather than attempting a partial answer or falling back to an un-narrated raw query result presented as if it were a full answer. **It fails visibly and gracefully — it never invents an answer.** |
| **Case-summary generation** | Same pattern: if the LLM call fails, the API returns a clear "summary generation unavailable" status rather than an empty or fabricated summary. The case's underlying data (entities, notes, evidence) remains fully accessible and manually reviewable regardless — the LLM only ever generates a convenience narrative on top of data the investigator can already see. |

**Implementation mechanism:** the `LLM Client Interface` (Section 3) is the single choke point for this behavior — every caller goes through it, so degradation handling (timeout, retry-once, then surface a typed "unavailable" result) is implemented once, not duplicated per feature. This keeps the guarantee consistent by construction rather than by convention.

This model is also reflected in Section 18 (Failure Points & Recovery Considerations).

---

## 13. Case Workspace Architecture

### 13.1 Data Model Decision

The Case Workspace is represented entirely as graph nodes and relationships in Neo4j — no properties-vs-nodes ambiguity, no second database. The explicit representation is:

| Concern | Representation | Why |
|---|---|---|
| **Case** | `Case` node (`id`, `title`, `created_at`, `status`) | A case is a first-class entity investigators create, list, and open — it needs its own identity, not just a property bag on something else. |
| **Note** | `Note` **node** (`id`, `text`, `created_at`), not a property on `Case` | Notes are multiple, ordered, timestamped, and may individually reference a specific entity or relationship (e.g., "note on why Sameer matters"). A property can't hold this structure cleanly; a node can be queried, ordered, and linked. This resolves the ambiguity DOC2 previously left open. |
| **Case ↔ Entity** | `(:Case)-[:INCLUDES_ENTITY]->(:Person\|Phone\|Vehicle\|...)` | Direct relationship — an investigator explicitly adds an entity to a case; queryable in one hop from either side. |
| **Case ↔ Relationship** | `(:Case)-[:INCLUDES_RELATIONSHIP]->(r)` is not directly expressible in Neo4j (relationships can't be relationship-targets), so this is modeled as `(:Case)-[:INCLUDES_EDGE]->(:EdgeRef {rel_id, from_id, to_id, rel_type})`, where `EdgeRef` is a small pointer node identifying which domain relationship was added to the case | Keeps the case's set of "relationships of interest" queryable and evidence-linkable without denormalizing the underlying domain relationship itself. |
| **Case ↔ Evidence** | `(:Case)-[:INCLUDES_EVIDENCE]->(:Evidence)` | Reuses the same `Evidence` nodes already attached to relationships/patterns (Section 5.1) — a case doesn't get its own copy of evidence, it points at the existing evidence graph, preserving a single source of truth for provenance. |
| **Note ↔ subject** | `(:Note)-[:ABOUT]->(entity \| :EdgeRef \| :Evidence)` (optional) | Lets a note be general (case-level, no `ABOUT` edge) or specific (attached to a particular entity/relationship/evidence item). |

This is a deliberately simple, fully-graph-native model: everything a case needs to reference already exists in the graph or is a small pointer node, so no relational schema, join logic, or second database is required to satisfy FR27.

### 13.2 Behavior

- Case Workspace Service exposes CRUD endpoints: create case, add/remove entity or `EdgeRef`/evidence association, add note (optionally scoped via `ABOUT`), generate summary.
- "Generate investigation summary" calls the LLM Client with the case's associated entities/relationships/evidence/notes (retrieved via the Evidence/Provenance Resolver where evidence is involved) as context, producing a narrative document — narrating existing structured data rather than inventing content. See Section 12A for behavior if the LLM is unavailable.
- No separate case database is introduced (see Section 5.2); if case data volume or query patterns later prove awkward in Neo4j, that would be the documented trigger for reconsidering PostgreSQL — not before.

---

## 14. API Boundaries (Summary — full contracts in DOC3)

Representative REST surface exposed by the FastAPI backend (exact request/response schemas deferred to DOC3):

- `GET /entities/search?q=...`
- `GET /entities/{id}` — entity detail + resolution rationale
- `GET /entities/{id}/relationships` — with evidence
- `GET /graph?asOf=<timestamp>&dataset=<synthetic_demo|live_public|all>&filters=...` — filtered graph for the network view; `dataset` defaults to `synthetic_demo` (see Section 6.5)
- `GET /analytics` — centrality/community/pattern summaries
- `GET /patterns` — flagged investigative leads with explanations
- `GET /evidence/{relationship_id | pattern_id}` — full evidence chain
- `POST /ask` — natural-language question → narrated answer + path + evidence
- `POST /cases`, `GET /cases/{id}`, `POST /cases/{id}/items`, `POST /cases/{id}/notes`, `GET /cases/{id}/summary`
- `POST /ingestion/run` (demo/admin action to trigger synthetic ingestion) and, if the live adapter is enabled, an equivalent trigger or status endpoint for it.

All endpoints that return relationships or flagged items include evidence references inline or via a consistent evidence-lookup pattern — this is an API-design rule, not just a backend implementation detail, so the frontend can never render a claim without a path to its evidence.

---

## 15. Deployment Architecture

- **Frontend:** deployed to Vercel (Next.js-native fit).
- **Backend:** deployed to Render or Railway (simple container/process deployment, no orchestration platform needed).
- **Neo4j:** Neo4j Aura (managed) is the simplest option consistent with "no infrastructure we don't need" — avoids self-managing a database server for a demo. Self-hosted Neo4j in a container is an acceptable fallback if Aura's free/dev tier doesn't fit the dataset size or session needs.
- **Background polling (optional live adapter):** runs as a simple scheduled task within the backend process (e.g., an async periodic task or a lightweight scheduler library) — not a separate worker service or job queue.
- **Configuration:** LLM provider, API keys, and adapter enablement (synthetic-only vs. synthetic+live) are environment-configured, so the guaranteed demo path can be run with the live adapter fully disabled with a single config flag (`LIVE_ADAPTER_ENABLED=false`, Section 6.5). The frontend's default `dataset` scope (`synthetic_demo`) is likewise configuration, not hardcoded, so switching to include live data for a demonstration of extensibility is a deliberate, explicit action.

---

## 16. Security & Trust Boundaries

- The backend is the only component with credentials to Neo4j and the LLM provider; the frontend only ever talks to the backend's REST API.
- No authentication/authorization is implemented for the prototype (per DOC1 NFR8); the deployed demo should be treated as accessible-by-link, not as handling sensitive real data — reinforced by the constraint that only synthetic or public data is ever present in the system.
- The optional live adapter only ever performs outbound read requests to public sources; it never accepts inbound connections or exposes new attack surface beyond the existing backend.
- LLM prompts sent for Ask-the-Network and case summaries are constructed from graph data already scoped to this system — no additional external data is passed to the LLM.

---

## 17. Major Architectural Decisions & Trade-offs

| Decision | Alternative considered | Why this choice |
|---|---|---|
| Monolithic FastAPI backend | Microservices per pipeline stage | No independent scaling/failure requirement exists; microservices would add deployment and coordination complexity with zero corresponding benefit at this scale. |
| Neo4j only (no PostgreSQL) | Neo4j + PostgreSQL for case/user data | Case data is graph-shaped; adding a second database means two schemas, two sources of truth, and extra ops work with no concrete requirement forcing it (per DOC1 constraint). |
| Scheduled polling for live adapter | Kafka/streaming ingestion | Realistic public sources for this domain aren't high-frequency; polling matches actual data cadence and avoids unjustified infrastructure. |
| Query-time "asOf" filtering for Time Machine | Full temporal/versioned graph database | Demo-sized dataset makes query-time filtering fast enough; a versioned graph store would be substantial extra engineering for no visible demo benefit. |
| Two-call LLM design for Ask-the-Network (generate query, then narrate results) | Single LLM call that "answers" directly | Structurally prevents the LLM from inventing facts — directly satisfies the "LLM is never the source of truth" requirement rather than relying on prompt instructions alone. |
| Rule-based pattern detection | ML/learned anomaly detection | Explainability is a hard product requirement; rules are inspectable by construction, an ML model would need its own explainability layer for no added value at this data scale. |
| Source-adapter interface from day one | Hardcode synthetic loading, retrofit live support later | Costs little now, avoids a rewrite if/when the live adapter is built, and directly satisfies the DOC1 requirement that the core system stay decoupled from any specific source. |
| Batch-first entity resolution, incremental as best-effort | Build robust incremental resolution now | Batch resolution is what the guaranteed demo path actually needs; incremental resolution correctness at graph scale is a genuinely hard problem better scoped as documented future work than solved prematurely. |
| Dataset-tagging for isolation (single Neo4j DB, `dataset` property + query-time filter) | Separate Neo4j databases/instances per source | A single property and default query scope fully prevents an accidental live-data write from altering the demo view; a second database instance would add real operational overhead for a problem a tag already solves. |

---

## 18. Failure Points & Recovery Considerations

| Failure point | Impact | Mitigation |
|---|---|---|
| Live adapter source unreachable | Optional adapter silently yields no new data | By design — core system unaffected; logged, not surfaced as an error to the demo user unless explicitly checking live-adapter status |
| LLM API unavailable/slow | Ask-the-Network and case-summary generation cannot produce their LLM-driven output | Both fail gracefully with an explicit "unavailable" status (never a fabricated answer) per the LLM Degradation Model, Section 12A; extraction continues via spaCy/regex, so core ingestion and graph construction are unaffected |
| LLM generates invalid/unsafe Cypher | Could return wrong data or fail | Query validation step (Section 12) rejects non-read-only or schema-violating queries before execution |
| Neo4j unavailable | Full system outage (it's the system of record) | Out of scope to mitigate further for a demo (no case for HA infrastructure here); operationally, ensure Neo4j Aura instance is warmed up before a live demo |
| Entity resolution false-merge/false-split | Misleading graph structure | Resolution rationale is inspectable (FR10) so errors are visible and explainable rather than hidden; thresholds are configurable for demo tuning |

---

*End of DOC2. Awaiting approval before proceeding to DOC3 — Contracts & Interfaces.*
