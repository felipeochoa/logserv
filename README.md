# Safe Python Logging Across Processes

This module provides a way to handle concurrent logging from multiple
processes, which don't have to share any ancestors. In particular, it
allows for many different processes to log to the same file in an
orderly manner.

## Installation

Is in the usual manner: `python setup.py install` or any of its
derivatives (e.g., `pip`)

## Features

* Supports `AF_INET` and `AF_UNIX` sockets
* Supports defining formatters on clients
* Asynchronous server based on asyncore
* Pure python, no outside dependencies
* Drops right into existing logging framework

## Basic Usage

You first need to determine whether you are going to run a UNIX
server or an INET server, and select an address for the server. (That
is, an absolute path in the case of UNIX or a host/port combo for
INET).


You need to run the logging server(s) in a separate process or thread,
launched through the `asyncore.loop` function:

    import asyncore
    from logserv import server
    s = server.LogServer(("localhost", 9876))
    asyncore.loop(map=server.LogServer.logging_map)

In any client applications, you only need to change your use of
`RotatingFileHandler` objects for instances of `SocketForwarder` (for
INET setups) or `UnixClient` (for UNIX setups), giving these the
address of the server as an additional parameter:

    LOGGING = {"version": 1,
         # etc.
         "handlers": {
             "old_rotating_file_handler_1": {
                 "class": "logserv.client.SocketForwarder",
                 "host": "localhost",
                 "port": 9876,
                 "formatters":  # must use the built in
                                # `loggging.Formatter`,
                                # if any
                 # all the other parameters stay the same
                 "filename": ...,
                 "maxBytes": ...,
             }
         }
    }

## Using UNIX sockets:

To use the server over Unix Domain sockets, override
the `server.LogServer.socket_family` parameter in the class before
creating the first server:

    import asyncore, socket
    from logserv import server
    server.LogServer.socket_family = socket.AF_UNIX
    s = server.LogServer('/full/path/to/test.sock')
    asyncore.loop(map=server.LogServer.logging_map)

In the client, you just need to replace references
to `logserv.client.SocketForwarder` with references
to `logserv.client.UnixClient`

## Absolute vs Relative Pathnames

You don't **have** to use absolute paths to refer to file locations,
but if you don't you have to be careful to specify the `host` argument
for the client in terms of its working directory -- everything else is
relative to the server.

## TODO

* Fix client transmission of Formatter params
* expand test coverage (almost at 100%)

  - test `client.SocketForwarder.sendFormat`
  - more integration testing
  - esp. add test to ensure that a correct logrecord is unloaded properly

* expand protocol to allow client to select the handler class it wants
  to use.

## Copyright

Copyright (c) 2013 Felipe Ochoa

See LICENSE.md for details
