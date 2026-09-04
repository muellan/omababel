"""The browser impersonation layer: headers, cookies, pacing, TLS shape."""

import json
import os
import ssl
import time
import unittest

from helpers import TempEnv

from ob import http, impersonate


class FakeResponseObj:
    def __init__(self, status=200, headers=None, body=b"<html>ok</html>"):
        self.status = status
        self._headers = headers or [("Content-Type", "text/html")]
        self._body = body

    def read(self):
        return self._body

    def getheaders(self):
        return list(self._headers)


class FakeConnection:
    """Records exactly what would go on the wire."""

    last = None

    def __init__(self, host, port, secure, timeout, profile, replies):
        self.host = host
        self.port = port
        self.secure = secure
        self.timeout = timeout
        self.profile = profile
        self.replies = replies
        self.request_line = ()
        self.headers = []
        self.body = None
        FakeConnection.last = self

    def putrequest(self, method, path, skip_host=False, skip_accept_encoding=False):
        self.request_line = (method, path, skip_host, skip_accept_encoding)

    def putheader(self, key, value):
        self.headers.append((key, value))

    def endheaders(self, body=None):
        self.body = body

    def getresponse(self):
        return self.replies.pop(0) if self.replies else FakeResponseObj()

    def close(self):
        pass


class ImpersonateTest(TempEnv):
    def setUp(self):
        super().setUp()
        impersonate.reset_state()
        self._factory = impersonate.connection_factory
        os.environ["OMABABEL_HOST_INTERVAL"] = "0"
        impersonate.MIN_INTERVAL = 0.0
        self.connections = []

    def tearDown(self):
        impersonate.connection_factory = self._factory
        impersonate.reset_state()
        super().tearDown()

    def serve(self, *replies):
        queue = list(replies)

        def factory(host, port, secure, timeout, profile):
            conn = FakeConnection(host, port, secure, timeout, profile, queue)
            self.connections.append(conn)
            return conn

        impersonate.connection_factory = factory

    # ------------------------------------------------------------ headers
    def test_chrome_headers_in_chrome_order(self):
        self.serve(FakeResponseObj())
        impersonate.fetch("https://dict.leo.org/englisch-deutsch/house")
        sent = FakeConnection.last.headers
        names = [k for k, _ in sent]
        self.assertEqual(names[0], "Host")
        for expected in ("sec-ch-ua", "User-Agent", "Accept", "Sec-Fetch-Site",
                         "Accept-Encoding", "Accept-Language"):
            self.assertIn(expected, names, expected)
        # order is part of the fingerprint: the client hints lead, the fetch
        # metadata follows the user agent
        self.assertLess(names.index("sec-ch-ua"), names.index("User-Agent"))
        self.assertLess(names.index("User-Agent"), names.index("Sec-Fetch-Mode"))
        values = dict(sent)
        self.assertIn("Chrome/", values["User-Agent"])
        self.assertEqual(values["Host"], "dict.leo.org")
        self.assertIn("dict.leo.org", values["Referer"])
        # nothing we cannot decode is advertised
        self.assertNotIn("br", values["Accept-Encoding"])
        self.assertNotIn("zstd", values["Accept-Encoding"])
        # http.client must not add its own Host/Accept-Encoding on top
        self.assertEqual(FakeConnection.last.request_line[2:], (True, True))

    def test_caller_headers_replace_the_profile_ones_in_place(self):
        self.serve(FakeResponseObj())
        impersonate.fetch("https://example.org/x",
                          headers={"Accept": "application/json", "X-Extra": "1"})
        sent = FakeConnection.last.headers
        names = [k for k, _ in sent]
        self.assertEqual(dict(sent)["Accept"], "application/json")
        self.assertEqual(names.count("Accept"), 1)          # replaced, not appended
        self.assertLess(names.index("Accept"), names.index("X-Extra"))

    def test_accept_language_follows_the_search_language(self):
        self.serve(FakeResponseObj())
        impersonate.fetch("https://example.org/x", accept_language="de-DE,de;q=0.9")
        self.assertEqual(dict(FakeConnection.last.headers)["Accept-Language"], "de-DE,de;q=0.9")

    # ------------------------------------------------------------ cookies
    def test_cookies_are_kept_and_replayed_across_processes(self):
        self.serve(FakeResponseObj(headers=[("Set-Cookie", "sid=abc123; Path=/; Domain=leo.org"),
                                            ("Set-Cookie", "theme=dark")]),
                   FakeResponseObj())
        impersonate.fetch("https://dict.leo.org/a")
        impersonate.fetch("https://dict.leo.org/b")
        cookie = dict(FakeConnection.last.headers).get("Cookie", "")
        self.assertIn("sid=abc123", cookie)
        self.assertIn("theme=dark", cookie)
        # a fresh process reads them back from the cache directory
        impersonate.reset_state()
        self.serve(FakeResponseObj())
        impersonate.fetch("https://dict.leo.org/c")
        self.assertIn("sid=abc123", dict(FakeConnection.last.headers).get("Cookie", ""))

    def test_expired_and_foreign_cookies_are_not_sent(self):
        self.serve(FakeResponseObj(headers=[("Set-Cookie", "old=1; Max-Age=-10"),
                                            ("Set-Cookie", "keep=2")]),
                   FakeResponseObj(), FakeResponseObj())
        impersonate.fetch("https://dict.leo.org/a")
        impersonate.fetch("https://dict.leo.org/b")
        cookie = dict(FakeConnection.last.headers).get("Cookie", "")
        self.assertNotIn("old=", cookie)
        self.assertIn("keep=2", cookie)
        impersonate.fetch("https://www.duden.de/x")
        self.assertNotIn("keep", dict(FakeConnection.last.headers).get("Cookie", ""))

    def test_a_cookie_cannot_claim_another_domain(self):
        self.serve(FakeResponseObj(headers=[("Set-Cookie", "evil=1; Domain=example.com")]),
                   FakeResponseObj())
        impersonate.fetch("https://dict.leo.org/a")
        impersonate.fetch("https://example.com/x")
        self.assertNotIn("evil", dict(FakeConnection.last.headers).get("Cookie", ""))

    # ------------------------------------------------------------- pacing
    def test_a_refusal_pauses_the_host_for_the_next_process_too(self):
        self.serve(FakeResponseObj(status=403, body=b"nope"))
        with self.assertRaises(impersonate.ImpersonateError) as ctx:
            impersonate.fetch("https://dict.leo.org/a")
        self.assertEqual(ctx.exception.status, 403)
        state = json.loads((self.tmp / "cache" / impersonate._State.FILE).read_text(encoding="utf-8"))
        info = state["hosts"]["dict.leo.org"]
        self.assertEqual(info["refusals"], 1)
        self.assertGreater(info["blocked_until"], time.time())
        # the next attempt does not walk straight back into the block
        impersonate.reset_state()
        self.serve(FakeResponseObj())
        with self.assertRaises(impersonate.ImpersonateError) as ctx:
            impersonate.fetch("https://dict.leo.org/b", timeout=0.2)
        self.assertIn("waiting", str(ctx.exception))

    def test_retry_after_is_honoured(self):
        self.serve(FakeResponseObj(status=429, headers=[("Retry-After", "90")]))
        with self.assertRaises(impersonate.ImpersonateError):
            impersonate.fetch("https://example.org/a")
        info = impersonate.state().host("example.org")
        self.assertGreater(info["blocked_until"], time.time() + 80)

    def test_a_good_reply_clears_the_block(self):
        self.serve(FakeResponseObj(status=403), FakeResponseObj())
        with self.assertRaises(impersonate.ImpersonateError):
            impersonate.fetch("https://example.org/a")
        impersonate.state().host("example.org")["blocked_until"] = 0
        impersonate.fetch("https://example.org/b")
        self.assertEqual(impersonate.state().refusals("example.org"), 0)

    # ---------------------------------------------------------- redirects
    def test_redirects_are_followed_with_the_cookies(self):
        self.serve(FakeResponseObj(status=302, headers=[("Location", "/moved"),
                                                        ("Set-Cookie", "sid=1")]),
                   FakeResponseObj(body=b"<html>final</html>"))
        reply = impersonate.fetch("https://example.org/start")
        self.assertEqual(reply.body, b"<html>final</html>")
        self.assertEqual(FakeConnection.last.request_line[1], "/moved")
        self.assertIn("sid=1", dict(FakeConnection.last.headers).get("Cookie", ""))

    # ----------------------------------------------------------- payloads
    def test_a_post_body_is_sent_with_its_length(self):
        self.serve(FakeResponseObj())
        impersonate.fetch("https://example.org/api", data=b'{"a":1}',
                          headers={"Content-Type": "application/json"})
        self.assertEqual(FakeConnection.last.request_line[0], "POST")
        self.assertEqual(FakeConnection.last.body, b'{"a":1}')
        self.assertEqual(dict(FakeConnection.last.headers)["Content-Length"], "7")

    def test_gzip_bodies_are_decoded(self):
        import gzip as gz
        blob = gz.compress(b"<html>zipped</html>")
        self.serve(FakeResponseObj(headers=[("Content-Encoding", "gzip")], body=blob))
        self.assertEqual(impersonate.fetch("https://example.org/x").body, b"<html>zipped</html>")

    # ---------------------------------------------------------------- TLS
    def test_the_tls_context_is_chrome_shaped(self):
        ctx = impersonate.build_context(impersonate.profile_for("chrome"))
        self.assertEqual(ctx.minimum_version, ssl.TLSVersion.TLSv1_2)
        self.assertTrue(ctx.check_hostname)
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.options & ssl.OP_NO_COMPRESSION)
        names = [c["name"] for c in ctx.get_ciphers()]
        # Chrome leads with the AES-128-GCM suites, not with AES-256 the way
        # python's default list does
        first_ecdhe = next(n for n in names if n.startswith("ECDHE"))
        self.assertEqual(first_ecdhe, "ECDHE-ECDSA-AES128-GCM-SHA256")

    def test_profiles(self):
        self.assertEqual(impersonate.profile_for("").name, "chrome")
        self.assertEqual(impersonate.profile_for("firefox").name, "firefox")
        self.assertEqual(impersonate.profile_for("nonsense").name, "chrome")
        self.assertIn("Firefox/", impersonate.profile_for("firefox").ua)


class HttpIntegrationTest(TempEnv):
    """ob.http.fetch uses the browser transport by default."""

    def setUp(self):
        super().setUp()
        impersonate.reset_state()
        self._factory = impersonate.connection_factory
        impersonate.MIN_INTERVAL = 0.0
        os.environ.pop("OMABABEL_OFFLINE", None)

    def tearDown(self):
        impersonate.connection_factory = self._factory
        impersonate.reset_state()
        os.environ["OMABABEL_OFFLINE"] = "1"
        super().tearDown()

    def serve(self, *replies):
        queue = list(replies)
        impersonate.connection_factory = lambda *a: FakeConnection(*a, replies=queue)

    def test_web_sources_go_through_the_browser_transport(self):
        self.serve(FakeResponseObj(body=b"<html>hi</html>"))
        resp = http.fetch("https://dict.leo.org/x")
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.text, "<html>hi</html>")
        self.assertIn("Chrome/", dict(FakeConnection.last.headers)["User-Agent"])

    def test_a_403_becomes_a_fetch_error_with_its_status(self):
        self.serve(FakeResponseObj(status=403, body=b"blocked"))
        with self.assertRaises(http.FetchError) as ctx:
            http.fetch("https://dict.leo.org/x")
        self.assertEqual(ctx.exception.status, 403)

    def test_impersonation_can_be_switched_off(self):
        os.environ["OMABABEL_IMPERSONATE"] = "0"
        try:
            self.assertFalse(impersonate.enabled())
        finally:
            os.environ.pop("OMABABEL_IMPERSONATE", None)
        self.assertTrue(impersonate.enabled())


if __name__ == "__main__":
    unittest.main()
