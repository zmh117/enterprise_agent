"""Isolated stdlib-only resolver. Receives names, never URLs or credentials."""

import json
import socket
import sys


def main() -> None:
    try:
        request = json.loads(sys.stdin.buffer.read(4097))
        host, port, family, kind, proto, flags = request
        if not isinstance(host, str) or len(host) > 253:
            raise ValueError
        rows = socket.getaddrinfo(host, port, family, kind, proto, flags)
        # Resolver output is bounded too, independently of a configured DNS server.
        if not 0 < len(rows) <= 64:
            raise ValueError
        body = json.dumps(rows).encode()
        if len(body) > 32768:
            raise ValueError
        sys.stdout.buffer.write(body)
    except Exception:
        sys.exit(1)


if __name__ == "__main__":
    main()
