\pset pager off

-- Runtime foundation inventory.
-- This file intentionally excludes password_hash, token_hash, csrf_hash,
-- ciphertext, nonce, config_json, snapshot_json and metadata_json.

\echo 'identity_and_membership'
WITH credential AS (
    SELECT user_id, 1 AS has_password
    FROM user_password_credential
),
sessions AS (
    SELECT
        user_id,
        count(*) FILTER (WHERE status = 'active') AS active_sessions,
        max(last_seen_at) AS last_seen_at
    FROM user_session
    GROUP BY user_id
)
SELECT
    u.id,
    u.username,
    u.display_name,
    u.account_type,
    u.status,
    COALESCE(c.has_password, 0) AS has_password,
    COALESCE(s.active_sessions, 0) AS active_sessions,
    s.last_seen_at,
    string_agg(
        r.code || '[' || ur.status || ']',
        ', ' ORDER BY r.code
    ) AS roles
FROM app_user AS u
LEFT JOIN credential AS c ON c.user_id = u.id
LEFT JOIN sessions AS s ON s.user_id = u.id
LEFT JOIN rbac_user_role AS ur ON ur.user_id = u.id
LEFT JOIN rbac_role AS r ON r.id = ur.role_id
GROUP BY
    u.id,
    u.username,
    u.display_name,
    u.account_type,
    u.status,
    c.has_password,
    s.active_sessions,
    s.last_seen_at
ORDER BY u.username;

\echo 'rbac_roles'
SELECT
    r.id,
    r.code,
    r.name,
    r.status,
    r.origin,
    r.protected,
    r.revision,
    count(DISTINCT ur.id) FILTER (
        WHERE ur.status = 'enabled'
    ) AS enabled_members,
    count(DISTINCT ac.id) FILTER (
        WHERE ac.status = 'enabled'
    ) AS enabled_admin_capabilities,
    count(DISTINCT aa.id) FILTER (
        WHERE aa.status = 'enabled'
    ) AS enabled_app_access
FROM rbac_role AS r
LEFT JOIN rbac_user_role AS ur ON ur.role_id = r.id
LEFT JOIN rbac_role_admin_capability AS ac ON ac.role_id = r.id
LEFT JOIN rbac_role_application_access AS aa ON aa.role_id = r.id
GROUP BY
    r.id,
    r.code,
    r.name,
    r.status,
    r.origin,
    r.protected,
    r.revision
ORDER BY r.code;

\echo 'human_platform_admins'
SELECT
    r.code AS role_code,
    u.id AS user_id,
    u.username,
    u.account_type,
    u.status AS user_status,
    ur.status AS membership_status,
    ur.assignment_source,
    ur.expires_at,
    EXISTS (
        SELECT 1
        FROM user_password_credential AS c
        WHERE c.user_id = u.id
    ) AS has_password,
    EXISTS (
        SELECT 1
        FROM user_session AS s
        WHERE s.user_id = u.id
          AND s.status = 'active'
    ) AS has_active_session
FROM rbac_role AS r
JOIN rbac_user_role AS ur ON ur.role_id = r.id
JOIN app_user AS u ON u.id = ur.user_id
WHERE r.code = 'platform-admin'
ORDER BY u.username;

\echo 'authorization_counts'
SELECT
    (SELECT count(*) FROM app_user) AS user_total,
    (SELECT count(*) FROM rbac_role) AS role_total,
    (SELECT count(*) FROM rbac_user_role) AS membership_total,
    (SELECT count(*) FROM rbac_role_admin_capability)
        AS admin_capability_total,
    (SELECT count(*) FROM rbac_role_application_access)
        AS application_access_total,
    (SELECT count(*) FROM rbac_role_application_capability)
        AS application_capability_total,
    (SELECT count(*) FROM rbac_role_application_scope)
        AS application_scope_total,
    (SELECT count(*) FROM permission_policy)
        AS permission_policy_total,
    (SELECT count(*) FROM platform_access_grant)
        AS platform_access_grant_total;

SELECT
    'permission_policy' AS source,
    subject_type,
    effect,
    status,
    count(*) AS rows
FROM permission_policy
GROUP BY subject_type, effect, status
UNION ALL
SELECT
    'platform_access_grant' AS source,
    subject_type,
    effect,
    status,
    count(*) AS rows
FROM platform_access_grant
GROUP BY subject_type, effect, status
ORDER BY source, subject_type, effect, status;

\echo 'resource_bindings'
SELECT
    id,
    code,
    scope_type,
    COALESCE(environment_id, '-') AS environment_id,
    COALESCE(base_id, '-') AS base_id,
    COALESCE(workshop_id, '-') AS workshop_id,
    resource_kind,
    COALESCE(engine, '-') AS engine,
    status,
    revision,
    CASE
        WHEN config_json IS NULL OR config_json = '' THEN 0
        ELSE 1
    END AS has_config,
    CASE
        WHEN secret_refs_json IS NULL
          OR secret_refs_json IN ('', '[]', '{}') THEN 0
        ELSE 1
    END AS has_secret_refs
FROM platform_resource_binding
ORDER BY resource_kind, code;

SELECT resource_kind, engine, status, count(*) AS rows
FROM platform_resource_binding
GROUP BY resource_kind, engine, status
ORDER BY resource_kind, engine, status;

\echo 'managed_secret_metadata'
SELECT
    s.id,
    s.code,
    s.provider,
    s.ref,
    s.purpose,
    s.status,
    s.active_version,
    s.revision,
    count(v.id) AS version_count,
    string_agg(
        DISTINCT v.status,
        ', ' ORDER BY v.status
    ) AS version_statuses
FROM platform_secret AS s
LEFT JOIN platform_secret_version AS v ON v.secret_id = s.id
GROUP BY
    s.id,
    s.code,
    s.provider,
    s.ref,
    s.purpose,
    s.status,
    s.active_version,
    s.revision
ORDER BY s.code;

\echo 'resource_secret_reference_metadata'
SELECT id, code, provider, ref, purpose, status, revision
FROM platform_secret_reference
ORDER BY code;

\echo 'business_applications'
WITH rev AS (
    SELECT
        application_id,
        count(*) AS revision_count,
        count(*) FILTER (WHERE status = 'draft') AS draft_count
    FROM business_application_revision
    GROUP BY application_id
),
pub AS (
    SELECT
        application_id,
        count(*) AS publication_count,
        max(revision) AS latest_publication_revision
    FROM business_application_publication
    GROUP BY application_id
),
dep AS (
    SELECT
        application_id,
        count(*) FILTER (WHERE active = 1) AS active_deployments,
        string_agg(
            DISTINCT environment,
            ', ' ORDER BY environment
        ) FILTER (WHERE active = 1) AS environments
    FROM business_application_deployment
    GROUP BY application_id
),
route AS (
    SELECT
        application_id,
        count(*) AS active_routes,
        string_agg(
            DISTINCT trigger_type,
            ', ' ORDER BY trigger_type
        ) AS trigger_types
    FROM business_application_active_route
    GROUP BY application_id
)
SELECT
    a.id,
    a.code,
    a.name,
    a.status,
    a.revision,
    a.owner_user_id,
    COALESCE(rev.revision_count, 0) AS revisions,
    COALESCE(rev.draft_count, 0) AS drafts,
    COALESCE(pub.publication_count, 0) AS publications,
    pub.latest_publication_revision,
    COALESCE(dep.active_deployments, 0) AS active_deployments,
    dep.environments,
    COALESCE(route.active_routes, 0) AS active_routes,
    route.trigger_types
FROM business_application AS a
LEFT JOIN rev ON rev.application_id = a.id
LEFT JOIN pub ON pub.application_id = a.id
LEFT JOIN dep ON dep.application_id = a.id
LEFT JOIN route ON route.application_id = a.id
ORDER BY a.code;

\echo 'application_resource_scope_impact'
SELECT
    a.code AS application_code,
    r.code AS role_code,
    s.environment_id,
    s.base_id,
    s.workshop_id,
    count(prb.id) AS matching_resources,
    string_agg(
        DISTINCT prb.resource_kind,
        ', ' ORDER BY prb.resource_kind
    ) AS resource_kinds
FROM rbac_role_application_scope AS s
JOIN rbac_role_application_access AS aa
  ON aa.id = s.application_access_id
JOIN rbac_role AS r ON r.id = aa.role_id
JOIN business_application AS a ON a.id = aa.application_id
LEFT JOIN platform_resource_binding AS prb
  ON prb.environment_id = s.environment_id
 AND (s.base_id IS NULL OR prb.base_id = s.base_id)
 AND (s.workshop_id IS NULL OR prb.workshop_id = s.workshop_id)
WHERE aa.status = 'enabled'
GROUP BY
    a.code,
    r.code,
    s.environment_id,
    s.base_id,
    s.workshop_id
ORDER BY
    a.code,
    r.code,
    s.environment_id,
    s.base_id,
    s.workshop_id;
