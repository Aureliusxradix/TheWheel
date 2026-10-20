"""Links a member pastes may reach the public internet only.

The server fetches whatever link a member pastes into Add a listing. On the live box that fetch starts inside the
house's network, so a link to a private address (the house's own services, the router, another container) must
never be followed. The check sits at the moment a connection is made, on the address actually dialled, so a
redirect or a name that resolves differently the second time cannot slip past it.

Imported by reader/core.py, which installs it. WHEEL_ALLOW_PRIVATE_FETCH=1 turns it off (tests against a local page).
"""
import ipaddress
import os
import socket

import urllib3.util.connection as _conn


class BlockedAddress(OSError):
    pass


def public(ip: str) -> bool:
    a = ipaddress.ip_address(ip.split("%")[0])
    if a.version == 6 and a.ipv4_mapped:
        a = a.ipv4_mapped
    return a.is_global


def create_connection(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None, socket_options=None):
    host, port = address
    host = host.strip("[]")
    err: OSError | None = None
    for af, socktype, proto, _, sa in socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM):
        if not public(sa[0]):
            err = BlockedAddress(f"{host} is not on the public internet")
            continue
        sock = socket.socket(af, socktype, proto)
        try:
            for opt in socket_options or ():
                sock.setsockopt(*opt)
            if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect(sa)  # the vetted address itself, never a second lookup
            return sock
        except OSError as e:
            err = e
            sock.close()
    raise err or OSError(f"{host}: no address")


def install():
    if os.environ.get("WHEEL_ALLOW_PRIVATE_FETCH") != "1":
        _conn.create_connection = create_connection
