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


class TestReading(TestChannel):

    def setUp(self):
        super().setUp()
        self.c.recv = mock.MagicMock()
        self.c.remaining = 10

class TestReadline(TestReading):

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


class TestReadByLen(TestReading):

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


class TestStateTransitions(TestReading):

    def setUp(self):
        self.TO_PATCH['pickle'] = 'pickle.loads'
        super().setUp()
        for attr in ['welcome', 'identify', 'confirm_log',
                     'receive_header', 'receive_log', 'receive_msg',
                     'format']:
            setattr(self.c, attr,
                    mock.MagicMock(wraps=getattr(self.c, attr)))

    def set_return_value(self, val):
        self.c.recv.return_value = val
    ret = property(fset=set_return_value)
    def encode_set_return_value(self, val):
        self.ret = val.encode('UTF-8')
    eret = property(fset=encode_set_return_value)


class TestNormalTransitions(TestStateTransitions):

    def test_welcome(self):
        self.assertEqual(self.c.status, 'WELCOMING')
        self.eret = 'HELLO 1.0\n'
        self.c.handle_read()
        self.c.welcome.assert_called_once_with()
        self.assertEqual(self.c.status, 'IDENTIFYING')
        self.assertEqual(self.c.write_buf, 'HELLO 1.0\n')

    def test_identify(self):
        self.c.status = 'IDENTIFYING'
        self.eret = ('IDENTIFY {"--level": 0, "filename":' +
                     ' "test.log", "maxBytes": 10240}\n')
        self.c.handle_read()
        self.c.identify.assert_called_once_with()
        self.assertEqual(self.c.status, 'WAITING')
        self.assertEqual(self.c.write_buf, 'OK\n')

    def test_waiting(self):
        self.c.status = 'WAITING'
        self.eret = "LOG\n"
        self.c.handle_read()
        self.c.confirm_log.assert_called_once_with()
        self.assertEqual(self.c.status, 'LOG-HEADER')
        self.assertEqual(self.c.write_buf, 'OK\n')

    def test_log_header_to_log(self):
        self.c.status = 'LOG-HEADER'
        self.ret = b"\x00\x00\x00\x0A"
        self.c.handle_read()
        self.c.receive_header.assert_called_once_with()
        self.assertEqual(self.c.status, 'LOGGING')
        self.assertEqual(self.c.write_buf, b'')

    def test_log_header_to_message(self):
        self.c.status = 'LOG-HEADER'
        self.assertEqual(self.c.remaining, len(struct.pack(">L", 99)))
        self.ret = b"\x00\x00\x00\x00"
        self.c.handle_read()
        self.c.receive_header.assert_called_once_with()
        self.assertEqual(self.c.remaining, 0)
        self.assertEqual(self.c.status, 'MESSAGING')
        self.assertEqual(self.c.write_buf, b'')

    def test_receive_log(self):
        self.c.status = "LOGGING"
        record = object()  # new unique object
        self.mocks['pickle'].return_value = record
        self.c.handler = mock.MagicMock()
        self.ret = b"a binary-format pickle..."
        self.c.remaining = len(b"a binary-format pickle...")
        self.c.handle_read()
        self.c.receive_log.assert_called_once_with()
        self.c.handler.emit.assert_called_once_with(record)
        self.assertEqual(self.c.write_buf, b'')

    def test_receive_format_msg(self):
        self.c.status = 'MESSAGING'
        self.c.handler = logging.Handler()
        self.eret = 'FORMAT {"fmt": "%(message)s"}\n'
        self.c.handle_read()
        self.c.receive_msg.assert_called_once_with()
        self.c.format.assert_called_once_with(fmt='%(message)s')
        self.assertEqual(self.c.write_buf, 'OK\n')

    def test_receive_quit_msg(self):
        self.c.status = 'MESSAGING'
        self.c.handler = logging.Handler()
        self.eret = 'QUIT\n'
        self.c.handle_read()
        self.c.receive_msg.assert_called_once_with()
        self.assertFalse(self.c.connected)


class TestProtocolErrors(TestStateTransitions):

    def force(self):
        self.assertRaises(ProtocolError, self.c.handle_read)

    def test_welcome(self):
        self.assertEqual(self.c.status, 'WELCOMING')
        self.eret = 'GARBAGE\n'
        self.force()

    def test_identify_header(self):
        self.c.status = 'IDENTIFYING'
        self.eret = 'GARBAGE{data...}\n'
        self.force()

    def test_identify_no_data(self):
        self.c.status = 'IDENTIFYING'
        self.eret = 'IDENTIFY\n'
        self.force()

    def test_identify_json(self):
        self.c.status = 'IDENTIFYING'
        self.eret = 'IDENTIFY {NOT JSON!!}\n'
        self.force()

    def test_identify_json_not_dict(self):
        self.c.status = 'IDENTIFYING'
        self.eret = 'IDENTIFY [1, 2, 3]\n'
        self.force()

    def test_identify_data(self):
        self.c.status = 'IDENTIFYING'
        self.eret = 'IDENTIFY {"--level": 0, "not_a_param": 1}\n'
        self.force()

    def test_identify_no_level(self):
        self.c.status = 'IDENTIFYING'
        self.eret = 'IDENTIFY {"not_a_param": 1, "not_another_param": 3}\n'
        self.force()

    def test_waiting_bad_call(self):
        self.c.status = 'WAITING'
        self.eret = 'GARBAGE\n'
        self.force()

    def test_log_bad_pickle(self):
        self.c.status = 'LOGGING'
        self.c.remaining = 10
        self.ret = b'1234567890'
        self.mocks['pickle'].side_effect = pickle.UnpicklingError
        self.force()

    def test_bad_message_name(self):
        self.c.status = 'MESSAGING'
        self.eret = 'GARBAGE\n'
        self.force()

    def test_no_format_params(self):
        self.c.status = 'MESSAGING'
        self.eret = 'FORMAT\n'
        self.force()

    def test_bad_format_params(self):
        self.c.status = 'MESSAGING'
        self.eret = 'FORMAT {NOT JSON!}\n'
        self.force()

    def test_invalid_format_params(self):
        self.c.status = 'MESSAGING'
        self.eret = 'FORMAT {"not_an_arg": 3}\n'
        self.force()

    def test_format_params_not_json_dict(self):
        self.c.status = 'MESSAGING'
        self.eret = 'FORMAT [3, 4]\n'
        self.force()


if __name__ == "__main__":
    unittest.main()
