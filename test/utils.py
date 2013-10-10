"""
This module provides some utilities for easier testing.
"""

from unittest import mock
import unittest
import io


class Patches:

    """
    A mixin class to handle patching starting and stopping.
    """

    TO_PATCH = {}

    def setUp(self):
        self.patchers = {}
        for name, target_vals in self.TO_PATCH.items():
            target, args, kw = self._make_patch_args(target_vals)
            self.patchers[name] = mock.patch(target, *args, **kw)
        self.mocks = {name: patcher.start()
                      for name, patcher in self.patchers.items()}
        super().setUp()

    def tearDown(self):
        for patcher in self.patchers.values():
            patcher.stop()
        super().tearDown()

    def change_patch(self, name, target, args=(), kw=None):
        """Update a patch."""
        kw = {} if kw is None else kw
        self.patchers[name].stop()
        self.patchers[name] = mock.patch(target, *args, **kw)
        self.mocks[name] = self.patchers[name].start()

    @staticmethod
    def _make_patch_args(target_vals):
        """
        Parses `target_vals` into parameters for making a new patch.

        Valid forms for a target, and their interpretation are:

        - **string** target_vals is interpreted as the target to patch
        - **2-sequence** The first item is taken to be the target, the second
          can be the keyword args if it's a dictionary or otherwise the
          positional args
        - **3-sequence** is taken to be `(target, args, kwargs)`

        """

        if not isinstance(target_vals, str):
            try:
                target, arg2 = target_vals
            except ValueError:
                target, args, kw = target_vals
            else:
                if isinstance(arg2, dict):
                    args, kw = tuple(), arg2
                else:
                    args, kw = arg2, dict()
        else:
            target, args, kw = target_vals, tuple(), dict()
        return target, args, kw


class Mopen(mock.MagicMock):

    def __init__(self,
                 side_effect=None, return_value=b'', name=None, **kwargs):
        super().__init__(side_effect=side_effect, return_value=return_value,
                         name=name, **kwargs)
        self.closed_value = None

    def __call__(self, *args, **kw):
        """
        Fake the call to open().

        Arguments are the same as for `open`, except mode 'U' is not
        supported and `Mopen` does not take a `closefd` or `opener`
        argument.

        For ease of use, all calls to a `Mopen` object are converted into
        keyword calls before updated `call_args`.

        """
        # Using this method clobbers the signature but allows
        # super().__call__ to reflect the true arguments
        def parse_args(file, mode='r', buffering=-1, encoding=None,
                       errors=None, newline=None):
            return (file, mode, buffering, encoding, errors, newline)
        file, mode, buffering, encoding, errors, newline = parse_args(*args,
                                                                      **kw)
        # Force all calls to be in keyword form
        kw.update(zip(['file', 'mode', 'buffering',
                       'encoding', 'errors', 'newline'],
                       args))
        super().__call__(**kw)

        if not isinstance(file, (str, bytes, int)):
            raise TypeError("Invalid file: %r" % file)
        if not isinstance(mode, str):
            raise TypeError("open() argument 2 must be str, not %s" %
                            type(mode))
        if not isinstance(buffering, int):
            raise TypeError("an integer is required")
        mode_set = set(mode)
        if any((not mode or  # empty mode
                not (mode_set < set('arwxbt+')),  # weird values
                len(mode) > len(mode_set),  # repeated values
                len(mode_set & set('arwx')) != 1,  # != 1 type designator
                set('bt') < mode_set)):  # both text designators
            raise ValueError("Invalid mode: %r" % mode)
        if 'b' in mode:
            if encoding is not None:
                name = "an encoding"
            elif errors is not None:
                name = "an errors"
            elif newline is not None:
                name = "a newline"
            else:
                name = ""
            if name:
                raise ValueError("binary mode doesn't take %s argument" %
                                 name)

        if mode_set & set('wx'):
            buf = io.BytesIO()
        else:
            buf = io.BytesIO(self.return_value)
        if 'a' in mode:
            buf.seek(0, io.SEEK_END)
        old_close = buf.close
        def log_then_close():
            self.closed_value = buf.getvalue()
            return old_close()
        buf.close = log_then_close
        if 'b' in mode:
            return buf
        else:
            return io.TextIOWrapper(buf, encoding, errors, newline)
