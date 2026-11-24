import base64
import hashlib
from html import escape

from fastapi.responses import HTMLResponse


_STYLE = """
:root {
  color-scheme: light;
  font: 14px/1.5 system-ui, "PingFang SC", "Microsoft YaHei", sans-serif;
  color: #222033;
  background: #fff;
  --accent: #513ccd;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 32px 24px;
}
main {
  width: min(100%, 360px);
  margin: 0 auto;
}
h1 { margin: 0 0 22px; font-size: 21px; font-weight: 650; line-height: 1.3; }
form { display: grid; gap: 16px; }
label { display: grid; gap: 5px; font-size: 13px; font-weight: 550; }
input, button { width: 100%; min-width: 0; min-height: 40px; border-radius: 8px; font: inherit; }
input { padding: 8px 11px; font-size: 14px; color: inherit; border: 1px solid #cfcdd9; background: white; }
input:focus { outline: 2px solid #ddd7ff; outline-offset: 1px; border-color: var(--accent); }
button {
  border: 1px solid transparent; padding: 8px 12px; color: white;
  background: var(--accent); font-weight: 600; cursor: pointer;
}
button:hover { background: #4230ae; }
button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.secondary { color: #434050; background: white; border-color: #d5d2de; }
.secondary:hover { background: #f6f5f9; }
.actions { display: grid; grid-template-columns: 1fr 1.6fr; gap: 8px; }
p { margin: 0; color: #595568; overflow-wrap: anywhere; }
.account {
  display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 10px; overflow-wrap: anywhere;
}
.account span { color: #625d74; }
[role=alert] { color: #a82132; font-size: 13px; }
@media (max-width: 380px), (max-height: 360px) {
  body { padding: 20px; }
  form { gap: 12px; }
  h1 { margin-bottom: 16px; font-size: 20px; }
}
"""
_STYLE_HASH = base64.b64encode(hashlib.sha256(_STYLE.encode()).digest()).decode()


def auth_page(
    heading: str,
    fields: str,
    headers: dict[str, str],
    *,
    auto_script: str = "",
    status: int = 200,
) -> HTMLResponse:
    script = f'<script src="{escape(auto_script, quote=True)}"></script>' if auto_script else ""
    return HTMLResponse(
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(heading)} · Enterprise Agent</title><style>{_STYLE}</style></head>"
        '<body><main aria-labelledby="heading">'
        f'<h1 id="heading">{escape(heading)}</h1><form method="post">{fields}</form>'
        f"</main>{script}</body></html>",
        status_code=status,
        headers={
            **headers,
            "Content-Security-Policy": headers["Content-Security-Policy"]
            + f"; style-src 'sha256-{_STYLE_HASH}'",
        },
    )
