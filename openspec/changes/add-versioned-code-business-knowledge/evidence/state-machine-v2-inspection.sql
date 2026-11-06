-- 只读核验：指定 MES 来源，列出各候选/已启用快照的实际状态机行。
-- FAILED/CANDIDATE 是审查材料，不能当作已启用问答事实。
SELECT b.id AS build_id, b.stage AS build_stage,
       s.id AS snapshot_id, s.state AS snapshot_state,
       t.object_key, t.machine_key, t.business_key, t.event_key,
       t.source_mode, origins.state_keys AS from_state_keys,
       t.guard_json, t.actions_json, t.target_mode, t.target_state_key,
       t.success_boundary_json
FROM knowledge.code_build b
JOIN knowledge.code_snapshot s ON s.id = b.snapshot_id
JOIN knowledge.code_transition t ON t.snapshot_id = s.id
LEFT JOIN LATERAL (
    SELECT array_agg(x.state_key ORDER BY x.state_key) AS state_keys
    FROM knowledge.code_transition_source x
    WHERE x.snapshot_id = t.snapshot_id AND x.business_key = t.business_key
) origins ON true
WHERE b.source_id = 'ea3fd4a6-3eac-538b-bf73-b57509593147'
ORDER BY b.created_at DESC, t.object_key, t.business_key;

-- 每条迁移的失败条件、失败后状态以及保留动作；与同快照状态值一起读。
SELECT b.id AS build_id, b.stage AS build_stage,
       f.snapshot_id, f.business_key, f.failure_key, f.phase, f.outcome,
       f.state_mode, f.state_key, st.raw_value,
       f.failure_json
FROM knowledge.code_transition_failure f
JOIN knowledge.code_build b ON b.snapshot_id = f.snapshot_id
LEFT JOIN knowledge.code_state st
  ON st.snapshot_id = f.snapshot_id
 AND st.machine_key = f.machine_key AND st.state_key = f.state_key
WHERE b.source_id = 'ea3fd4a6-3eac-538b-bf73-b57509593147'
ORDER BY b.created_at DESC, f.business_key, f.ordinal;

-- 问答默认读取的已启用快照；为空代表候选尚未通过并启用。
SELECT source_id, knowledge_base_id, active_snapshot_id
FROM knowledge.code_binding
WHERE source_id = 'ea3fd4a6-3eac-538b-bf73-b57509593147';
