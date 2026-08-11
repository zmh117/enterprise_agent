## 1. Fact-Source Baseline

- [x] 1.1 Re-read the current immutable migration catalog and active changes, confirm Baseline `100` as the required predecessor, and allocate unoccupied expand/backfill/contract versions without changing an existing migration
- [x] 1.2 Add a machine-readable schema fact-source manifest schema covering owner, semantics, classification, canonical source, writer, reader, retention, migration phase, retirement gate, and evidence reference
- [x] 1.3 Populate the manifest for Session, Job, Message, Workflow draft/publication, all four Outbox stages, Runtime ledger/claim/event, ONES identity challenge, publication/history/audit, and `job_dispatch_cutover_quarantine`
- [x] 1.4 Inventory production code, tests, CLI/runbooks, management queries, Runtime implementations, and declared external readers/writers for every compatibility column and retirement candidate
- [x] 1.5 Add validation that rejects unknown classifications, missing owners/readers/writers, compatibility shadows without an exit gate, and immutable snapshots without a source revision/hash contract
- [x] 1.6 Add a CI check that reconciles manifest object names with the supported PostgreSQL/SQLite schema catalogs and reports drift without reading data rows

## 2. Safe Preflight and Characterization

- [x] 2.1 Add characterization tests proving current Session/Job write duality, read fallback, Job/message duplication, and Workflow graph assembly before refactoring
- [x] 2.2 Implement a read-only consolidation preflight that verifies migration head/checksum, compatibility-field parity, Job-to-user-message cardinality, Workflow graph parity, pending Outbox/retry/recovery state, and retirement-candidate usage
- [x] 2.3 Ensure preflight output contains only schema versions, stable record IDs where required, classifications, counts, and bounded error codes—never message bodies, graph configuration bodies, credentials, or raw business payloads
- [x] 2.4 Add fixture coverage for exact parity, missing canonical facts, conflicting old/new fields, zero/multiple user messages, graph-only drafts, normalized-only drafts, divergent graphs, pending retries, and active Runtime recovery claims
- [x] 2.5 Make all migration/backfill commands dry-run and fail-closed by default, requiring an explicit apply mode, expected schema head, target confirmation, and operator-supplied evidence location for data writes

## 3. Workflow Fact-Source Consolidation

- [x] 3.1 Add deterministic normalized graph serialization with stable node/edge ordering, schema versioning, validation, and config hashing
- [x] 3.2 Change Workflow draft reads, validation, preview, and publication to use template metadata plus normalized node/edge rows and never merge in `graph_json`
- [x] 3.3 Make Workflow publication read a single locked/expected draft revision and reject concurrent edits instead of producing a mixed snapshot
- [x] 3.4 Add a re-runnable Workflow backfill that parses `graph_json` only when normalized rows are absent, rejects dual-nonempty divergence, and records safe checkpoint/evidence metadata
- [x] 3.5 Stop Workflow template writes from updating `graph_json` after verified read cutover while preserving immutable publication `graph_snapshot_json`
- [x] 3.6 Add repository/service/API tests for empty drafts, node/edge edits, deterministic publication hash, concurrent revision conflict, post-publication draft edits, and operation when `graph_json` is absent

## 4. Session, Job, and Message Consolidation

- [x] 4.1 Refactor Session domain and repository reads to require generic Channel/Connector/conversation/requester facts plus Application Publication and execution-scope isolation, with no DingTalk-field fallback on the canonical path
- [x] 4.2 Change session-key construction so Business Application ID, Application Publication ID, execution scope, Project, Channel, Connector, conversation type, and external identity form the deterministic isolation boundary
- [x] 4.3 Preserve historical Sessions as read-only and add tests proving a new Application Publication or execution scope creates a new Session without copying old messages or summaries
- [x] 4.4 Refactor Job domain/repository reads so generic source/requester, Project, fixed Agent/Application provenance, status/retry/result, and immutable execution snapshots are explicit facts
- [x] 4.5 Make the single ordered role=`user` `agent_message` associated with a Job the user-message source used by Agent context, retries, debug/management API assembly, and history views
- [x] 4.6 Add database/application invariants that prevent zero or multiple canonical input messages for new executable Jobs while retaining an explicit read-only state for irreparable legacy history
- [x] 4.7 Change Job creation to atomically persist/resolve Session, persist the canonical user message, create the Job, and create Job dispatch outbox without writing Session/Job compatibility shadows
- [x] 4.8 Keep Job query response semantics stable by joining/projecting the canonical message and generic facts rather than exposing removed physical columns
- [x] 4.9 Remove compatibility fallbacks and shadow fields from domain constructors, repositories, context builders, API assemblers, tests, fixtures, and operational queries after read cutover evidence passes
- [x] 4.10 Add regression tests for Channel creation, debug creation, idempotent duplicate ingress, retries, result delivery, historical `legacy_unattributed`/message-unavailable views, and absence of compatibility columns

## 5. Operational Facts and Retirement Gates

- [x] 5.1 Add tests or architecture checks that keep Webhook, Channel ingress, Job dispatch, and Delivery outbox writers/consumers mapped to their own transaction boundaries and prohibit cross-stage replacement dual writes
- [x] 5.2 Add Runtime recovery acceptance coverage proving terminal ledger and invocation claim/event remain required for duplicate delivery, ownership, expiration, replay, and terminal recovery even when their tables begin empty
- [x] 5.3 Register ONES identity challenge and immutable publication/history/audit objects as retained facts, and verify consolidation scripts never select, log, backfill, truncate, or drop their sensitive contents
- [x] 5.4 Evaluate `job_dispatch_cutover_quarantine` against every retirement gate in each target environment; prepare contract removal only if all gates pass, otherwise record `blocked` with owner and unmet conditions
- [x] 5.5 Add a retirement-evidence validator that rejects approval based only on zero rows, `legacy`/`cutover` naming, local static search, or a single-environment observation

## 6. Migration Artifacts and Rollback

- [x] 6.1 Add the uniquely numbered expand migration for any canonical message linkage, constraints, indexes, manifest support, and non-destructive compatibility needed by the verified backfill
- [x] 6.2 Implement re-runnable, batched Session/Job/Message and Workflow backfill checkpoints with bounded transactions, high-water marks, rate controls, parity assertions, and safe progress output
- [x] 6.3 Add read-cutover and write-cutover version/runbook boundaries so each can be deployed and rolled back before schema contract without creating a permanent top-level feature flag
- [x] 6.4 Add a contract precondition that aborts if parity, message cardinality, graph equivalence, zero old-column access, pending retry/recovery, retention, backup, approval, or expected-head evidence is missing
- [x] 6.5 Add the uniquely numbered contract migration that drops only approved Session/Job shadows and Workflow `graph_json`, and conditionally handles `job_dispatch_cutover_quarantine` according to its signed retirement decision
- [x] 6.6 Test migrations from empty database, exact Baseline `100`, representative legacy snapshots, interrupted backfill, concurrent migrator, precondition failure, and successful forward-only contract
- [x] 6.7 Document rollback before contract as application rollback with preserved columns, and after contract as verified backup restore or forward fix without modifying immutable migrations

## 7. Verification and Documentation

- [x] 7.1 Run focused backend tests for Job, Channel, Workflow, Outbox, Runtime recovery, identity challenge, migration runner, and schema verification using the repository virtual environment
- [x] 7.2 Run full backend and relevant Web checks, distinguish change-caused failures from pre-existing failures, and record commands and bounded results
- [ ] 7.3 Run schema/comment verification for PostgreSQL and SQLite representations and confirm dropped compatibility objects have no production SQL, model, fixture, or documentation references
- [ ] 7.4 Exercise the local Runtime → Inbox/Outbox → RabbitMQ → Job → Worker → Delivery chain, including duplicate ingress, retry, recovery, publication isolation, history read, and Workflow publication
- [x] 7.5 Update migration and operations documentation with stage commands, authority boundaries, backup/restore, safe evidence fields, stop conditions, and explicit prohibition on automatic real-database writes
- [x] 7.6 Validate this OpenSpec change strictly, run repository diff checks, and record which claims are `Confirmed-current`, `Documented-intent`, `Observed-local`, or still deployment-gated

## 8. Separately Authorized Rollout

- [ ] 8.1 Obtain explicit target, backup, maintenance-window, and operator authorization before any real database write; do not treat code merge, image build, test, startup, or OpenSpec apply as authorization
- [ ] 8.2 Verify and, under its own authorization, complete exact `042 → 100` Baseline Adoption before running any consolidation migration
- [ ] 8.3 Deploy expand artifacts and execute verified backfill in the authorized environment, preserving safe checkpoint and rollback evidence
- [ ] 8.4 Deploy and validate read cutover while old writes remain available for application rollback
- [ ] 8.5 Deploy and validate write cutover, then observe at least one complete retry/recovery retention cycle and one production release cycle with zero legacy access
- [ ] 8.6 Obtain domain, Runtime, database, security/audit, and operations sign-off for every field/table retirement decision; keep failed candidates `blocked`
- [ ] 8.7 Execute the contract migration only in a separately authorized maintenance window with global migration lock and verified backup, then run post-contract acceptance
- [ ] 8.8 Archive bounded migration and retirement evidence without raw messages, graph bodies, secrets, credentials, or business payloads, and only then mark deployment-gated tasks complete
