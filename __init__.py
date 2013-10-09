"""
Applications needing to generate logs use a special handler that connects
to a logging server. The server and the client form a connection on a
separate socket, and the client uses a subclass of `SocketHandler` to
"post" log records to the server.

The protocol used to communicate between the client and the server is built
on the same pickle-based protocol used in SocketHandler:

  Upon connecting to the server, the client must initiate a handshake with
  the server by sending the message*

      'HELLO <version-info>\n'

  The server then responds

      'HELLO <version-info>\n'

  In both instances, <version-info> is a string identifying the maximum
  protocol version supported by each party. Currently only "1.0" is in
  use.

  The client must then respond with the message

      'IDENTIFY <params>\n'

  where <params> is a JSON-serialized dict with certain requirements:

  * <params> must contain the key 'lvl'
  * <params>['lvl'] must be an acceptable argument for `setLevel`.
  * The remaining keys in <params> are passed to the 'RotatingFileHandler'
    constructor to create the handler that will accept the client's logging
    requests.

  The server then responds with the message

      'OK\n'

  and the handshake is completed.

  Once the handshake has been performed, the client sends the message

      'LOG\n'

  and the server responds

      'OK\n'

  At that point the server listens passively for log records in the format
  created by `logging.handlers.SocketHandlers`:

      log-record  =  len-bytes pickle-data
      len-bytes   =  A big-endian 4 byte integer specifying the length of
                     pickle-data
      pickle-data =  a serialized dictionary with the instance data of a
                     record object with 'msg', 'args', and 'exc_info'
                     modified as in `logging.handlers.SocketHandlers`

  If the client wishes to communicate something else to the server at this
  time, it sends out 4 null bytes "\x00\x00\x00\x00" at the start of a
  record, followed by a newline-terminated message:

      message       =  "\x00\x00\x00\x00" message-text
      message-text  =  <non-newline characters>* '\n'

  Version 1.0 of the protocol supports two messages this way:

  1. Formatter -- if the message text is a formatter-message, the server will
     use the parameters given as arguments to construct a `logging.Formatter`
     instance that will be attached to the handler.  Only the vanilla
     built-in formatter is supported, so the only parameters to communicate
     are 'fmt', 'datefmt', and 'style'. If the client is using custom
     formatting, it MAY communicate this to the server by sending a message

         "FORMAT <params>\n"

     where <params> is a JSON-serialized dict whose keys form a subset of
     'fmt', 'datefmt', and 'style'. The server attempts to create and attach
     the formatter, and if successful responds with the message

         'OK\n'

  2. Quitting -- before terminating the connection, the client SHOULD send a
     quit message:

         'QUIT\n'

* Except for the `len-bytes` and `pickle-data` transmissions, all text MUST
  be encoded in UTF-8

"""
class LogServerError(Exception):
    pass

class ProtocolError(LogServerError):

    def __init__(self, expected, actual):
        self.expected = expected
        self.actual = actual
        msg = "EXPECTED %s, received %s" % (expected, actual)
        super().__init__(msg)

class VersionMismatchError(LogServerError):
    pass
