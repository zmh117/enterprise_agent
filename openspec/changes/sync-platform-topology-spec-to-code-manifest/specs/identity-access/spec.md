## MODIFIED Requirements

### Requirement: Tool calls are recorded with safe summaries
The system SHALL persist tool call records with sanitized request payload summaries, bounded normalized response summaries, status, duration, risk level, audit linkage, and exact MCP Tool or external Capability outcome details when available. For governed external APIs, the system MUST record Release and attempt metadata but MUST NOT persist authentication material, raw HTTP request/response bodies or unbounded external content.

#### Scenario: Database tool succeeds
- **WHEN** `query_database` returns evidence through `tool-mcp`
- **THEN** the system records the tool identifier/schema hash, sanitized request summary, bounded response summary, duration, status, risk level, related audit event and actual Resource Revision metadata

#### Scenario: Tool call returns sensitive or large data
- **WHEN** a tool response contains sensitive fields or exceeds inline storage limits
- **THEN** the system stores a masked or summarized response in PostgreSQL and avoids persisting raw sensitive payloads in the tool call row

#### Scenario: Tool MCP rejects a call
- **WHEN** `tool-mcp` rejects a tool call because of Job provenance, authorization, resource resolution, data-source policy, query policy or malformed parameters
- **THEN** the system records a failed tool call with a safe rejection reason, duration, risk level and audit event without exposing resource secrets

#### Scenario: Governed external API call succeeds after retry
- **WHEN** a QUERY Capability succeeds after one or more HTTP attempts
- **THEN** the system records one linked Tool Call and separate safe attempt metadata containing identifiers, classification, duration, size and status, without raw body, Token, Cookie or authentication Header

#### Scenario: Governed external output is INTERNAL
- **WHEN** a Capability returns bounded normalized INTERNAL data
- **THEN** the Tool Call summary preserves user, Application Publication, Capability Release and classification provenance and remains subject to the existing Job access boundary
