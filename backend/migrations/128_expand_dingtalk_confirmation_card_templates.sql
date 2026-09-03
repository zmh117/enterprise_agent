-- Configure DingTalk confirmation cards per source Connector and preserve the
-- historical template fact for Connectors and CREATE card outboxes that
-- existed before purpose-bound templates were introduced.

-- sqlite-only
UPDATE integration_connector
   SET metadata = json_set(
         metadata,
         '$.card_templates.external_action_confirmation.template_id',
         '0ad7c643-7e30-4797-8284-da5ef89d3841.schema',
         '$.card_templates.external_action_confirmation.contract_version',
         'external-action-confirmation-v1'
       ),
       revision = revision + 1,
       updated_at = CURRENT_TIMESTAMP
 WHERE connector_type = 'dingtalk_enterprise_stream'
   AND deleted = 0
   AND json_valid(metadata)
   AND json_extract(
         metadata,
         '$.card_templates.external_action_confirmation.template_id'
       ) IS NULL;

-- postgres-only
UPDATE integration_connector
   SET metadata = jsonb_set(
         metadata::jsonb,
         '{card_templates}',
         COALESCE(metadata::jsonb -> 'card_templates', '{}'::jsonb)
         || jsonb_build_object(
              'external_action_confirmation',
              jsonb_build_object(
                'template_id',
                '0ad7c643-7e30-4797-8284-da5ef89d3841.schema',
                'contract_version',
                'external-action-confirmation-v1'
              )
            ),
         true
       )::text,
       revision = revision + 1,
       updated_at = CURRENT_TIMESTAMP
 WHERE connector_type = 'dingtalk_enterprise_stream'
   AND deleted = 0
   AND metadata::jsonb #>> '{card_templates,external_action_confirmation,template_id}'
       IS NULL;

-- sqlite-only
UPDATE external_action_card_outbox
   SET payload_json = json_set(
         payload_json,
         '$.card_binding',
         json_object(
           'purpose', 'external_action_confirmation',
           'template_id', '0ad7c643-7e30-4797-8284-da5ef89d3841.schema',
           'contract_version', 'external-action-confirmation-v1',
           'connector_id', (
             SELECT source_connector_id
               FROM external_action_intent
              WHERE id = external_action_card_outbox.action_intent_id
           ),
           'connector_revision', COALESCE((
             SELECT c.revision
               FROM external_action_intent i
               LEFT JOIN integration_connector c ON c.id = i.source_connector_id
              WHERE i.id = external_action_card_outbox.action_intent_id
           ), 1)
         )
       ),
       updated_at = CURRENT_TIMESTAMP
 WHERE event_kind = 'CREATE'
   AND json_valid(payload_json)
   AND json_extract(payload_json, '$.card_binding') IS NULL;

-- postgres-only
UPDATE external_action_card_outbox AS o
   SET payload_json = jsonb_set(
         o.payload_json::jsonb,
         '{card_binding}',
         jsonb_build_object(
           'purpose', 'external_action_confirmation',
           'template_id', '0ad7c643-7e30-4797-8284-da5ef89d3841.schema',
           'contract_version', 'external-action-confirmation-v1',
           'connector_id', i.source_connector_id,
           'connector_revision', COALESCE(c.revision, 1)
         ),
         true
       )::text,
       updated_at = CURRENT_TIMESTAMP
  FROM external_action_intent AS i
  LEFT JOIN integration_connector AS c ON c.id = i.source_connector_id
 WHERE i.id = o.action_intent_id
   AND o.event_kind = 'CREATE'
   AND o.payload_json::jsonb -> 'card_binding' IS NULL;
