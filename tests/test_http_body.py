import unittest

from sni_proxy.server import _read_http_body


class _FakeSock:
    def __init__(self, data):
        self.data = data

    def recv(self, n):
        chunk = self.data[:n]
        self.data = self.data[n:]
        return chunk


class HttpBodyTests(unittest.TestCase):
    def test_content_length_body_is_not_truncated(self):
        lines = ["POST /upload HTTP/1.1", "Content-Length: 10"]
        body = _read_http_body(_FakeSock(b"56789"), b"01234", lines)
        self.assertEqual(body, b"0123456789")

    def test_chunked_body_is_read_to_terminator(self):
        lines = ["POST /upload HTTP/1.1", "Transfer-Encoding: chunked"]
        body = _read_http_body(
            _FakeSock(b"3\r\nabc\r\n0\r\n\r\n"), b"", lines)
        self.assertTrue(body.endswith(b"0\r\n\r\n"))


if __name__ == "__main__":
    unittest.main()
