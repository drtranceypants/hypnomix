"""HTTP to this computer only: never through a proxy, never to another host, never followed to one.

The app talks to the HypnoMix engine (its MCP surface, http://127.0.0.1:PORT/mcp) and to a HypnoMix Studio window
on the same computer. `urllib.request.urlopen` would send those calls to the HTTP proxy named in the environment
(http_proxy, or the system's proxy on a Mac) and with them the session's paths and every tool argument. Everything
that calls the engine uses `urlopen` from here instead:

    from hypnomix.core import loopback
    with loopback.urlopen(request, timeout=8) as r: ...

A URL that is not on 127.0.0.1, localhost or [::1] is refused (ValueError) and a redirect is not followed (the
3xx answer is raised as an HTTPError, as any other error answer).
"""
import urllib.parse
import urllib.request

HOSTS = ("127.0.0.1", "localhost", "::1")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)


def is_loopback(url):
    try:
        return (urllib.parse.urlparse(str(url)).hostname or "").lower() in HOSTS
    except ValueError:
        return False


def urlopen(req, timeout=None):
    """urllib.request.urlopen for a loopback URL: no proxy, no redirects, nothing off this computer."""
    url = req.full_url if hasattr(req, "full_url") else str(req)
    if not is_loopback(url):
        raise ValueError(f"only this computer is called here: {url}")
    return _OPENER.open(req, timeout=timeout)
