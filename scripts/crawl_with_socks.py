#!/usr/bin/env python3
"""Run the resumable crawler through a private SOCKS URL file (requires PySocks)."""
import os
import socket
from pathlib import Path
from urllib.parse import urlsplit, unquote

if os.environ.get('BABADUM_SOCKS_FILE'):
    import socks
    proxy = urlsplit(Path(os.environ['BABADUM_SOCKS_FILE']).read_text().strip())
    if proxy.scheme not in ('socks5', 'socks5h') or not proxy.hostname or not proxy.port:
        raise ValueError('Expected a SOCKS5 URL in BABADUM_SOCKS_FILE')
    socks.set_default_proxy(socks.SOCKS5, proxy.hostname, proxy.port, rdns=True,
                            username=unquote(proxy.username) if proxy.username else None,
                            password=unquote(proxy.password) if proxy.password else None)
    socket.socket = socks.socksocket
    def connect(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None):
        return socks.create_connection(address, timeout=timeout, source_address=source_address,
                                       proxy_type=socks.SOCKS5, proxy_addr=proxy.hostname,
                                       proxy_port=proxy.port, proxy_rdns=True,
                                       proxy_username=unquote(proxy.username) if proxy.username else None,
                                       proxy_password=unquote(proxy.password) if proxy.password else None)
    socket.create_connection = connect
    # Disable inherited HTTP proxies; this process uses the SOCKS tunnel.
    import urllib.request
    urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))

if __name__ == '__main__':
    import crawl_babadum
    raise SystemExit(crawl_babadum.main())
