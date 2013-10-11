import json
import logging
import socket
import time
import unittest
from unittest import mock

from .. import server, ProtocolError
from . import utils


class TestServer(utils.Patches, unittest.TestCase):

    TO_PATCH = {'socket': 'socket.socket'}

    def test_create(self):
        s = server.LogServer('path')
        self.assertEqual('path', s.addr)
        self.assertTrue(s.accepting)
        s.socket.bind.assert_called_once_with('path')
        s.socket.listen.assert_called_once_with(5)

    def test_accepted(self):
        s = server.LogServer('path')
        s.channel_class = mock.MagicMock()
        s.handle_accepted('new_sock', 'new_addr')
        s.channel_class.assert_called_once_with('new_sock', s.logging_map)
        self.assertEqual(server.LogServer.channel_class,
                         server.LoggingChannel)


if __name__ == "__main__":
    unittest.main()
