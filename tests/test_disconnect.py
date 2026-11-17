import unittest

from sni_proxy.server import _is_disconnect


class DisconnectTests(unittest.TestCase):
    def test_connection_reset_is_normal(self):
        self.assertTrue(_is_disconnect(ConnectionResetError(10054, "reset")))

    def test_broken_pipe_is_normal(self):
        self.assertTrue(_is_disconnect(BrokenPipeError(10053, "closed")))

    def test_other_errors_are_real(self):
        self.assertFalse(_is_disconnect(ValueError("bad")))
        self.assertFalse(_is_disconnect(TimeoutError("timeout")))


if __name__ == "__main__":
    unittest.main()
