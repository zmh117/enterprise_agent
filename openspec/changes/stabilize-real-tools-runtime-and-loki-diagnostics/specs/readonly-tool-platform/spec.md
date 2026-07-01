## ADDED Requirements

### Requirement: Loki diagnostics must remain read-only and bounded
Internal API Platform SHALL provide Loki diagnostic operations only as read-only, bounded requests and MUST apply the same tenant, selector label, time range, response size, redaction, and access-control policies used by `query_loki`.

#### Scenario: Bounded label diagnostics
- **WHEN** Agent or developer tooling requests Loki labels or label values through Internal API Platform
- **THEN** the platform returns only bounded diagnostic summaries and records the access decision

#### Scenario: Disallowed diagnostic selector
- **WHEN** a Loki diagnostic request includes a disallowed selector label or exceeds configured limits
- **THEN** the platform rejects the request with a safe non-secret error summary

### Requirement: Tool platform shall expose actionable empty-result metadata
Internal API Platform SHALL distinguish an empty Loki result from platform failure and provide safe metadata that helps determine whether the likely cause is tenant, label, selector, keyword, or time-window mismatch.

#### Scenario: Empty Loki result
- **WHEN** a Loki query succeeds but returns no streams or no log lines
- **THEN** the platform returns `line_count=0`, `stream_count`, selector metadata, time-window metadata, and safe hints instead of treating the request as an upstream failure

#### Scenario: Loki upstream unavailable
- **WHEN** Loki is unreachable or returns retryable upstream errors
- **THEN** the platform classifies the result as retryable upstream failure and does not return misleading empty-result hints
