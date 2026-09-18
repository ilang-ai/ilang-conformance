# -*- coding: utf-8 -*-
"""run.http_transport against a server that closes the connection after its reply.

A reply sent with `Connection: close` (or as HTTP/1.0) makes http.client close the socket
once the body has been read. The transport must stop reading there and not touch the closed
socket again; before the fix it set a timeout on it, got OSError (EBADF on POSIX, WinError
10038 on Windows), and recorded a good reply as a network error. No socket is opened: a fake
socket stands in for the connection, closing for real only when both the connection and the
response file have let it go, as a Python socket does.
"""

import http.client
import io
import json
import unittest

import support  # noqa: F401  (blocks the network, puts the repository on sys.path)
import run as runner


class _File(io.BytesIO):
    def __init__(self, data, owner):
        super().__init__(data)
        self.owner = owner

    def close(self):
        self.owner.file_closed = True
        super().close()


class _Sock:
    def __init__(self, response):
        self.response = response
        self.sent = b""
        self.close_called = False
        self.file_closed = False

    def sendall(self, data):
        self.sent += data

    def makefile(self, mode, *args, **kwargs):
        return _File(self.response, self)

    def settimeout(self, seconds):
        if self.close_called and self.file_closed:
            raise OSError(9, "Bad file descriptor")

    def close(self):
        self.close_called = True


def reply(version, extra_headers, body):
    head = "%s 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\n%s\r\n" % (
        version, len(body), "".join(h + "\r\n" for h in extra_headers))
    return head.encode("ascii") + body


class TransportCloseTests(unittest.TestCase):
    def call(self, raw):
        sock = _Sock(raw)
        saved = http.client.HTTPConnection.connect
        http.client.HTTPConnection.connect = lambda self: setattr(self, "sock", sock)
        try:
            return runner.http_transport("http://stub.invalid/v1/chat/completions", {}, b"{}", 5), sock
        finally:
            http.client.HTTPConnection.connect = saved

    def test_http10_reply_is_read_whole(self):
        body = json.dumps({"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}).encode()
        (status, headers, got), sock = self.call(reply("HTTP/1.0", [], body))
        self.assertEqual((status, got), (200, body))
        self.assertTrue(sock.close_called and sock.file_closed)

    def test_connection_close_reply_is_read_whole(self):
        body = b'{"x": "' + b"y" * 200000 + b'"}'
        (status, headers, got), _ = self.call(reply("HTTP/1.1", ["Connection: close"], body))
        self.assertEqual((status, got), (200, body))
        self.assertEqual(headers.get("connection"), "close")

    def test_keep_alive_reply_still_works(self):
        body = b'{"ok": true}'
        (status, headers, got), _ = self.call(reply("HTTP/1.1", [], body))
        self.assertEqual((status, got), (200, body))


if __name__ == "__main__":
    unittest.main()
