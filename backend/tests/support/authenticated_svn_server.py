"""Disposable HTTPS SVN fixture. Run only in the isolated code-svn test container."""

from pathlib import Path
import os
import subprocess


def run(*args: str, data: bytes | None = None) -> bytes:
    return subprocess.run(args, input=data, check=True, capture_output=True).stdout


root = Path("/tmp/svn-auth-fixture")
root.mkdir()
run("svnadmin", "create", str(root / "repo"))
source = root / "source"
(source / "trunk/module").mkdir(parents=True)
(source / "trunk/module/rule.cpp").write_text("int release_allowed = 0;\n")
run("svn", "import", str(source), (root / "repo").as_uri(), "-m", "synthetic baseline")
run("svn", "checkout", (root / "repo").as_uri(), str(root / "writer"))
(root / "writer/trunk/module/rule.cpp").write_text("int release_allowed = 1;\n")
run("svn", "commit", str(root / "writer"), "-m", "synthetic rule change")
run(
    "openssl",
    "req",
    "-x509",
    "-newkey",
    "rsa:2048",
    "-nodes",
    "-days",
    "1",
    "-keyout",
    str(root / "server.key"),
    "-out",
    str(root / "server.crt"),
    "-subj",
    "/CN=host.docker.internal",
    "-addext",
    "subjectAltName=DNS:host.docker.internal,DNS:localhost,IP:127.0.0.1",
)
run("htpasswd", "-ci", str(root / "accounts"), "synthetic-user", data=b"synthetic-password\n")
config = Path("/opt/code-svn/apache.conf").read_text()
config = config.replace("/state/tls", str(root)).replace("/repos/mes", "/repos/fixture")
config = config.replace("/state/repos/mes", str(root / "repo"))
# The URL replacement also changes the repository path in the template.
config = config.replace("/state/repos/fixture", str(root / "repo"))
start, end = config.index("        <Limit GET"), config.index("    </Location>")
config = (
    config[:start]
    + f"""        AuthType Basic
        AuthName "Synthetic SVN fixture"
        AuthUserFile {root / "accounts"}
        Require valid-user
"""
    + config[end:]
)
config = config.replace(
    "</VirtualHost>",
    f"""    <Location /public/fixture>
        DAV svn
        SVNPath {root / "repo"}
        Require all granted
    </Location>
</VirtualHost>""",
)
# Expose the same isolated fixture over HTTP and svn:// for protocol acceptance.
http_host = config[config.index("<VirtualHost") :].replace("*:8443", "*:8080")
http_host = "\n".join(line for line in http_host.splitlines() if not line.strip().startswith("SSL"))
config += "\nListen 8080\n" + http_host + "\n"
(root / "repo/conf/svnserve.conf").write_text(
    "[general]\nanon-access = read\nauth-access = read\npassword-db = passwd\nrealm = synthetic-fixture\n"
)
(root / "repo/conf/passwd").write_text("[users]\nsynthetic-user = synthetic-password\n")
run("svnadmin", "hotcopy", str(root / "repo"), str(root / "repo-auth"))
(root / "repo-auth/conf/svnserve.conf").write_text(
    (root / "repo/conf/svnserve.conf")
    .read_text()
    .replace("anon-access = read", "anon-access = none")
)
subprocess.Popen(
    ["svnserve", "--daemon", "--foreground", "--root", str(root), "--listen-port", "3690"]
)
(root / "apache.conf").write_text(config)
os.execvp("apache2", ["apache2", "-f", str(root / "apache.conf"), "-DFOREGROUND"])
