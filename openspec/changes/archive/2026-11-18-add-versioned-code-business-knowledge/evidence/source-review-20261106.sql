-- 本次直接审校：只读。固定快照避免与历史失败模型候选混读。
SELECT t.object_key, t.machine_key, t.business_key, t.event_key,
       t.source_mode, src.origins, t.source_json,
       t.guard_json, t.actions_json, t.target_mode, t.target_state_key,
       target.raw_value AS target_raw_value, t.success_boundary_json
FROM knowledge.code_transition t
LEFT JOIN LATERAL (
    SELECT jsonb_agg(jsonb_build_object('state_key', s.state_key, 'value', s.raw_value)) AS origins
    FROM knowledge.code_transition_source x
    JOIN knowledge.code_state s USING(snapshot_id, machine_key, state_key)
    WHERE x.snapshot_id=t.snapshot_id AND x.business_key=t.business_key
) src ON true
LEFT JOIN knowledge.code_state target
  ON target.snapshot_id=t.snapshot_id AND target.machine_key=t.machine_key
 AND target.state_key=t.target_state_key
WHERE t.snapshot_id='0ad7a672-308b-531e-81cf-d3ec48aa5d9f'
ORDER BY t.machine_key, t.business_key;

SELECT business_key, failure_key, phase, outcome, state_mode, state_key, failure_json
FROM knowledge.code_transition_failure
WHERE snapshot_id='0ad7a672-308b-531e-81cf-d3ec48aa5d9f'
ORDER BY business_key, ordinal;

SELECT relation_json
FROM knowledge.code_relation
WHERE snapshot_id='0ad7a672-308b-531e-81cf-d3ec48aa5d9f'
ORDER BY relation_id;

SELECT r.attributes::jsonb->'knowledge' AS business_rule
FROM knowledge.code_member m
JOIN knowledge.document_revision r ON r.id=m.revision_id AND r.document_id=m.document_id
WHERE m.snapshot_id='0ad7a672-308b-531e-81cf-d3ec48aa5d9f'
  AND r.attributes::jsonb->'knowledge'->>'kind'='rule'
ORDER BY r.attributes::jsonb->'knowledge'->>'business_key';
