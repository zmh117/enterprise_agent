Use this skill when service logs, trace ids, or exception messages are relevant.

Workflow:
1. Extract service name, time range, trace id, and keywords.
2. Query Loki with bounded selectors and result limits.
3. If logs show SQL or cache symptoms, use database or Redis tools.
4. Report the observed evidence and the limits of the search.

