# DingTalk Stream fixtures

- `direct_text.json` and `group_text.json` are sanitized from local real Stream audit events on 2026-07-12. Real values, message text, names and identifiers were replaced.
- `picture.json` follows the installed `dingtalk-stream` SDK `picture -> content.downloadCode` contract.
- `file.json` is the normalized contract fixture used by the adapter; a real file Stream event remains part of final runtime acceptance.

No fixture contains a real download code, webhook, token, employee identifier or conversation identifier.
