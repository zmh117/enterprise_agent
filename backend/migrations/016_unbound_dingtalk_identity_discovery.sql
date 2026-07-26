create table if not exists dingtalk_identity_candidate (
    id text primary key,
    tenant_code text not null,
    external_subject_id text not null,
    display_name text not null default '',
    first_seen_at text not null,
    last_seen_at text not null,
    observation_count integer not null default 0
        check (observation_count >= 0),
    revision integer not null default 1
        check (revision >= 1),
    created_at text not null,
    updated_at text not null,
    unique (tenant_code, external_subject_id)
);

create index if not exists idx_dingtalk_identity_candidate_last_seen
    on dingtalk_identity_candidate(last_seen_at desc, id desc);

create index if not exists idx_dingtalk_identity_candidate_display_name
    on dingtalk_identity_candidate(display_name);

create table if not exists dingtalk_identity_candidate_message (
    id text primary key,
    candidate_id text not null
        references dingtalk_identity_candidate(id) on delete cascade,
    source_ingress_event_id text not null unique
        references channel_ingress_event(id),
    connector_id text not null
        references integration_connector(id),
    robot_code text not null default '',
    conversation_type text not null
        check (conversation_type in ('direct', 'group')),
    conversation_id text not null default '',
    message_kind text not null default 'unsupported',
    safe_text text not null default '',
    text_truncated integer not null default 0
        check (text_truncated in (0, 1)),
    attachment_type text not null default '',
    attachment_name text not null default '',
    attachment_size integer,
    occurred_at text not null,
    received_at text not null,
    created_at text not null
);

create index if not exists idx_dingtalk_candidate_message_recent
    on dingtalk_identity_candidate_message(
        candidate_id, received_at desc, id desc
    );

create index if not exists idx_dingtalk_candidate_message_conversation
    on dingtalk_identity_candidate_message(
        conversation_type, conversation_id
    );

create index if not exists idx_dingtalk_candidate_message_robot
    on dingtalk_identity_candidate_message(robot_code);
