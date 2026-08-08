\set ON_ERROR_STOP on

begin;
set local lock_timeout = '10s';
set local statement_timeout = '60s';

lock table
  platform_secret,
  platform_secret_version,
  platform_secret_change_event,
  platform_runtime_config_value,
  model_connection,
  model_connection_revision
in access exclusive mode;

lock table
  integration_connector,
  platform_secret_reference,
  platform_resource_binding,
  webhook_trigger_revision,
  webhook_trigger_publication,
  app_user,
  user_external_identity,
  rbac_role,
  rbac_user_role
in share mode;

create temporary table platform_secret_reset_inventory
on commit drop
as
with secret_inventory as materialized (
  select coalesce(
    jsonb_agg(
      jsonb_build_object(
        'id', s.id,
        'code', s.code,
        'ref', s.ref,
        'status', s.status,
        'active_version', s.active_version,
        'revision', s.revision,
        'versions', coalesce((
          select jsonb_agg(
            jsonb_build_object(
              'id', v.id,
              'version', v.version,
              'key_id', v.key_id,
              'algorithm', v.algorithm,
              'status', v.status
            )
            order by v.version, v.id
          )
          from platform_secret_version v
          where v.secret_id = s.id
        ), '[]'::jsonb),
        'change_events', coalesce((
          select jsonb_agg(
            jsonb_build_object(
              'id', e.id,
              'secret_revision', e.secret_revision,
              'action', e.action,
              'status', e.status
            )
            order by e.secret_revision, e.id
          )
          from platform_secret_change_event e
          where e.secret_id = s.id
        ), '[]'::jsonb)
      )
      order by s.code, s.id
    ),
    '[]'::jsonb
  ) as items
  from platform_secret s
),
runtime_inventory as materialized (
  select coalesce(
    jsonb_agg(
      jsonb_build_object(
        'id', v.id,
        'key', v.key,
        'scope_type', v.scope_type,
        'scope_code', v.scope_code,
        'service_name', v.service_name,
        'secret_ref', v.secret_ref,
        'status', v.status,
        'revision', v.revision
      )
      order by v.key, v.scope_type, v.scope_code, v.service_name, v.id
    ),
    '[]'::jsonb
  ) as items
  from platform_runtime_config_value v
  where v.secret_ref in (select ref from platform_secret)
     or v.key in ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN')
),
model_inventory as materialized (
  select coalesce(
    jsonb_agg(
      jsonb_build_object(
        'id', c.id,
        'code', c.code,
        'status', c.status,
        'revision', c.revision,
        'current_revision_id', coalesce(c.current_revision_id, ''),
        'revisions', coalesce((
          select jsonb_agg(
            jsonb_build_object(
              'id', r.id,
              'revision', r.revision,
              'status', r.status,
              'api_key_secret_id', coalesce(r.api_key_secret_id, ''),
              'config_hash', r.config_hash
            )
            order by r.revision, r.id
          )
          from model_connection_revision r
          where r.connection_id = c.id
        ), '[]'::jsonb)
      )
      order by c.code, c.id
    ),
    '[]'::jsonb
  ) as items
  from model_connection c
  where exists (
    select 1
    from model_connection_revision r
    where r.connection_id = c.id
      and r.api_key_secret_id in (select id from platform_secret)
  )
),
dependency_inventory as materialized (
  select jsonb_build_object(
    'integration_connector', (
      select count(*)
      from integration_connector c
      where c.secret_ref in (select ref from platform_secret)
         or c.endpoint_ref in (select ref from platform_secret)
         or exists (
           select 1 from platform_secret s
           where c.metadata::text like '%' || s.ref || '%'
         )
    ),
    'platform_secret_reference', (
      select count(*)
      from platform_secret_reference r
      where r.ref in (select ref from platform_secret)
    ),
    'platform_resource_binding', (
      select count(*)
      from platform_resource_binding b
      where exists (
        select 1 from platform_secret s
        where b.secret_refs_json::text like '%' || s.ref || '%'
      )
    ),
    'webhook_trigger_revision', (
      select count(*)
      from webhook_trigger_revision r
      where exists (
        select 1 from platform_secret s
        where r.config_json::text like '%' || s.ref || '%'
      )
    ),
    'webhook_trigger_publication', (
      select count(*)
      from webhook_trigger_publication p
      where exists (
        select 1 from platform_secret s
        where p.snapshot_json::text like '%' || s.ref || '%'
      )
    )
  ) as counts
),
inventory as (
  select jsonb_build_object(
    'platform_secrets', s.items,
    'runtime_config_values', r.items,
    'model_connections', m.items,
    'other_dependency_counts', d.counts
  ) as document
  from secret_inventory s
  cross join runtime_inventory r
  cross join model_inventory m
  cross join dependency_inventory d
)
select
  document,
  encode(sha256(convert_to(document::text, 'UTF8')), 'hex') as digest
from inventory;

create temporary table platform_secret_reset_preserve_baseline
on commit drop
as
select jsonb_build_object(
  'app_user', jsonb_build_object(
    'count', (select count(*) from app_user),
    'digest', (
      select encode(sha256(convert_to(coalesce(
        jsonb_agg(jsonb_build_object(
          'id', id,
          'status', status,
          'revision', revision,
          'account_type', account_type
        ) order by id)::text,
        '[]'
      ), 'UTF8')), 'hex')
      from app_user
    )
  ),
  'user_external_identity', jsonb_build_object(
    'count', (select count(*) from user_external_identity),
    'digest', (
      select encode(sha256(convert_to(coalesce(
        jsonb_agg(jsonb_build_object(
          'id', id,
          'user_id', user_id,
          'provider', provider,
          'tenant_code', tenant_code,
          'connector_id', connector_id,
          'status', status,
          'revision', revision
        ) order by id)::text,
        '[]'
      ), 'UTF8')), 'hex')
      from user_external_identity
    )
  ),
  'rbac_role', jsonb_build_object(
    'count', (select count(*) from rbac_role),
    'digest', (
      select encode(sha256(convert_to(coalesce(
        jsonb_agg(jsonb_build_object(
          'id', id,
          'code', code,
          'status', status,
          'revision', revision,
          'admin_revision', admin_revision,
          'business_revision', business_revision,
          'membership_revision', membership_revision
        ) order by id)::text,
        '[]'
      ), 'UTF8')), 'hex')
      from rbac_role
    )
  ),
  'rbac_user_role', jsonb_build_object(
    'count', (select count(*) from rbac_user_role),
    'digest', (
      select encode(sha256(convert_to(coalesce(
        jsonb_agg(jsonb_build_object(
          'id', id,
          'user_id', user_id,
          'role_id', role_id,
          'status', status,
          'revision', revision
        ) order by id)::text,
        '[]'
      ), 'UTF8')), 'hex')
      from rbac_user_role
    )
  ),
  'dingtalk_connectors', jsonb_build_object(
    'count', (
      select count(*)
      from integration_connector
      where connector_type like 'dingtalk%'
    ),
    'digest', (
      select encode(sha256(convert_to(coalesce(
        jsonb_agg(jsonb_build_object(
          'id', id,
          'connector_type', connector_type,
          'enabled', enabled,
          'allow_ingress', allow_ingress,
          'allow_delivery', allow_delivery,
          'revision', revision,
          'deleted', deleted,
          'secret_ref', secret_ref,
          'endpoint_ref', endpoint_ref
        ) order by id)::text,
        '[]'
      ), 'UTF8')), 'hex')
      from integration_connector
      where connector_type like 'dingtalk%'
    )
  )
) as document;

do $preflight$
declare
  actual_inventory jsonb;
  actual_digest text;
  actual_baseline jsonb;
  prepared_count integer;
  version_count integer;
  model_revision_count integer;
begin
  select document, digest
  into actual_inventory, actual_digest
  from platform_secret_reset_inventory;

  if actual_digest !=
    'ae6699fab921d0b671896f5b97c25671ac9ab6d633c157a71cb179abeb9a46d6'
  then
    raise exception
      'platform_secret_reset inventory digest changed: %',
      actual_digest;
  end if;

  select count(*)
  into prepared_count
  from audit_event
  where id =
      'audit_platform_secret_reset_0e086a4aeebe40698c5555ba8fec85e1'
    and event_type = 'platform_secret_reset_prepared'
    and status = 'PREPARED'
    and payload_summary::jsonb->>'operation_id' =
      'platform_secret_reset_0e086a4a-eebe-4069-8c55-55ba8fec85e1'
    and payload_summary::jsonb->>'inventory_digest' =
      'ae6699fab921d0b671896f5b97c25671ac9ab6d633c157a71cb179abeb9a46d6';

  if prepared_count != 1 then
    raise exception 'platform_secret_reset PREPARED audit is missing';
  end if;

  if jsonb_array_length(actual_inventory->'platform_secrets') != 3
     or jsonb_array_length(
       actual_inventory->'runtime_config_values'
     ) != 1
     or jsonb_array_length(actual_inventory->'model_connections') != 1
  then
    raise exception 'platform_secret_reset target counts changed';
  end if;

  select coalesce(sum(jsonb_array_length(item->'versions')), 0)
  into version_count
  from jsonb_array_elements(
    actual_inventory->'platform_secrets'
  ) item;

  select coalesce(sum(jsonb_array_length(item->'revisions')), 0)
  into model_revision_count
  from jsonb_array_elements(
    actual_inventory->'model_connections'
  ) item;

  if version_count != 14 or model_revision_count != 4 then
    raise exception 'platform_secret_reset child counts changed';
  end if;

  if exists (
    select 1
    from jsonb_each_text(
      actual_inventory->'other_dependency_counts'
    )
    where value::integer != 0
  ) then
    raise exception 'platform_secret_reset found an unapproved dependency';
  end if;

  select document
  into actual_baseline
  from platform_secret_reset_preserve_baseline;

  if actual_baseline != jsonb_build_object(
    'app_user', jsonb_build_object(
      'count', 7,
      'digest',
      '17b7419ea09c8f78f2eac9d68376778940e12a8f73c3176e7292627c42849ccb'
    ),
    'user_external_identity', jsonb_build_object(
      'count', 7,
      'digest',
      '8e018fd08f16deb3d746c6e099991a387579d48a6354fff8c722fa0caba43396'
    ),
    'rbac_role', jsonb_build_object(
      'count', 3,
      'digest',
      '51b412b9dbc6562df243133d491025044e70a09443df925bf5da9ffc68b0ea58'
    ),
    'rbac_user_role', jsonb_build_object(
      'count', 7,
      'digest',
      '91928e11f2aa582a473f9d9d79cff7e39d087993d8c453042c31d8286786ac18'
    ),
    'dingtalk_connectors', jsonb_build_object(
      'count', 3,
      'digest',
      '4c88ff2cb5fd5efca65631ac6c25e24540e790887e924806d3d6a89915560997'
    )
  ) then
    raise exception 'platform_secret_reset preserve baseline changed';
  end if;
end
$preflight$;

do $apply$
declare
  affected integer;
begin
  update model_connection c
  set
    current_revision_id = null,
    status = 'rotation_required',
    revision = 0,
    updated_at = to_char(
      clock_timestamp() at time zone 'UTC',
      'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
    )
  where c.id in (
    select model_item.value->>'id'
    from platform_secret_reset_inventory i,
    lateral jsonb_array_elements(
      i.document->'model_connections'
    ) as model_item(value)
  );
  get diagnostics affected = row_count;
  if affected != 1 then
    raise exception
      'platform_secret_reset expected 1 model connection, got %',
      affected;
  end if;

  delete from model_connection_revision r
  where r.id in (
    select revision_item.value->>'id'
    from platform_secret_reset_inventory i,
    lateral jsonb_array_elements(
      i.document->'model_connections'
    ) as connection_item(value),
    lateral jsonb_array_elements(
      connection_item.value->'revisions'
    ) as revision_item(value)
  );
  get diagnostics affected = row_count;
  if affected != 4 then
    raise exception
      'platform_secret_reset expected 4 model revisions, got %',
      affected;
  end if;

  delete from platform_runtime_config_value v
  where v.id in (
    select runtime_item.value->>'id'
    from platform_secret_reset_inventory i,
    lateral jsonb_array_elements(
      i.document->'runtime_config_values'
    ) as runtime_item(value)
  );
  get diagnostics affected = row_count;
  if affected != 1 then
    raise exception
      'platform_secret_reset expected 1 runtime config value, got %',
      affected;
  end if;

  delete from platform_secret_change_event e
  where e.secret_id in (
    select secret_item.value->>'id'
    from platform_secret_reset_inventory i,
    lateral jsonb_array_elements(
      i.document->'platform_secrets'
    ) as secret_item(value)
  );
  get diagnostics affected = row_count;
  if affected != 0 then
    raise exception
      'platform_secret_reset expected 0 change events, got %',
      affected;
  end if;

  delete from platform_secret_version v
  where v.secret_id in (
    select secret_item.value->>'id'
    from platform_secret_reset_inventory i,
    lateral jsonb_array_elements(
      i.document->'platform_secrets'
    ) as secret_item(value)
  );
  get diagnostics affected = row_count;
  if affected != 14 then
    raise exception
      'platform_secret_reset expected 14 secret versions, got %',
      affected;
  end if;

  delete from platform_secret s
  where s.id in (
    select secret_item.value->>'id'
    from platform_secret_reset_inventory i,
    lateral jsonb_array_elements(
      i.document->'platform_secrets'
    ) as secret_item(value)
  );
  get diagnostics affected = row_count;
  if affected != 3 then
    raise exception
      'platform_secret_reset expected 3 secrets, got %',
      affected;
  end if;
end
$apply$;

do $verify$
declare
  current_baseline jsonb;
begin
  if exists (select 1 from platform_secret)
     or exists (
       select 1
       from platform_runtime_config_value
       where key in ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN')
     )
     or exists (
       select 1
       from model_connection_revision r
       join model_connection c on c.id = r.connection_id
       where c.code = 'default-deepseek-anthropic'
     )
  then
    raise exception 'platform_secret_reset target verify failed';
  end if;

  if not exists (
    select 1
    from model_connection
    where code = 'default-deepseek-anthropic'
      and current_revision_id is null
      and status = 'rotation_required'
      and revision = 0
  ) then
    raise exception 'platform_secret_reset model identity verify failed';
  end if;

  select jsonb_build_object(
    'app_user', jsonb_build_object(
      'count', (select count(*) from app_user),
      'digest', (
        select encode(sha256(convert_to(coalesce(
          jsonb_agg(jsonb_build_object(
            'id', id,
            'status', status,
            'revision', revision,
            'account_type', account_type
          ) order by id)::text,
          '[]'
        ), 'UTF8')), 'hex')
        from app_user
      )
    ),
    'user_external_identity', jsonb_build_object(
      'count', (select count(*) from user_external_identity),
      'digest', (
        select encode(sha256(convert_to(coalesce(
          jsonb_agg(jsonb_build_object(
            'id', id,
            'user_id', user_id,
            'provider', provider,
            'tenant_code', tenant_code,
            'connector_id', connector_id,
            'status', status,
            'revision', revision
          ) order by id)::text,
          '[]'
        ), 'UTF8')), 'hex')
        from user_external_identity
      )
    ),
    'rbac_role', jsonb_build_object(
      'count', (select count(*) from rbac_role),
      'digest', (
        select encode(sha256(convert_to(coalesce(
          jsonb_agg(jsonb_build_object(
            'id', id,
            'code', code,
            'status', status,
            'revision', revision,
            'admin_revision', admin_revision,
            'business_revision', business_revision,
            'membership_revision', membership_revision
          ) order by id)::text,
          '[]'
        ), 'UTF8')), 'hex')
        from rbac_role
      )
    ),
    'rbac_user_role', jsonb_build_object(
      'count', (select count(*) from rbac_user_role),
      'digest', (
        select encode(sha256(convert_to(coalesce(
          jsonb_agg(jsonb_build_object(
            'id', id,
            'user_id', user_id,
            'role_id', role_id,
            'status', status,
            'revision', revision
          ) order by id)::text,
          '[]'
        ), 'UTF8')), 'hex')
        from rbac_user_role
      )
    ),
    'dingtalk_connectors', jsonb_build_object(
      'count', (
        select count(*)
        from integration_connector
        where connector_type like 'dingtalk%'
      ),
      'digest', (
        select encode(sha256(convert_to(coalesce(
          jsonb_agg(jsonb_build_object(
            'id', id,
            'connector_type', connector_type,
            'enabled', enabled,
            'allow_ingress', allow_ingress,
            'allow_delivery', allow_delivery,
            'revision', revision,
            'deleted', deleted,
            'secret_ref', secret_ref,
            'endpoint_ref', endpoint_ref
          ) order by id)::text,
          '[]'
        ), 'UTF8')), 'hex')
        from integration_connector
        where connector_type like 'dingtalk%'
      )
    )
  ) into current_baseline;

  if current_baseline != (
    select document
    from platform_secret_reset_preserve_baseline
  ) then
    raise exception 'platform_secret_reset preserve verify failed';
  end if;
end
$verify$;

insert into audit_event (
  id,
  job_id,
  event_type,
  actor_id,
  status,
  summary,
  payload_summary,
  created_at
)
values (
  'audit_platform_secret_reset_applied_0e086a4aeebe40698c5555ba8fec85e1',
  null,
  'platform_secret_reset_applied',
  'codex-local-maintenance',
  'SUCCEEDED',
  'Platform Secret reset applied and transactionally verified',
  jsonb_build_object(
    'operation_id',
    'platform_secret_reset_0e086a4a-eebe-4069-8c55-55ba8fec85e1',
    'inventory_digest',
    'ae6699fab921d0b671896f5b97c25671ac9ab6d633c157a71cb179abeb9a46d6',
    'deleted_platform_secrets',
    3,
    'deleted_platform_secret_versions',
    14,
    'deleted_runtime_config_values',
    1,
    'deleted_model_connection_revisions',
    4,
    'preserved_model_connection_identities',
    1
  )::text,
  to_char(
    clock_timestamp() at time zone 'UTC',
    'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
  )
);

commit;

select
  'APPLIED' as status,
  'platform_secret_reset_0e086a4a-eebe-4069-8c55-55ba8fec85e1'
    as operation_id,
  'ae6699fab921d0b671896f5b97c25671ac9ab6d633c157a71cb179abeb9a46d6'
    as inventory_digest,
  (select count(*) from platform_secret) as remaining_platform_secrets,
  (
    select count(*)
    from platform_runtime_config_value
    where key in ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN')
  ) as remaining_anthropic_runtime_values,
  (
    select count(*)
    from model_connection_revision r
    join model_connection c on c.id = r.connection_id
    where c.code = 'default-deepseek-anthropic'
  ) as remaining_model_revisions;
