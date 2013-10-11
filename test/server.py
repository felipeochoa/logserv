import json
import logging
import socket
import struct
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


class TestChannel(utils.Patches, unittest.TestCase):

    TO_PATCH = {'socket': 'socket.socket'}

    def setUp(self):
        super().setUp()
        self.map = {}
        self.c = server.LoggingChannel(mock.MagicMock(), self.map)


class TestChannelBasic(TestChannel):

    def test_create(self):
        self.assertEqual(self.c.status, 'WELCOMING')
        self.assertEqual(self.c.handler, None)
        self.assertEqual(self.c.read_buf, [])
        self.assertEqual(self.c.write_buf, b'')
        self.assertEqual(self.c.remaining, 0)

    def test_read_write_state(self):
        self.assertTrue(self.c.readable())
        self.assertFalse(self.c.writable())
        self.c.write_buf = b'Test message\n'
        self.assertTrue(self.c.writable())
        self.assertFalse(self.c.readable())


class TestReadLine(TestChannel):

    def setUp(self):
        super().setUp()
        self.c.recv = mock.MagicMock()

    def test_single_read(self):
        self.c.recv.return_value = 'Test line\n'.encode('UTF-8')
        line = self.c.find_term()
        self.assertEqual(line, 'Test line\n')
        self.c.recv.assert_called_once_with(1024)
        self.assertEqual(self.c.read_buf, [])

    def test_multiple_reads(self):
        self.c.recv.side_effect = ['Tes'.encode('UTF-8'),
                                    't l'.encode('UTF-8'),
                                    'ine\n'.encode('UTF-8')]
        resp = self.c.find_term()
        self.assertEqual(resp, None)
        self.assertEqual(self.c.read_buf, ['Tes'.encode('UTF-8')])

        resp = self.c.find_term()
        self.assertEqual(resp, None)
        self.assertEqual(self.c.read_buf, ['Tes'.encode('UTF-8'),
                                           't l'.encode('UTF-8')])

        resp = self.c.find_term()
        self.assertEqual(resp, 'Test line\n')
        self.assertEqual(self.c.read_buf, [])

    def test_malformed_data(self):
        self.c.recv.return_value = ('two lines\n'
                                    'in one message\n').encode('UTF-8')
        self.assertRaises(ProtocolError, self.c.find_term)

    def test_split_malformed_data(self):
        self.c.recv.side_effect = ['two lines'.encode('UTF-8'),
                                   '\nin one message\n'.encode('UTF-8')]
        self.c.find_term()
        self.assertRaises(ProtocolError, self.c.find_term)

    def test_extra_data(self):
        self.c.recv.return_value = 'a line\nwith extra data'.encode('UTF-8')
        self.assertRaises(ProtocolError, self.c.find_term)

    def test_invalid_unicode_in_data(self):
        self.c.recv.return_value = b'\xC0' + '\n'.encode('UTF-8')
        self.assertRaises(ProtocolError, self.c.find_term)


class TestReadByLen(TestChannel):

    def setUp(self):
        super().setUp()
        self.c.recv = mock.MagicMock()
        self.c.remaining = 10

    def test_single_read(self):
        self.c.recv.return_value = '1234567890'.encode('UTF-8')
        ret = self.c.receive_by_len()
        self.assertEqual(ret, '1234567890'.encode('UTF-8'))
        self.assertEqual(self.c.read_buf, [])
        self.assertEqual(self.c.remaining, 0)

    def test_multiple_reads(self):
        self.c.recv.side_effect = ['123'.encode('UTF-8'),
                                 '456'.encode('UTF-8'),
                                 '7890'.encode('UTF-8')]
        ret = self.c.receive_by_len()
        self.assertEqual(ret, None)
        self.assertEqual(self.c.read_buf, ['123'.encode('UTF-8')])
        self.assertEqual(self.c.remaining, 7)
        ret = self.c.receive_by_len()
        self.assertEqual(ret, None)
        self.assertEqual(self.c.read_buf, ['123'.encode('UTF-8'),
                                           '456'.encode('UTF-8')])
        self.assertEqual(self.c.remaining, 4)
        ret = self.c.receive_by_len()
        self.assertEqual(ret, '1234567890'.encode('UTF-8'))
        self.assertEqual(self.c.read_buf, [])
        self.assertEqual(self.c.remaining, 0)


class TestWriting(TestChannel):

    def setUp(self):
        super().setUp()
        self.socket = self.c.socket
        self.socket.send = mock.MagicMock(return_value=13)

    def test_write_string(self):
        self.c.write_buf = 'test message\n'
        self.c.handle_write()
        self.c.socket.send.assert_called_once_with(
            'test message\n'.encode('UTF-8'))
        self.assertFalse(self.c.writable())

    def test_write_bytes(self):
        self.c.write_buf = 'test message\n'.encode('UTF-8')
        self.c.handle_write()
        self.c.socket.send.assert_called_once_with(
            'test message\n'.encode('UTF-8'))
        self.assertFalse(self.c.writable())

    def test_partial_write_string(self):
        self.c.write_buf = 'test message\n'
        self.socket.send.return_value = 5
        self.c.handle_write()
        self.assertEqual(self.c.write_buf, 'message\n'.encode('UTF-8'))
        self.assertTrue(self.c.writable())

    def test_partial_write_bytes(self):
        self.c.write_buf = 'test message\n'.encode('UTF-8')
        self.socket.send.return_value = 5
        self.c.handle_write()
        self.assertEqual(self.c.write_buf, 'message\n'.encode('UTF-8'))
        self.assertTrue(self.c.writable())


if __name__ == "__main__":
    unittest.main()
