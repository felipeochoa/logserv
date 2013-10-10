import json
import logging.handlers
import socket
import time

from . import ProtocolError, VersionMismatchError

class SocketForwarder(logging.handlers.SocketHandler):

    """
    A `SocketHandler` subclass that converses with a log server.

    Any extra keyword parameters are passed on to the `RotatingFileHandler`
    on the other end of the socket.

    All of the IO is performed blockingly, like in the parent class.

    """

    version_str = "1.0"
    max_line_length = 10240

    def __init__(self, host, port, timeout=None, **kwargs):
        self.shook_hands = False
        self.kwargs = kwargs
        if timeout is None:
            self.timeout = socket.getdefaulttimeout()
        else:
            self.timeout = timeout
        super().__init__(host, port)

    def createSocket(self):
        """
        Creates a socket and performs the handshake with the server.
        """
        super().createSocket()
        self.doHandshake()

    def sendtext(self, data):
        if isinstance(data, str):
            data = data.encode('UTF-8')
        self.send(data)

    def recv_line(self, decode=True):
        resp = [b'']
        resp_len = 0
        terminator = '\n'.encode('UTF-8')
        start = time.time()
        while terminator not in resp[-1]:
            if self.timeout is not None and time.time() > start + self.timeout:
                raise socket.timeout
            elif resp_len > self.max_line_length:
                raise ProtocolError("a line of length < %d",
                                    "too many bytes")
            data = self.sock.recv(1024)
            resp.append(data)
            resp_len += len(data)
        resp = b''.join(resp)
        if decode:
            resp = resp.decode('UTF-8')
        other = resp.split('\n', 1)[1]
        if other:
            raise ProtocolError("a %s-terminated message" % terminator,
                                resp)
        return resp

    def doHandshake(self):
        self.sendtext('HELLO %s\n' % self.version_str)
        resp = self.recv_line()
        if not resp.startswith('HELLO '):
            raise ProtocolError('"HELLO <version>\n"', resp)
        elif resp[6:] != '1.0\n':
            raise VersionMismatchError("Handler does not support version %s",
                                       resp[6:],)
        params = {'--level': self.level}
        params.update(self.kwargs)
        param_json = json.dumps(params) + '\n'
        self.sendtext('IDENTIFY %s' % param_json)
        resp = self.recv_line()
        if resp != 'OK\n':
            raise ProtocolError("'OK\n'", resp)
        self.shook_hands = True
        self.sendtext('LOG\n')
        resp = self.recv_line()
        if resp != 'OK\n':
            raise ProtocolError("'OK\n'", resp)
