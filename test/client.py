import json
import logging
import socket
import time
import unittest
from unittest import mock

from .. import client, ProtocolError, VersionMismatchError
from . import utils


class TestClient(utils.Patches, unittest.TestCase):

    TO_PATCH = {'socket': 'socket.socket'}

    def setUp(self):
        super().setUp()
        self.s = client.SocketForwarder('test-host', 999,
                                        filename='test.log', maxBytes=1024)


class TestClientBasics(TestClient):

    def test_create(self):
        self.assertEqual(self.s.host, 'test-host')
        self.assertEqual(self.s.port, 999)
        self.assertEqual(self.s.kwargs, {'filename': 'test.log',
                                         'maxBytes': 1024})
        self.assertTrue(isinstance(self.s, logging.Handler))

    def test_createSocket(self):
        self.s.doHandshake = mock.MagicMock()
        self.s.createSocket()
        self.s.sock.connect.assert_called_once_with(('test-host', 999))
        self.s.doHandshake.assert_called_once_with()

    def test_sendtext(self):
        self.s.send = mock.MagicMock()
        self.s.sendtext('Test text')
        self.s.send.assert_called_once_with('Test text'.encode('UTF-8'))
        self.s.send.reset_mock()
        self.s.sendtext('Test bytes'.encode('UTF-8'))
        self.s.send.assert_called_once_with('Test bytes'.encode('UTF-8'))

    # test for recv_line in its own test case

    def test_handshake_ok(self):
        responses = [(s + '\n') for s in ['HELLO 1.0', 'OK', 'OK']]
        self.s.recv_line = mock.MagicMock()
        self.s.recv_line.side_effect = iter(responses + [AssertionError,])
        self.s.sendtext = mock.MagicMock()
        self.s.createSocket()
        call_args_list = self.s.sendtext.call_args_list
        self.assertEqual(len(call_args_list), 3)

        # First check the HELLO message, sendall takes a string or bytes
        self.assertIn(call_args_list[0],
                      [mock.call('HELLO 1.0\n'),
                       mock.call('HELLO 1.0\n'.encode('UTF-8'))])

        # Now we check the call to IDENTIFY
        data = call_args_list[1][0][0]
        self.assertTrue(isinstance(data, (str, bytes)))
        try:
            data = data.decode('UTF-8')
        except AttributeError:
            pass
        self.assertEqual('\n', data[-1])
        msg, params = data.split(' ', 1)
        self.assertEqual(msg, 'IDENTIFY')
        try:
            params = json.loads(params)
        except ValueError:
            self.fail("Send invalid JSON data: %r" % params)
        self.assertIn('--level', params)
        try:
            self.assertEqual(logging._checkLevel(params.pop('--level')),
                             self.s.level)
        except (ValueError, TypeError):
            self.fail("Passed invalid level value")
        self.assertEqual(params, {'filename': 'test.log', 'maxBytes': 1024})

        # Finally we check the call to LOG
        self.assertIn(call_args_list[2],
                      [mock.call('LOG\n'),
                       mock.call('LOG\n'.encode('UTF-8'))])


class Test_Recv_Line(TestClient):

    def setUp(self):
        super().setUp()
        self.s.sock = mock.MagicMock()
        self.s.sock.recv = mock.MagicMock()

    def set_responses(self, responses, encode=True):
        if encode:
            self.s.sock.recv.side_effect = iter(
                [s.encode('UTF-8') for s in responses] +
                [AssertionError("Called recv too many times!")])
        else:
            self.s.sock.recv.side_effect = iter(
                list(responses) +
                [AssertionError("Called recv too many times!")])

    def test_line_working(self):
        self.set_responses(('this i', 's A t', 'est', '!\n'))
        line = self.s.recv_line()
        self.assertEqual(line, 'this is A test!\n')

    def test_line_multiple_messages(self):
        # The client only expects server messages in response to its own
        # messages, therefore a second queued message signifies trouble!
        self.set_responses(['tes', 'st #1\ntest2\n'])
        self.assertRaises(ProtocolError, self.s.recv_line)

    def test_line_too_long(self):
        self.set_responses(['abcd123456'] * 1025)
        self.assertRaises(ProtocolError, self.s.recv_line)

    def test_responses_too_slow(self):
        self.s.timeout = 1
        self.s.sock.recv.side_effect = lambda _: time.sleep(.2) or b'a'
        self.assertRaises(socket.timeout, self.s.recv_line)

    def test_invalid_utf8(self):
        self.set_responses([b'\xC0', '\n'.encode('UTF-8')], False)
        self.assertRaises(ProtocolError, self.s.recv_line)


class TestHandshakeFailures(TestClient):

    def setUp(self):
        super().setUp()
        self.s.recv_line = mock.MagicMock()
        self.s.sendtext = mock.MagicMock()

    def set_resps(self, val):
        self.s.recv_line.side_effect = list(val) + [AssertionError]
    resps = property(fset=set_resps)

    def force(self, error=None):
        if error is None:
            error = ProtocolError
        self.assertRaises(error, self.s.createSocket)

    def test_bad_hello(self):
        self.resps = ['GARBAGE\n']
        self.force()
        self.s.sendtext.assert_called_once_with('HELLO 1.0\n')

    def test_bad_hello_version(self):
        self.resps = ['HELLO 2.0\n']
        self.force(VersionMismatchError)
        self.s.sendtext.assert_called_once_with('HELLO 1.0\n')

    def test_bad_ok_1(self):
        self.resps = ['HELLO 1.0\n', 'NOT OK\n']
        self.force()
        self.assertEqual(2, len(self.s.sendtext.call_args_list))

    def test_bad_ok_2(self):
        self.resps = ['HELLO 1.0\n', 'OK\n', 'NOT OK\n']
        self.force()
        self.assertEqual(3, len(self.s.sendtext.call_args_list))

if __name__ == "__main__":
    unittest.main()
