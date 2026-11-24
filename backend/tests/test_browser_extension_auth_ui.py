import base64
import hashlib
import re
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient

from app.modules.channel.browser.auth import CLIENT_ID, PREFIX
from backend.tests.test_browser_extension_stream import ORIGIN, prepare


def test_interactive_authorization_retries_login_and_can_cancel():
    api, _, password = prepare()
    c = api.state.container
    path = PREFIX + "/auth/authorize"
    query = {
        "client_id": CLIENT_ID,
        "redirect_uri": f"https://{CLIENT_ID}.chromiumapp.org/",
        "code_challenge_method": "S256",
        "code_challenge": "c" * 43,
        "state": "synthetic-ui-state",
    }
    try:
        with TestClient(api, base_url=ORIGIN, follow_redirects=False) as client:
            headers = {"origin": ORIGIN, "accept": "text/html"}
            login = client.get(path, params=query)
            style = re.search(r"<style>(.*?)</style>", login.text, re.S).group(1)
            digest = base64.b64encode(hashlib.sha256(style.encode()).digest()).decode()
            assert f"style-src 'sha256-{digest}'" in login.headers["Content-Security-Policy"]
            name = c.identity_repository.get_user("user_local_admin")["username"]
            bad = client.post(
                path,
                params=query,
                headers=headers,
                data={"action": "login", "username": name, "password": "synthetic-wrong-password"},
            )
            assert bad.status_code == 401 and 'role="alert"' in bad.text
            assert "synthetic-wrong-password" not in bad.text
            signed_in = client.post(
                path,
                params=query,
                headers=headers,
                data={"action": "login", "username": name, "password": password},
            )
            assert signed_in.status_code == 303
            consent = client.get(path, params=query)
            csrf = re.search('name="csrf" value="([^"]+)"', consent.text).group(1)
            cancel = client.post(
                path,
                params=query,
                headers=headers,
                data={"action": "deny", "csrf": csrf},
            )
            assert cancel.status_code == 303
            assert parse_qs(urlsplit(cancel.headers["location"]).query) == {
                "state": [query["state"]],
                "error": ["access_denied"],
            }
            silent = client.get(path, params={**query, "prompt": "none"})
            assert parse_qs(urlsplit(silent.headers["location"]).query)["error"] == [
                "consent_required"
            ]
    finally:
        c.database.close()
