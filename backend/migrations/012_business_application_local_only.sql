-- Business Application runtime is intentionally single-environment.
-- Preserve immutable publications and historical Job provenance while removing
-- non-local deployment pointers and their mutable route projections.

DELETE FROM business_application_active_route
 WHERE environment <> 'local'
    OR deployment_id IN (
      SELECT id
        FROM business_application_deployment
       WHERE environment <> 'local'
    );

DELETE FROM business_application_deployment
 WHERE environment <> 'local';
