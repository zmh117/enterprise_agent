alter table integration_connector
    add column deleted integer not null default 0;

create table if not exists channel_connector_runtime (
    connector_id text primary key references integration_connector(id),
    runtime_id text not null default '',
    runtime_status text not null default 'STOPPED'
        check (runtime_status in (
            'STOPPED', 'STARTING', 'CONNECTED', 'REGISTERED',
            'RECONNECTING', 'AUTH_FAILED', 'ERROR'
        )),
    loaded_revision integer,
    connected integer not null default 0,
    registered integer not null default 0,
    connected_at text,
    disconnected_at text,
    last_message_at text,
    last_heartbeat_at text,
    last_error_code text not null default '',
    last_error_summary text not null default '',
    updated_at text not null
);

create index if not exists idx_channel_connector_runtime_heartbeat
    on channel_connector_runtime(last_heartbeat_at);

create table if not exists channel_runtime_lease (
    lease_name text primary key,
    runtime_id text not null,
    lease_token text not null,
    expires_at text not null,
    updated_at text not null
);

create index if not exists idx_channel_runtime_lease_expiry
    on channel_runtime_lease(expires_at);

create table if not exists channel_ingress_event (
    id text primary key,
    source_type text not null,
    connector_id text not null references integration_connector(id),
    external_event_id text not null,
    correlation_id text not null,
    payload_hash text not null,
    safe_summary_json text not null default '{}',
    normalized_event_json text not null default '{}',
    reply_credential_ciphertext text not null default '',
    status text not null default 'ACCEPTED'
        check (status in (
            'ACCEPTED', 'DISPATCH_PENDING', 'DISPATCHING',
            'JOB_CREATED', 'REJECTED', 'DISPATCH_FAILED'
        )),
    job_id text references agent_job(id),
    error_code text not null default '',
    error_summary text not null default '',
    request_bytes integer not null default 0,
    received_at text not null,
    dispatched_at text,
    completed_at text,
    unique (connector_id, external_event_id)
);

create index if not exists idx_channel_ingress_event_status_received
    on channel_ingress_event(status, received_at);

create table if not exists channel_ingress_outbox (
    id text primary key,
    channel_event_id text not null unique references channel_ingress_event(id),
    correlation_id text not null,
    status text not null default 'pending'
        check (status in ('pending', 'publishing', 'published', 'dead')),
    attempt_count integer not null default 0,
    next_attempt_at text not null,
    claimed_by text not null default '',
    claimed_at text,
    last_error_summary text not null default '',
    created_at text not null,
    published_at text,
    updated_at text not null
);

create index if not exists idx_channel_ingress_outbox_claim
    on channel_ingress_outbox(status, next_attempt_at, created_at);
