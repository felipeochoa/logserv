"""
This class provides an asyncore implementation of a logging server.

The bulk of the work is performed in the `LoggingChannel` class, which
handles each connection's state and file handler.

"""

import asyncore
import json
import pickle
import socket
import struct

class LoggingChannel(asyncore.dispatcher):

    NUM_LEN_BYTES = 4

    def __init__(self, sock=None, map=None):
        super().__init__(sock, map)
        self.status = 'WELCOMING'
        self.handler = None
        self.read_buf = []
        self.write_buf = b''
        self.remaining = self.NUM_LEN_BYTES

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
        elif self.status == 'FORMATTING':
            self.set_format()
        elif self.status == 'WAITING':
            self.confirm_log()
        elif self.status == 'LOG-HEADER':
            self.receive_header()
        elif self.status == 'LOGGING':
            self.receive_log()
        else:
            raise ValueError("self.status is %r" % self.status)

    def find_term(self, term='\n'.encode('UTF-8')):
        data = self.recv(128)
        self.read_buf.append(data)
        if term in data:
            resp = b''.join(self.read_buf)
            if not data.endswith(term):
                raise ProtocolError("a %s-terminated message" % term, resp)
            elif term in data[:-1]:
                raise ProtocolError("a single-line message",
                                    "%s in the client response" % term)
            return resp
        return None

    def welcome(self):
        msg = self.find_term()
        if msg is not None:
            msg = msg.decode('UTF-8')
            head, rest = msg.split(' ', 1)
            if head != 'HELLO':
                raise ProtocolError("'HELLO\n'", msg)
            if rest != '1.0\n':
                raise VersionMismatchError("Server does not support " +
                                           "version %s" % rest)
            self.write_buf = 'HELLO %s\n' % self.version
            self.status = 'IDENTIFYING'

    def identify(self):
        msg = self.find_term()
        if msg is not None:
            msg = msg.decode('UTF-8')
            head, rest = msg.split(' ', 1)
            if not head == 'IDENTIFY':
                raise ProtocolError("'IDENTIFY'", head)
            try:
                params = json.loads(rest)
            except ValueError:
                raise ProtocolError("a JSON object", rest)
            if 'lvl' not in params:
                raise ProtocolError("a 'lvl' key", None)
            level = params['lvl']
            try:
                self.handler = RotatingFileHandler(**params)
            except TypeError as err:
                raise ProtocolError("valid parameters for "
                                    "`RotatingFileHandler`", err.args[0])
            self.handler.setLevel(level)
            self.write_buf = 'OK\n'
            self.status = 'FORMATTING'

    def set_format(self):
        msg = self.find_term()
        if msg is not None:
            msg = msg.decode('UTF-8')
            head, rest = msg.split(' ')
            if head == 'LOG\n':  # rest is blank
                self.status = 'LOG-HEADER'
                self.write_buf = 'OK\n'
            elif head == 'FORMAT':
                try:
                    params = json.loads(rest)
                except ValueError:
                    raise ProtocolError("a JSON object", rest)
                try:
                    formatter = logging.Formatter(**params)
                except TypeError as err:
                    raise ProtocolError("valid parameters for "
                                        "logging.Formatter", err.args[0])
                self.handler.setFormatter(formatter)
                self.status = 'WAITING'

    def confirm_log(self):
        msg = self.find_term()
        if msg is not None:
            if msg != 'LOG\n'.encode('UTF-8'):
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
            slen = struct.unpack(">L", data)
            if slen == 0:
                return self.quit()
            self.remaining = slen
            self.status = 'LOGGING'

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

    def quit(self):
        self.close()


class LogServer(asyncore.dispatcher):

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

    # Forbid the "cheap inheritance"
    def __getattr__(self, attr):
        raise AttributeError("%s object has no attribute '%s'" %
                             (self.__class__.__name__, attr))
