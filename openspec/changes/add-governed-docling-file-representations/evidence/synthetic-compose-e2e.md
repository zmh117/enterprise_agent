# Synthetic Compose E2E — 2026-08-21

## Scope and isolation

The acceptance run used generated, non-business samples only. The reusable drivers are:

- `scripts/generate_docling_synthetic_samples.py`
- `scripts/run_docling_compose_e2e.py`
- `docker-compose.synthetic-e2e.yml`

The overlay rendered and ran as project `enterprise_agent_docling_e2e` with dedicated
PostgreSQL, RabbitMQ and MinIO volumes. The fresh database applied all 16 ledger entries
through migration 115 before any synthetic application was created. Source bytes,
extracted Markdown/JSON, object keys, credentials and reply payloads were never printed.

An initial isolation preflight exposed that the base Compose file assigns explicit global
volume names. That first attempt was stopped immediately because project naming alone did
not isolate those volumes. It caused the main PostgreSQL process to restart, but no
synthetic fixtures were written to the main database. The main database completed recovery
and subsequent checkpoints; its ledger remains `16:115`, and PostgreSQL, API, File Service
and File Worker are healthy. The overlay now overrides all three data volumes with explicit
`enterprise_agent_docling_e2e_*` names so this collision cannot recur.

## Confirmed business evidence

The fresh synthetic run submitted DOCX, PPTX, XLSX, PDF, PNG, JPEG and WebP through the
internal DingTalk Runtime lease/Inbox endpoint. The channel outbox and RabbitMQ attachment
queue were consumed by the real channel and File Worker services. The processing worker
then called the pinned Docling Serve v1.30.0 image and committed representations through
File Service.

- Runtime Inbox replay of the same DOCX event returned `created=false`; no duplicate
  channel fact was created.
- The valid seven-format recovery batch produced seven `SUCCEEDED` processing runs and
  fourteen atomic representations: one Markdown plus one Docling JSON per input.
- A malformed DOCX was rejected with `document_source_malformed`.
- A source above the 25 MiB boundary and a publication using profile `NONE` were rejected
  before Docling submission.
- With Docling stopped, seven already-durable runs reached `RETRY_WAIT` and then the stable
  `docling_service_unavailable` terminal path. Retry audit facts recorded 30-second and
  60-second backoff decisions, and the seven safe envelopes reached the DLQ.
- With a one-shot processing worker configured for a one-second provider timeout, the same
  persisted run recorded `docling_processing_timeout` backoffs of one and two seconds,
  reused its durable task identity, and succeeded on attempt three.
- After Docling and the normal processing worker restarted, a new seven-format batch
  succeeded. The earlier failed runs remained immutable failure evidence.
- Expiry plus real File Service maintenance cleaned the only active workspace, made 15
  source versions and 16 representations unreadable, completed 31 cleanup facts, and
  reported zero unknown orphan or missing referenced objects.

The final isolated snapshot contains nine successful and seven failed processing runs,
two currently available and sixteen cleaned representations. The processing main/retry
queues are empty; the seven deliberately exhausted safe summaries remain in the DLQ.

## Rollout and legacy-path reconciliation

The default `NONE` publication produced no processing run. Only the isolated test
publication enabled `docling-text-v1`. During and after the run:

- `attachment_content` remained exactly zero;
- the legacy table was not dropped or altered by this change;
- idle observation showed Docling at `1.813 GiB / 8 GiB` and the processing worker at
  `39.59 MiB / 512 MiB`;
- the processing queue had one consumer and zero ready/unacknowledged messages;
- errors were limited to the deliberately injected malformed, unavailable and timeout
  paths described above.

The separate CPU benchmark remains the capacity gate for this host. This acceptance does
not authorize expanding beyond one test publication or raising worker concurrency.

## Runtime-to-Delivery gate

The old seed Agent was also exercised and failed closed before Runtime invocation with
`runtime_model_binding_missing`, proving that a historical publication without a frozen
model connection cannot silently execute. A current-protocol synthetic Agent publication
was not created because the fresh isolated database has no ready model credential. The
acceptance harness checks only safe readiness metadata and does not read, copy or persist a
real API key.

Therefore task 10.3 remains open: success through the actual model Runtime and governed
Delivery adapter still requires a ready model connection in the isolated environment. A
container health check or a mocked model response is not substituted for that evidence.
