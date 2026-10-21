#!/usr/bin/env python3
"""Expose an authenticated HTTPS CONNECT proxy as a local SOCKS5 proxy.

The crawler speaks SOCKS5 (PySocks). The managed proxy gateway speaks HTTPS
CONNECT. This bridge lets the crawler use the stable gateway without changing
its transport code.
"""
import argparse
import base64
import socket
import ssl
import struct
import threading
from urllib.parse import urlsplit


def read_exact(stream, count):
    data = b''
    while len(data) < count:
        chunk = stream.recv(count - len(data))
        if not chunk:
            raise OSError('unexpected end of stream')
        data += chunk
    return data


class Bridge:
    def __init__(self, proxy_url):
        parts = urlsplit(proxy_url)
        if parts.scheme != 'https' or not parts.hostname or not parts.port:
            raise ValueError('expected an https:// proxy URL')
        self.host = parts.hostname
        self.port = parts.port
        self.auth = base64.b64encode(
            '{}:{}'.format(parts.username or '', parts.password or '').encode()
        ).decode()
        self.context = ssl.create_default_context()

    def connect(self, host, port):
        raw = socket.create_connection((self.host, self.port), timeout=20)
        try:
            stream = self.context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise
        request = (
            'CONNECT {}:{} HTTP/1.1\r\nHost: {}:{}\r\n'
            'Proxy-Authorization: Basic {}\r\n\r\n'
        ).format(host, port, host, port, self.auth)
        stream.sendall(request.encode('ascii'))
        response = b''
        while b'\r\n\r\n' not in response:
            chunk = stream.recv(4096)
            if not chunk:
                stream.close()
                raise OSError('proxy closed during CONNECT')
            response += chunk
            if len(response) > 65536:
                stream.close()
                raise OSError('proxy response too large')
        status = response.split(b'\r\n', 1)[0]
        if b' 200 ' not in status:
            stream.close()
            raise OSError('proxy refused CONNECT: ' + status.decode('latin1'))
        prefix = response.split(b'\r\n\r\n', 1)[1]
        if prefix:
            stream.prepend = prefix
        return stream


def relay(source, target):
    try:
        while True:
            data = source.recv(65536)
            if not data:
                break
            target.sendall(data)
    except OSError:
        pass
    finally:
        try:
            target.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def handle(client, bridge):
    upstream = None
    try:
        version, methods = read_exact(client, 2)
        if version != 5:
            return
        read_exact(client, methods)
        client.sendall(b'\x05\x00')
        version, command, _, address_type = read_exact(client, 4)
        if version != 5 or command != 1:
            return
        if address_type == 1:
            host = socket.inet_ntoa(read_exact(client, 4))
        elif address_type == 3:
            length = read_exact(client, 1)[0]
            host = read_exact(client, length).decode('idna')
        elif address_type == 4:
            host = socket.inet_ntop(socket.AF_INET6, read_exact(client, 16))
        else:
            return
        port = struct.unpack('!H', read_exact(client, 2))[0]
        upstream = bridge.connect(host, port)
        bound = upstream.getsockname()
        client.sendall(b'\x05\x00\x00\x01' + socket.inet_aton('0.0.0.0') + struct.pack('!H', 0))
        pending = getattr(upstream, 'prepend', b'')
        if pending:
            client.sendall(pending)
        threading.Thread(target=relay, args=(client, upstream), daemon=True).start()
        relay(upstream, client)
    except OSError:
        pass
    finally:
        if upstream is not None:
            try:
                upstream.close()
            except OSError:
                pass
        try:
            client.close()
        except OSError:
            pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--listen-port', type=int, default=11990)
    parser.add_argument('--proxy-url-file', default='data/proxy/http.url')
    args = parser.parse_args()
    with open(args.proxy_url_file, 'r', encoding='utf-8') as source:
        bridge = Bridge(source.read().strip())
    listener = socket.create_server(('127.0.0.1', args.listen_port), reuse_port=False)
    print('SOCKS5 bridge listening on 127.0.0.1:{}'.format(args.listen_port), flush=True)
    while True:
        client, _ = listener.accept()
        threading.Thread(target=handle, args=(client, bridge), daemon=True).start()


if __name__ == '__main__':
    main()
