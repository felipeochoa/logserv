"""
This class provides an asyncore implementation of a logging server.

The bulk of the work is performed in the `LoggingChannel` class, which
handles each connection's state and file handler.

"""

import asyncore
import json
import logging
import pickle
import socket
import struct

from . import ProtocolError
from logging.handlers import RotatingFileHandler

class StrictDispatcher(asyncore.dispatcher):

    # Forbid the "cheap inheritance"
    def __getattr__(self, attr):  # pragma: no cover
        raise AttributeError("%s object has no attribute '%s'" %
                             (self.__class__.__name__, attr))


class LoggingChannel(StrictDispatcher):

    # The channel has 7 primary states in which it can be:
    #
    #   1. WELCOMING: initial state, awaiting Hello message
    #   2. IDENTIFYING: awaiting IDENTIFY message
    #   3. WAITING: awaiting LOG message
    #   4. LOG-HEADER: awaiting a new log record, including length header
    #   5. LOGGING: receiving body of a log record
    #   6. MESSAGING: receiving a message during the main connection
    #   7. CLOSED: not receiving any messages
    #
    #   State transition diagram:
    #
    #                           +--> 5
    #                           |    |
    #         1 --> 2 --> 3 --> 4 <--+
    #                           |    |
    #                           +--> 6
    #
    #      All states can go to state 7 as well
    #
    # In reality, the number of states is much greater since between many
    # state transitions the server sends a message to the client.

    NUM_LEN_BYTES = 4
    version = "1.0"

    def __init__(self, sock=None, map=None):
        super().__init__(sock, map)
        self._status = 'WELCOMING'
        self.handler = None
        self.read_buf = []
        self.write_buf = b''
        self.remaining = 0

    @property
    def status(self):
        return self._status

    @status.setter
    def status(self, val):
        if val == 'LOG-HEADER':
            self.remaining = self.NUM_LEN_BYTES
        self._status = val

    def readable(self):
        return not self.write_buf

    def writable(self):
        return bool(self.write_buf)

    def handle_write(self):
        if isinstance(self.write_buf, str):
            self.write_buf = self.write_buf.encode('UTF-8')
        sent = self.send(self.write_buf)
        self.write_buf = self.write_buf[sent:]

    def handle_read(self):
        if self.status == 'WELCOMING':
            self.welcome()
        elif self.status == 'IDENTIFYING':
            self.identify()
        elif self.status == 'WAITING':
            self.confirm_log()
        elif self.status == 'LOG-HEADER':
            self.receive_header()
        elif self.status == 'LOGGING':
            self.receive_log()
        elif self.status == 'MESSAGING':
            self.receive_msg()
        else: # pragma: no cover
            raise ValueError("self.status is %r" % self.status)

    def find_term(self, term='\n'.encode('UTF-8')):
        data = self.recv(1024)
        self.read_buf.append(data)
        if term in data:
            resp = b''.join(self.read_buf)
            if not data.endswith(term):
                raise ProtocolError("a %s-terminated message" % term, resp)
            elif term in data[:-1]:
                raise ProtocolError("a single-line message",
                                    "%s in the client response" % term)
            try:
                resp = resp.decode('UTF-8')
            except UnicodeDecodeError:
                raise ProtocolError("a UTF-8 string", resp)
            self.read_buf = []
            return resp
        return None

    def welcome(self):
        msg = self.find_term()
        if msg is not None:
            head = msg.split(' ', 1)[0]
            if head != 'HELLO':
                raise ProtocolError("'HELLO'", msg)
            # regardless of the client version, we just use 1.0
            self.write_buf = 'HELLO %s\n' % self.version
            self.status = 'IDENTIFYING'

    def identify(self):
        msg = self.find_term()
        if msg is not None:
            head = msg.split(' ', 1)[0]
            if not head == 'IDENTIFY':
                raise ProtocolError("'IDENTIFY'", head)
            rest = msg.split(' ', 1)[1]  # This will never fail
            try:
                params = json.loads(rest)
            except ValueError:
                raise ProtocolError("a JSON object", rest)
            if '--level' not in params:
                raise ProtocolError("a '--level' key", None)
            level = params.pop('--level')
            try:
                self.handler = RotatingFileHandler(**params)
            except TypeError as err:
                raise ProtocolError("valid parameters for "
                                    "`RotatingFileHandler`", err.args[0])
            self.handler.setLevel(level)
            self.write_buf = 'OK\n'
            self.status = 'WAITING'

    def confirm_log(self):
        msg = self.find_term()
        if msg is not None:
            if msg != 'LOG\n':
                raise ProtocolError("'LOG\n'", msg)
            self.write_buf = 'OK\n'
            self.status = 'LOG-HEADER'

    def receive_by_len(self):
        data = self.recv(self.remaining)
        self.read_buf.append(data)
        self.remaining -= len(data)
        if self.remaining == 0:
            all_data = b''.join(self.read_buf)
            self.read_buf = []
            return all_data
        return None

    def receive_header(self):
        data = self.receive_by_len()
        if data is not None:
            slen = struct.unpack(">L", data)[0]
            if slen == 0:
                self.status = 'MESSAGING'
            else:
                self.status = 'LOGGING'
            self.remaining = slen

    def receive_log(self):
        data = self.receive_by_len()
        if data is not None:
            self.status = 'LOG-HEADER'
            self.remaining = self.NUM_LEN_BYTES
            try:
                log_record = pickle.loads(data)
            except Exception as err:
                raise ProtocolError("a valid pickled object", err.args)
            else:
                self.handler.emit(log_record)

    def receive_msg(self):
        msg = self.find_term()
        if msg is not None:
            head = msg.split(' ', 1)[0]
            if head == 'FORMAT':
                try:
                    rest = msg.split(' ', 1)[1]
                    params = json.loads(rest)
                except ValueError:
                    raise ProtocolError("a valid JSON object", rest)
                if not isinstance(params, dict):
                    raise ProtocolError("a JSON dict",
                                        "a " + params.__class__.__name__)
                try:
                    self.format(**params)
                except TypeError as e:
                    raise ProtocolError("valid formatter parameters",
                                        e.args[0])
            elif head == 'QUIT\n':
                self.close()
            else:
                raise ProtocolError("One of 'FORMAT' or 'QUIT'",
                                    msg)

    def format(self, fmt=None, datefmt=None, style='%'):
        formatter = logging.Formatter(fmt, datefmt, style=style)
        self.handler.setFormatter(formatter)
        self.write_buf = 'OK\n'

    def close(self):
        super().close()
        self.read_buf = []
        self.write_buf = b''


class LogServer(StrictDispatcher):

    channel_class = LoggingChannel
    logging_map = {}
    socket_family = socket.AF_UNIX

    def __init__(self, socket_path):
        super().__init__()
        try:
            self.create_socket(self.socket_family, socket.SOCK_STREAM)
            self.bind(socket_path)
            self.listen(5)
        except:  # pragma: no cover
            self.close()
            raise

    def handle_accepted(self, conn, addr):
        self.channel_class(conn, self.logging_map)
