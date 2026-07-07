## 1. Persistence and Compatibility

- [x] 1.1 Add migrations for generic channel fields on `agent_session` and `agent_job`, including source channel, connector ID, external event/conversation IDs, requester identity, routing context JSON, and reply route JSON.
- [x] 1.2 Add `delivery_attempt` and `delivery_chunk` persistence with job linkage, status, safe target summary, safe error summary, timestamps, and indexes.
- [x] 1.3 Add or extend connector configuration persistence for connector type, enabled flag, `allow_ingress`, `allow_delivery`, secret/endpoint references, host allowlist, and metadata.
- [x] 1.4 Update repository read/write methods so new records write generic fields while legacy DingTalk fields remain readable as fallback.
- [x] 1.5 Seed local connector configuration for debug, DingTalk webhook robot, DingTalk enterprise robot, Grafana alert webhook, email, generic webhook, and none route.

## 2. Channel Domain and Job Creation

- [x] 2.1 Create `channel` domain DTOs for `ChannelEvent`, `ChannelSource`, `RoutingContext`, `ReplyRoute`, and safe raw payload summaries.
- [x] 2.2 Refactor `CreateAgentJobCommand` away from DingTalk-specific names to requester/source/routing/reply-route fields.
- [x] 2.3 Update `CreateAgentJobService` to validate connector ingress authorization, user/service account permissions, routing context, and reply route before persistence.
- [x] 2.4 Preserve existing debug API behavior by mapping debug requests into Channel events with `delivery.type=none` unless a delivery override is provided.
- [x] 2.5 Add unit tests for generic Channel event creation, idempotency key handling, legacy DingTalk fallback reads, and message bus payload remaining `job_id` plus `correlation_id`.

## 3. DingTalk Channel Adapter

- [x] 3.1 Refactor existing DingTalk webhook handling to verify signatures and then map payloads into generic Channel events.
- [x] 3.2 Support DingTalk enterprise robot and DingTalk webhook robot connector types with configurable `allow_ingress` and `allow_delivery`.
- [x] 3.3 Preserve duplicate DingTalk webhook behavior by deriving stable idempotency keys from DingTalk message IDs.
- [x] 3.4 Update DingTalk tests to verify generic source metadata, reply route persistence, invalid signature rejection, unauthorized requester rejection, and duplicate delivery behavior.

## 4. Grafana Alert Ingress

- [x] 4.1 Add Grafana webhook route and adapter with connector token/signature verification.
- [x] 4.2 Implement `status=firing` filtering so firing alerts create Agent jobs and `resolved` alerts return ignored acknowledgement without creating jobs.
- [x] 4.3 Extract `ea_project_code`, `ea_environment`, `ea_base`, `ea_workshop`, `ea_service`, `ea_delivery_type`, and `ea_delivery_connector_id` labels into routing and delivery fields.
- [x] 4.4 Reject Grafana firing alerts missing required `ea_*` routing labels with safe audit events and no queue dispatch.
- [x] 4.5 Add tests for firing job creation, resolved ignored behavior, missing label rejection, duplicate Grafana delivery, and service-account permissions.

## 5. Result Delivery Service

- [x] 5.1 Create `delivery` domain and application services for reply-route resolution, report chunking, delivery attempts, and delivery chunks.
- [x] 5.2 Implement delivery adapters for `none`, DingTalk webhook robot, DingTalk enterprise robot, email, and generic webhook, with fake adapters for tests.
- [x] 5.3 Enforce connector `allow_delivery` and endpoint host allowlists before sending external HTTP delivery.
- [x] 5.4 Implement chunked delivery for long reports with `part x/y` markers and persisted per-chunk statuses.
- [x] 5.5 Ensure delivery failures update delivery status without changing successful Agent job status or re-running Agent execution.
- [x] 5.6 Add tests for one-chunk delivery, multi-chunk delivery, adapter failure, denied connector, denied host, `none` delivery, and safe error summaries.

## 6. Worker and Runtime Integration

- [x] 6.1 Replace direct DingTalk callback usage in `AgentExecutor` success path with `ResultDeliveryService.deliver_job_result`.
- [x] 6.2 Replace direct DingTalk failure notice usage in `AgentJobWorker` dead-letter path with `ResultDeliveryService.deliver_job_failure`.
- [x] 6.3 Keep AgentExecutor independent from DingTalk, Grafana, email, webhook clients, and RabbitMQ implementation details.
- [x] 6.4 Add duplicate RabbitMQ delivery tests proving completed jobs do not re-run and do not resend completed delivery attempts.
- [x] 6.5 Add failure-path tests proving delivery failure does not mark Agent job FAILED when Agent execution already SUCCEEDED.

## 7. Audit, Permission, and Query Visibility

- [x] 7.1 Add audit events for channel receipt, credential verification, channel normalization, ignored Grafana events, connector authorization, delivery attempts, delivery chunks, and delivery completion/failure.
- [x] 7.2 Extend permission checks to cover requester identity, service account sources, source connector ingress authorization, delivery connector authorization, and project/routing scope.
- [x] 7.3 Add safe summaries for raw Channel payloads and delivery targets without persisting tokens, secrets, or full webhook URLs.
- [x] 7.4 Extend debug/query APIs or repository methods so tests can inspect delivery attempts and delivery chunks for a job.
- [x] 7.5 Add audit/permission tests for unauthorized connector ingress, unauthorized delivery connector, ignored Grafana event, and masked connector secrets.

## 8. Documentation and Validation

- [x] 8.1 Update backend README with the new `from` / `delivery` / `routing` request contract and examples for Debug API, DingTalk, and Grafana.
- [x] 8.2 Document required Grafana `ea_*` labels and the `firing`-only behavior.
- [x] 8.3 Document connector configuration examples for DingTalk webhook robot, DingTalk enterprise robot, Grafana, email, generic webhook, and none.
- [x] 8.4 Run targeted backend tests for channel ingress, DingTalk, Grafana, delivery, worker idempotency, audit, and permissions.
- [x] 8.5 Run full project validation with `make check` and `openspec validate add-channel-ingress-and-delivery`.
- [x] 8.6 Manually verify a local debug job still completes with `delivery.type=none` and a Grafana firing sample creates a job without embedding Channel payload in RabbitMQ.
