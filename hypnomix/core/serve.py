"""The small web servers HypnoMix runs on this computer (the app, the review page).

    LocalServer(("127.0.0.1", port), handler)    a ThreadingHTTPServer that refuses a port someone else already holds

On macOS and Linux the usual "reuse the address" option is safe (it only lets a server start again while the old
connections are closing, and a second bind to a port in use still fails). On Windows the same option lets a second
program take a port that is in use, so there the option is left off: a plain bind to a port in use fails, and a restart
may need a short wait while old connections close.
"""
import os
from http.server import ThreadingHTTPServer


def _windows():
    return os.name == "nt"


class LocalServer(ThreadingHTTPServer):
    def __init__(self, *args, **kw):
        self.allow_reuse_address = not _windows()        # read by server_bind, which the base class calls from here
        super().__init__(*args, **kw)
