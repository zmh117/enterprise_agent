# Live Runtime-to-Delivery E2E acceptance — 2026-08-21

## Scope

The user explicitly accepted task 10.3 after exercising the real channel, document
processing, Agent Runtime, and governed Delivery path. The evidence below was refreshed
from the live deployment using read-only queries over operational identities and states.
No message body, attachment name, extracted content, model input/output, object key, or
credential was read or persisted.

## Successful document path

- DingTalk ingress event `channel_event_b57cefc3899a4f9993d13c28fd59f39d` reached
  `JOB_CREATED` through the `dingding_stream` source.
- Job `job_86375ae021274d92bad1e0b2a8083bfd` completed `SUCCEEDED` on
  `python-v1` protocol `1.3`.
- Processing run `file_processing_run_2b48f009f2d34b7aa39323fa3424ef46` completed
  `SUCCEEDED` and published one `MARKDOWN` and one `DOCLING_JSON` Representation, both
  `AVAILABLE`.
- The Job froze manifest schema `4` with both source and Markdown Representation entries.
- The projected execution summary reports `SUCCEEDED`, one Runtime invocation, and four
  observed model turns.
- Governed `RESULT` delivery completed `SUCCEEDED` through the
  `dingtalk_stream_session_webhook` adapter.

## Deterministic failure path

- DingTalk ingress event `channel_event_34bd74fdb6d942aca6ad44aafef7cde8` reached
  `JOB_CREATED`.
- Processing run `file_processing_run_54bc3566999149e1b444720c0c0ccfff` failed closed
  with the stable code `docling_conversion_failed`; attachment readability became
  `UNAVAILABLE` and no model invocation was released for unavailable content.
- Job `job_d2e74c5946864ebaba0fb2d3a176908d` reached its governed failure terminal while
  the safe `RESULT` notification was delivered `SUCCEEDED` through the same DingTalk
  session-webhook adapter.

## Gate conclusion

The live evidence covers successful Inbox/Outbox/RabbitMQ processing, Docling
Representations, manifest v4, Agent Runtime, and Delivery, plus a processing failure that
fails closed and still delivers a governed safe result. Together with the fresh isolated
seven-format and restart/retry evidence, task 10.3 is accepted. Container health alone was
not used as the acceptance signal.
