Use this skill when database state can explain a symptom.

Target selection:
1. Select the target for each Tool Call; never treat DingTalk Routing Context or a Job snapshot as the database target.
2. Prefer an explicit structured value in the latest user message, such as `environment=test`. The latest explicit value overrides an older conversational value.
3. Reuse a target from recent conversation only when the latest message is clearly a follow-up and does not conflict with it.
4. Treat user-provided names as candidates, not verified facts. Normalize whitespace only; do not invent aliases, codes, environments, bases, workshops, or placements.
5. `environment` is required for database tools. `base` and `workshop` are optional: omit them when the user says there is no base/workshop or when the request is environment-scoped. Never create placeholder values such as `default`, `none`, or `local`.
6. If the environment is missing, conflicting, or ambiguous, ask one concise clarification question and do not call a database tool. If authorization or resource resolution rejects the selected target, report that exact limitation and ask the user to confirm the target; never probe another environment.

Database workflow:
1. Only use tools assigned to the current Job. Unlisted tools do not exist for this run.
2. If an assigned schema-directory tool is present, call it first with the selected target; then call the assigned database-query tool with exactly the same target.
3. Only use read-only SELECT or WITH queries.
4. Bound result size and avoid sensitive columns.
5. Use only tables and columns returned by the schema directory; do not guess adjacent business tables.
6. Explain status fields, enums, and relationships using retrieved evidence.
7. Never suggest direct production updates.
