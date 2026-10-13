# AGENTS.md — Instructions for Implementation Agents

This repository follows a documentation-driven, multi-track workflow. The approved documents, in binding order, are:

```
DOC1 (Project Specification) → DOC2 (Technical Architecture) → DOC3 (Contracts & Interfaces) → DOC4 (Build Plan) → docs/tasks/<track>/<TaskID>.md
```

Each layer is subordinate to the ones before it. A task document never overrides DOC1–DOC4; if a task appears to require something DOC1–DOC4 don't define, that is a defect to flag, not a decision to make silently.

## If you have been asked to implement a task (e.g., "Implement A3")

1. Read this file.
2. Read `docs/DOC1_PROJECT_SPECIFICATION.md`.
3. Read `docs/DOC2_ARCHITECTURE.md`.
4. Read `docs/DOC3_CONTRACTS.md` — this is your binding interface contract. Do not deviate from it.
5. Read `docs/DOC4_BUILD_PLAN.md`, specifically the section for your assigned task's track.
6. Read `docs/tasks/<track>/<TaskID>.md` — your assigned task specification.
7. Implement **only** the assigned task. Do not implement other tasks, do not "helpfully" extend scope, and do not modify files outside what your task document lists under "Files/Modules to Create or Modify" unless a genuine defect requires flagging.
8. Write/update tests as specified under "Tests Required" in your task document.
9. Do not silently redesign an interface — if DOC3 seems to be missing something your task needs, stop and flag it rather than inventing a resolution.

## Repository structure

See DOC4 §2 for the full intended repository layout (backend, frontend, data, config, scripts).

## Source of truth hierarchy

1. Approved DOC1 — Project Specification
2. Approved DOC2 — Technical Architecture
3. Approved DOC3 — Contracts & Interfaces
4. Approved DOC4 — Build Plan
5. Individual task specifications (`docs/tasks/<track>/<TaskID>.md`)
6. Code

Implementation must never silently contradict the approved documentation. If implementation reveals that an architectural or contract decision needs to change, the process is: identify the problem, explain the impact, propose the change, get explicit approval, update the relevant document, then implement.

## Track summary (see DOC4 for full detail)

- **Track A — Backend/Foundation:** FastAPI skeleton, config, shared contract types, Neo4j connection, LLMClient, error envelope.
- **Track B — Data Pipeline / Extraction / Resolution:** Source adapters, ingestion orchestrator, entity/relationship extraction, entity resolution.
- **Track C — Neo4j / Graph / Evidence:** Schema, Graph Write Layer, Evidence/Provenance Resolver, `as_of` filter, graph/entity API endpoints.
- **Track D — Analytics / Pattern Detection / Time Machine:** Analytics service, pattern rules, Finding persistence, analytics/patterns API endpoints.
- **Track E — Frontend / Investigation UI:** Next.js dashboard components (NetworkView, EntityPanel, EvidencePanel, Timeline, AnalyticsPanel, FiltersAndSearch, AskTheNetwork, CaseWorkspace).
- **Track F — Ask-the-Network / LLM:** NL→Cypher generation, validation, execution, evidence attachment, narration, Ask API endpoint.
- **Track G — Case Workspace:** Case/Note/EdgeRef associations, summary generation, Case Workspace API endpoints.
- **Track H — Integration / Testing / Deployment:** Synthetic dataset, deployment scaffolding, cross-track integration and contract tests, contract-drift check, final demo rehearsal.

## Non-negotiable constraints (apply to every task, every track)

- No microservices, message brokers (Kafka/RabbitMQ), Kubernetes, WebSockets, or a second database (PostgreSQL/etc.) unless a future, explicitly-approved document amendment introduces them. None currently do.
- Every `Relationship` and `Finding` must carry non-empty evidence before being written or returned (DOC3 Contract Invariant 1).
- The LLM never originates a factual claim reaching the user (DOC3 Contract Invariant 3) and its unavailability never blocks core functionality (Invariant 4).
- Entity Resolution, Analytics, and Ask-the-Network never mix `synthetic_demo` and `live_public` data (Invariant 2).
- The live/public data adapter is never a dependency of the core, demoable system (Invariant 7).
- See DOC3 §15 for the full list of 16 binding Contract Invariants — every task document cites the specific ones relevant to it.

## Implementation Discipline

- Prefer the smallest implementation that satisfies the assigned task and its acceptance criteria.
- Do not add dependencies, abstractions, frameworks, infrastructure, or configuration unless required by the approved documents or task specification.
- Preserve existing behavior outside the assigned task.
- Before modifying an existing interface, verify it against DOC3 and the relevant task specification.
- Run the required tests before declaring the task complete.
- If a test, build, type check, or integration step fails because of an issue outside the assigned task, do not silently rewrite unrelated code. Report the failure and identify the likely owning task/track.
- At task completion, report:
   1. Files created or modified
   2. Implementation completed
   3. Tests added/updated
   4. Tests/checks run and their results
   5. Any deviations or blockers
   6. Any follow-up required by another task
- Do not mark a task complete when its acceptance criteria are not satisfied.
