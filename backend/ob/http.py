"""The one door every remote source goes through.

:func:`fetch` keeps time-outs, headers, gzip handling and error mapping
consistent.  By default the request is sent by :mod:`ob.impersonate`, which
speaks HTTP the way a browser does -- Chrome's header set in Chrome's
order, a Chrome-shaped TLS handshake, cookies kept between runs and one
request per host at a time -- because the scraped sites answer 403 to
anything that obviously is not a browser.  ``OMABABEL_IMPERSONATE=0`` falls
back to plain urllib, and ``OMABABEL_OFFLINE=1`` turns every network access
into a :class:`FetchError`, which keeps the test suite hermetic.
"""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, Optional, Union

from . import impersonate

DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)

DEFAULT_TIMEOUT = float(os.environ.get("OMABABEL_TIMEOUT", "12"))


class FetchError(Exception):
    """Network / HTTP failure.  ``status`` is the HTTP code when known.

    The URL is redacted here rather than at each raise site: a service that
    only takes its key in the query string would otherwise put that key into
    a message the panel shows and the CLI prints.
    """

    def __init__(self, message: str, status: Optional[int] = None, url: str = ""):
        safe = impersonate.redact_url(url) if url else ""
        text = str(message)
        if url and safe != url:
            text = text.replace(url, safe)
        super().__init__(text)
        self.status = status
        self.url = safe


class Response:
    def __init__(self, url: str, status: int, headers: Dict[str, str], body: bytes):
        self.url = url
        self.status = status
        self.headers = headers
        self.body = body

    @property
    def text(self) -> str:
        charset = "utf-8"
        ctype = self.headers.get("content-type", "")
        if "charset=" in ctype:
            charset = ctype.split("charset=")[-1].split(";")[0].strip() or "utf-8"
        try:
            return self.body.decode(charset, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.text)


class _SafeRedirects(urllib.request.HTTPRedirectHandler):
    """urllib follows redirects by replaying the original request.

    That includes the Authorization or X-Api-Key header, so a redirect to
    another origin would hand our credentials to whoever the remote party
    names.  Every hop is checked (`impersonate.check_redirect`) and anything
    that authenticates us is dropped when the origin changes.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        sensitive = {k: v for k, v in req.header_items() if impersonate.is_sensitive(k)}
        try:
            target = impersonate.check_redirect(req.full_url, newurl, sensitive)
        except impersonate.ImpersonateError as e:
            raise urllib.error.HTTPError(req.full_url, code, str(e), headers, fp)
        new = super().redirect_request(req, fp, code, msg, headers, target)
        if new is not None and not impersonate.same_origin(req.full_url, target):
            for name in list(new.headers):
                if impersonate.is_sensitive(name):
                    del new.headers[name]
            for name in list(getattr(new, "unredirected_hdrs", {})):
                if impersonate.is_sensitive(name):
                    del new.unredirected_hdrs[name]
        return new


_opener = urllib.request.build_opener(_SafeRedirects())


def _decompress(body: bytes, encoding: str) -> bytes:
    """Bounded inflation – see ob.impersonate._decompress."""
    return impersonate._decompress(body, encoding)


def fetch(
    url: str,
    *,
    data: Union[bytes, str, dict, None] = None,
    headers: Optional[Dict[str, str]] = None,
    method: Optional[str] = None,
    timeout: Optional[float] = None,
    json_body: Optional[object] = None,
    accept_language: str = "en,de;q=0.8",
) -> Response:
    if os.environ.get("OMABABEL_OFFLINE"):
        raise FetchError("offline mode (OMABABEL_OFFLINE is set)", url=url)
    # A credential belongs on an encrypted connection or nowhere.
    try:
        impersonate.require_secure(url, headers)
    except impersonate.ImpersonateError as e:
        raise FetchError(str(e), url=url)

    hdrs = {
        "User-Agent": DEFAULT_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": accept_language,
        "Accept-Encoding": "gzip, deflate",
    }
    if headers:
        hdrs.update(headers)

    payload: Optional[bytes] = None
    if json_body is not None:
        payload = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    elif isinstance(data, dict):
        payload = urllib.parse.urlencode(data).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
    elif isinstance(data, str):
        payload = data.encode("utf-8")
    elif isinstance(data, bytes):
        payload = data

    if impersonate.enabled():
        return _fetch_as_browser(url, payload, headers or {}, method,
                                 timeout or DEFAULT_TIMEOUT, accept_language)

    req = urllib.request.Request(url, data=payload, headers=hdrs, method=method)
    try:
        with _opener.open(req, timeout=timeout or DEFAULT_TIMEOUT) as resp:
            raw = impersonate.read_capped(resp)
            rh = {k.lower(): v for k, v in resp.headers.items()}
            body = _decompress(raw, rh.get("content-encoding", ""))
            return Response(resp.geturl(), resp.status, rh, body)
    except impersonate.TooLarge as e:
        raise FetchError(f"{url}: {e}", url=url)
    except urllib.error.HTTPError as e:
        try:
            raw = impersonate.read_capped(e, impersonate.MAX_ERROR_BYTES)
            rh = {k.lower(): v for k, v in e.headers.items()}
            body = _decompress(raw, rh.get("content-encoding", ""))
        except Exception:  # pragma: no cover - defensive
            body, rh = b"", {}
        err = FetchError(f"HTTP {e.code} for {url}", status=e.code, url=url)
        err.body = body[:impersonate.MAX_ERROR_BYTES]  # type: ignore[attr-defined]
        err.headers = rh  # type: ignore[attr-defined]
        raise err
    except urllib.error.URLError as e:
        raise FetchError(f"{e.reason} ({url})", url=url)
    except socket.timeout:
        raise FetchError(f"timeout ({url})", url=url)
    except (ConnectionError, OSError) as e:
        raise FetchError(f"{e} ({url})", url=url)


def _fetch_as_browser(url: str, payload: Optional[bytes], headers: Dict[str, str],
                      method: Optional[str], timeout: float, accept_language: str) -> Response:
    """Send through ob.impersonate, escalating to a real Chrome handshake
    (curl-impersonate) for a host that refuses us anyway."""
    host = urllib.parse.urlsplit(url).hostname or ""
    attempts = ["python"]
    if impersonate.state().refusals(host) and impersonate.impersonate_binary():
        attempts.insert(0, "binary")
    elif impersonate.impersonate_binary():
        attempts.append("binary")
    last: Optional[impersonate.ImpersonateError] = None
    for how in attempts:
        try:
            if how == "binary":
                reply = impersonate.fetch_with_binary(url, headers=headers, data=payload,
                                                      method=method, timeout=timeout)
            else:
                reply = impersonate.fetch(url, data=payload, headers=headers, method=method,
                                          timeout=timeout, accept_language=accept_language)
            return Response(reply.url, reply.status,
                            {k.lower(): v for k, v in reply.headers}, reply.body)
        except impersonate.ImpersonateError as e:
            last = e
            # Only a refusal is worth a second identity; a 404 stays a 404.
            if e.status not in (403, 429, 503, None):
                break
    err = FetchError(str(last), status=getattr(last, "status", None), url=url)
    err.body = getattr(last, "body", b"")            # type: ignore[attr-defined]
    err.headers = {k.lower(): v for k, v in getattr(last, "headers", [])}   # type: ignore[attr-defined]
    raise err


def quote(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def fill_template(template: str, **values: str) -> str:
    """Replace ``{word}``/``{from}``/``{to}`` placeholders, URL-encoded."""
    out = template
    for key, val in values.items():
        out = out.replace("{" + key + "}", quote(val))
    return out
