import json
import logging.handlers

from . import ProtocolError, VersionMismatchError

class SocketForwarder(logging.handlers.SocketHandler):

    """
    A `SocketHandler` subclass that converses with a log server.

    Any extra keyword parameters are passed on to the `RotatingFileHandler`
    on the other end of the socket.

    All of the IO is performed blockingly, like in the parent class.

    """

    def __init__(self, host, port=None, **kwargs):
        if port is not None:
            raise TypeError("%s does not take a 'port' argument")
        self.shook_hands = False
        self.kwargs = kwargs
        super().__init__(self, host, port)

    def makeSocket(self, timeout=1):
        """
        Makes a socket and performs the handshake with the server.
        """
        s = super().makeSocket(timeout)
        self.doHandshake()
        return s

    def sendall(self, data):
        if isinstance(data, str):
            data = data.encode('UTF-8')
        left = len(data)
        sentsofar = 0
        while left > 0:
            sent = self.sock.send(data[sentsofar:])
            sentsofar = sentsofar + sent
            left = left - sent

    def recv_until(self, terminator, decode=True):
        resp = ['']
        if decode:
            terminator = terminator.encode('UTF-8')
        while terminator not in resp[-1]:
            resp.append(self.sock.recv(128))
        resp = b''.join(resp)
        if decode:
            resp = resp.decode('UTF-8')
        resp, other = resp.split(terminator)
        if other:
            raise ProtocolError("a %s-terminated message" % terminator,
                                other)
        return resp

    def doHandshake(self):
        self.sendall('HELLO\n')
        resp = self.recv_until('\n')
        if not resp.startswith('HELLO '):
            raise ProtocolError('"HELLO <version>\n"', resp)
        elif resp[6:] != '1.0\n':
            raise VersionMismatchError("Handler does not support version %s",
                                       resp[6:],)
        params = {'lvl': self.level}
        params.update(self.kwargs)
        param_json = json.dumps(params)
        self.sendall('IDENTIFY %s' % param_json)
        resp = self.recv_until('\n')
        if resp != 'OK\n':
            raise ProtocolError("'OK\n'", resp)
        self.shook_hands = True
