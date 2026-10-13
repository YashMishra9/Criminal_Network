# DOC1 — Project Specification
## AI-Powered Criminal Network Analysis System

**Status:** Draft — pending approval
**Depends on:** Phase 0 (approved)
**Precedes:** DOC2 — Technical Architecture

---

## 1. Problem Statement

Investigators working with intelligence data face a fragmentation problem: relevant information about people, communications, transactions, vehicles, and events arrives from many disconnected sources (FIRs, police reports, call records, financial records, surveillance notes, social media, vehicle registries). The same real-world entity frequently appears under different names, identifiers, or partial records across these sources. Manually cross-referencing these fragments to build a coherent picture of a network — who is connected to whom, how, and why it matters — is slow, error-prone, and difficult to justify or explain after the fact.

A system that automates this cross-referencing risks a second problem: producing connections or conclusions that look authoritative but aren't traceable back to source evidence, or that imply guilt where only structural correlation exists.

## 2. Goals

- Demonstrate an end-to-end pipeline that converts fragmented, multi-source intelligence data into a connected, explorable knowledge graph.
- Make every system-generated connection and finding **traceable to its source record(s)**.
- Surface network structure and patterns as **investigative leads**, never as claims of wrongdoing.
- Provide an interactive dashboard that lets an investigator explore entities, relationships, evidence, and how the network evolves over time.
- Provide a natural-language interface ("Ask the Network") that answers questions by querying the actual graph — not by generating unfounded answers.
- Produce a convincing, reliable, end-to-end **live demo** suitable for a hackathon setting.
- Build the ingestion layer to be source-agnostic (synthetic and public/live data through the same pipeline) without taking on the cost or risk of production streaming infrastructure.

### Non-goals
This system is a prototype demonstrating a concept and workflow. It is explicitly not attempting to be a production law-enforcement platform, a predictive policing tool, or a system that integrates real restricted law-enforcement data.

## 3. Users

**Primary persona: Investigator / Analyst (demo user)**
Explores a case, searches for entities, inspects relationships and their evidence, runs analytics, moves the timeline, asks natural-language questions of the graph, and assembles findings into a case summary.

The prototype assumes a **single controlled user/session** per the approved Phase 0 decision — no multi-user roles, permissions, or tenancy are in scope.

## 4. User Workflows

**W1 — Explore a pre-built network**
Investigator opens the dashboard, sees the current graph, searches for or selects an entity, and inspects its connections and evidence.

**W2 — Trace a connection**
Investigator selects two entities and asks "how are these connected?" (via UI action or Ask-the-Network), and the system returns the actual path with supporting evidence.

**W3 — Investigate a flagged pattern**
Investigator reviews a list of system-flagged patterns (e.g., a bridge entity, an unusual transaction chain), opens the explanation for why it was flagged, and inspects the evidence behind it.

**W4 — Replay network evolution**
Investigator moves a timeline control and watches entities/relationships appear according to when the underlying source records occurred, to understand how the network formed.

**W5 — Ask the Network**
Investigator types a natural-language question; the system translates it into a graph query, executes it against Neo4j, and returns a narrated answer grounded in the actual query result plus evidence.

**W6 — Build a case**
Investigator creates a case, adds relevant entities/relationships/evidence to it, writes notes, and generates an investigation summary document from the collected material.

**W7 — Ingest fragmented sources (setup/demo workflow)**
System (or operator, at demo time) loads multiple distinct source files/feeds; the audience/investigator sees the "6 sources → 1 graph" transformation, including entity resolution collapsing aliases into single entities.

## 5. Functional Requirements

**Data & Ingestion**
- FR1: The system shall ingest data through a **common ingestion layer** accessed via **pluggable source adapters**, so that synthetic file-based sources and public/live sources both feed the same downstream pipeline.
- FR2: The system shall ship with at least one synthetic-data adapter as the primary, dependency-free demo path.
- FR3: The system may optionally ship one public/open live-data adapter (e.g., an RSS/news feed), used to demonstrate ingestion-layer extensibility. This adapter is **optional and non-blocking** — its unavailability must not affect the core demo.
- FR4: Live/public adapters shall use scheduled polling (not continuous streaming) to retrieve new data.
- FR5: Every ingested record shall retain a source identifier, source type, and timestamp for downstream provenance.

**Entity Extraction**
- FR6: The system shall extract defined entity types (Person, Phone, Vehicle, Location, Organization, Bank Account, Event, Case) from ingested records using a combination of NLP (spaCy), regex, and LLM assistance.
- FR7: Entity extraction shall operate on individual records/documents independently, so it can run on both batch-loaded and incrementally-arriving data without redesign.

**Entity Resolution**
- FR8: The system shall resolve multiple representations of the same real-world entity (name variants, shared identifiers such as phone/vehicle/address) into a single graph node.
- FR9: Entity resolution shall use a combination of name normalization, fuzzy matching, shared-attribute matching, and embeddings where useful.
- FR10: Entity resolution decisions shall be inspectable — an investigator can see why two records were merged into one entity.
- FR11 (scoped): Entity resolution is required to work correctly against a **batch/bounded dataset**. Resolution against a continuously-growing live graph is a bounded, best-effort capability for the prototype, not a guaranteed-correct one (see Section 9, Out of Scope, and Section 8, Constraints).

**Knowledge Graph**
- FR12: The system shall store resolved entities and relationships in Neo4j, using the node and relationship types defined for this domain (Person, Phone, Vehicle, Location, Organization, Bank Account, Transaction, Case, Event, Evidence; CALLED, OWNS, USED, TRANSFERRED, VISITED, MET, WORKS_FOR, ASSOCIATED_WITH, MENTIONED_IN, PART_OF).
- FR13: Every relationship shall retain a link to its supporting source record(s) — no relationship may exist in the graph without traceable evidence.
- FR14: The graph shall support incremental updates (new entities/relationships added without requiring a full rebuild).

**Analytics**
- FR15: The system shall compute degree centrality, betweenness centrality, PageRank, community detection, and shortest path over the graph, using Neo4j GDS or NetworkX.
- FR16: Analytics shall be computed on-demand or on a schedule over graph snapshots; true continuous/incremental analytics is out of scope.

**Pattern Detection**
- FR17: The system shall flag investigable patterns (e.g., unusually frequent communication, shared identifiers, rapid financial transfers, bridge entities, temporal convergence) using transparent rules and graph analytics — not opaque ML classification.
- FR18: Every flagged pattern shall be accompanied by a plain-language explanation of why it was flagged and a link to supporting evidence.
- FR19: The system shall never present a flagged pattern as a claim of wrongdoing. All flagged items shall be labeled as investigative leads.

**Evidence & Provenance**
- FR20: The system shall preserve source record IDs, timestamps, and supporting details for every relationship and every flagged pattern, regardless of whether the originating data was synthetic or live/public.

**Temporal Exploration**
- FR21: The system shall support a timeline control that reconstructs the graph's state at different points in time, using day-level or event-level granularity, based on source-record timestamps.

**Ask-the-Network (AI Assistant)**
- FR22: The system shall accept natural-language questions about the graph, translate them into a graph query (e.g., Cypher), execute the query against Neo4j, and return a narrated answer.
- FR23: The narration shall be grounded strictly in actual query results and evidence; the LLM shall not independently assert relationships or facts not present in the graph.
- FR24: The LLM component shall be accessed behind a replaceable service interface, not hard-coded to a specific provider/model.

**Dashboard**
- FR25: The system shall provide an interactive network visualization (pan, zoom, select, filter, highlight paths) using Cytoscape.js.
- FR26: The system shall provide an entity panel, an evidence panel, a timeline, an analytics/patterns panel, filters (entity type, relationship type, date, source, community, pattern), and search across entity types.

**Case Workspace**
- FR27: The system shall let a user create a case, associate entities/relationships/evidence with it, add notes, and generate an investigation summary from the collected case material.

## 6. Non-Functional Requirements

- NFR1: **Explainability** — every graph-derived finding, relationship, and flagged pattern must be traceable to source evidence; the system must never present unexplained conclusions.
- NFR2: **Evidence as ground truth** — the LLM is a translator/narrator, never a source of truth. Actual database/query results are authoritative.
- NFR3: **Demo reliability** — the core demo path (synthetic data) must function fully with zero dependency on external network services being available at demo time.
- NFR4: **Modularity without over-engineering** — the simplest architecture that satisfies these requirements is preferred; components (LLM, data sources, optional relational storage) must be replaceable/extensible without becoming distributed-systems infrastructure the project doesn't need.
- NFR5: **Reasonable extensibility** — the synthetic dataset should be able to grow in size without requiring a pipeline rewrite (though performance at large scale is not a target for this prototype).
- NFR6: **Data-source legality and privacy** — only synthetic data or legitimately public/open, ToS-compliant data sources may be used; no private, leaked, restricted, or unauthorized law-enforcement data; real-world data involving identifiable private individuals is to be avoided.
- NFR7: **No unnecessary infrastructure** — no message brokers, streaming platforms, or WebSocket-based real-time push are to be introduced unless a concrete, documented requirement demands them.
- NFR8: **Single-user/session** — no authentication, authorization, or multi-tenancy complexity is required unless a specific need is identified.

## 7. Core Features (in scope for the prototype)

1. Cross-source entity resolution
2. Evidence-backed relationships
3. Network Time Machine (temporal replay)
4. Explainable pattern detection
5. Evidence-grounded Ask-the-Network assistant
6. Case Workspace
7. Pluggable ingestion layer (synthetic + optional public/live adapter)

## 8. Scope

**In scope**
- Synthetic, intentionally fragmented and messy demo dataset across the listed data source types.
- Entity extraction, resolution, graph construction, analytics, and rule-based pattern detection over that dataset.
- A modular ingestion layer with a source-adapter interface, shipped with a synthetic adapter and, optionally, one public/open live-data adapter using scheduled polling.
- Full dashboard: network view, entity/evidence panels, timeline, analytics, filters, search.
- Ask-the-Network natural-language-to-Cypher assistant, grounded in actual graph results.
- Case workspace with notes and generated summary.
- Clear provenance/evidence trail for every relationship and finding, from both synthetic and any live source.

**Out of scope**
- Training a custom LLM or GNN.
- A crime-prediction / risk-scoring ML model.
- Facial recognition.
- Integration with real police/law-enforcement databases or real CDR providers.
- Nationwide-scale infrastructure or performance targets.
- True real-time streaming infrastructure (Kafka/RabbitMQ, WebSockets, continuous incremental analytics).
- Production-grade authentication, authorization, or multi-agency/multi-tenant access control.
- Guaranteed-correct entity resolution against a continuously-growing live graph (best-effort only, see FR11).
- Any use of real data involving identifiable private individuals.

## 9. Constraints

- Hackathon/demo timeline — engineering effort must prioritize a convincing, reliable end-to-end narrative over completeness or production robustness.
- Core demo must run fully offline from external live-data dependencies.
- Only public/open, legally accessible, ToS-compliant data may be used for any non-synthetic source.
- Neo4j is the system of record for graph data; a second (relational) database is only to be introduced if a concrete requirement cannot reasonably be met by Neo4j, with that reason documented at the time.
- LLM provider is undecided and must remain swappable behind a service interface.

## 10. Assumptions

- This is a hackathon/portfolio-grade prototype, not a production system, and will be evaluated on demo strength and conceptual soundness rather than production hardening.
- A single investigator/session is sufficient; no concurrent multi-user access is required.
- Synthetic data volume will start "meaningful but demo-sized" (dozens–low hundreds of entities), with exact numbers finalized during synthetic dataset design, not fixed in this document.
- If a live/public adapter is built, it will pull from sources concerning public entities (organizations, public officials in official capacity, public case metadata) — not private individuals.
- Day-level or event-level timeline granularity is sufficient; no sub-day/real-time temporal precision is required.

## 11. Success Criteria

The prototype is successful if it can demonstrate, live and reliably, the following narrative without relying on any unavailable external dependency:

1. Multiple distinct fragmented sources are loaded and shown as separate/messy inputs.
2. Entity resolution visibly collapses alias records (e.g., name variants) into single entities.
3. A connected knowledge graph is constructed from the resolved entities and relationships.
4. Graph analytics identify structurally significant entities and communities.
5. Pattern detection flags investigable leads, each with a stated reason.
6. Every relationship and flagged pattern can be traced to specific source evidence on demand.
7. The timeline control visibly replays network formation over time.
8. A natural-language question to Ask-the-Network returns an actual graph path with evidence, not an invented answer.
9. A case can be created, populated, and summarized from material gathered during the above steps.
10. The ingestion layer's source-adapter design is demonstrable or explainable as extensible to live public sources, even if only the synthetic adapter is exercised live during the demo.

---

*End of DOC1. Awaiting approval before proceeding to DOC2 — Technical Architecture.*
