import unittest

from bugbundle.redaction import RedactionRules, Redactor


class TestUrlRedaction(unittest.TestCase):
    def setUp(self):
        self.r = Redactor()

    def test_sensitive_params_redacted_others_kept(self):
        url = "http://localhost:8000/api?token=sekrit123&debug=1&Email=a%40b.com"
        out = self.r.redact_url(url)
        self.assertIn("token=%5BREDACTED%5D", out.replace("[", "%5B").replace("]", "%5D"))
        self.assertIn("debug=1", out)
        self.assertNotIn("sekrit123", out)
        self.assertNotIn("a%40b.com", out.lower())

    def test_url_without_query_unchanged(self):
        self.assertEqual(self.r.redact_url("http://x.test/path"), "http://x.test/path")

    def test_extra_param_names(self):
        r = Redactor(RedactionRules(extra_param_names=["tracking_id"]))
        out = r.redact_url("http://x.test/?tracking_id=abc123&q=hello")
        self.assertNotIn("abc123", out)
        self.assertIn("q=hello", out)

    def test_non_url_garbage_does_not_crash(self):
        # urlsplit never really fails, but text redaction is the fallback path.
        self.assertIsInstance(self.r.redact_url("not a url at all"), str)


class TestTextRedaction(unittest.TestCase):
    def setUp(self):
        self.r = Redactor()

    def test_email(self):
        out = self.r.redact_text("sync failed for alice@example.com, retry")
        self.assertNotIn("alice@example.com", out)
        self.assertIn("[REDACTED_EMAIL]", out)

    def test_email_can_be_disabled(self):
        r = Redactor(RedactionRules(redact_emails=False))
        self.assertIn("alice@example.com", r.redact_text("mail alice@example.com"))

    def test_jwt(self):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhbGljZSJ9.dummysignaturevalue"
        out = self.r.redact_text(f"got token {jwt} ok")
        self.assertNotIn("dummysignaturevalue", out)
        self.assertIn("[REDACTED_TOKEN]", out)

    def test_bearer_header(self):
        out = self.r.redact_text("Authorization: Bearer abcdef1234567890XYZ==")
        self.assertNotIn("abcdef1234567890XYZ==", out)

    def test_assignment_token(self):
        out = self.r.redact_text("config: api_key=sk-live-9876543210abcdef")
        self.assertNotIn("sk-live-9876543210abcdef", out)
        self.assertIn("api_key=", out)

    def test_short_values_not_eaten(self):
        # short/common words must survive token redaction
        out = self.r.redact_text("token=abc is too short to be a secret")
        self.assertIn("token=abc", out)


class TestFieldRedaction(unittest.TestCase):
    def test_password_always_redacted(self):
        r = Redactor(RedactionRules(sensitive_fields=set()))  # user empties the list
        self.assertEqual(r.redact_field("password", "hunter2"), "[REDACTED]")

    def test_hidden_and_normal_fields(self):
        r = Redactor()
        self.assertEqual(r.redact_field("csrf_token", "x"), "x")  # not in default list
        out = r.redact_field("comment", "reach me at bob@example.org")
        self.assertNotIn("bob@example.org", out)


class TestDomRedaction(unittest.TestCase):
    HTML = (
        '<html><body>'
        '<div id="account-panel">Logged in as alice@example.com, token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhIn0.c2lnbmF0dXJl</div>'
        '<p class="promo big">Buy now, contact bob@example.org</p>'
        '<input type="password" name="password" value="hunter2">'
        '<input type="hidden" name="csrf" value="abcdef123456">'
        '<footer>plain footer</footer>'
        '</body></html>'
    )

    def test_id_and_class_regions(self):
        r = Redactor(RedactionRules(dom_selectors=["#account-panel", ".promo"]))
        out = r.redact_dom(self.HTML)
        self.assertIn("[REDACTED REGION: #account-panel]", out)
        self.assertIn("[REDACTED REGION: .promo]", out)
        self.assertNotIn("alice@example.com", out)
        self.assertNotIn("bob@example.org", out)
        self.assertIn("plain footer", out)

    def test_tag_region(self):
        r = Redactor(RedactionRules(dom_selectors=["footer"]))
        out = r.redact_dom(self.HTML)
        self.assertIn("[REDACTED REGION: footer]", out)
        self.assertNotIn("plain footer", out)

    def test_password_and_hidden_values_stripped_even_without_regions(self):
        r = Redactor()  # no selectors configured
        out = r.redact_dom(self.HTML)
        self.assertNotIn("hunter2", out)
        self.assertNotIn('value="abcdef123456"', out)

    def test_bad_selector_raises(self):
        r = Redactor(RedactionRules(dom_selectors=["div > span:nth-child(2)"]))
        with self.assertRaises(ValueError):
            r.redact_dom(self.HTML)


if __name__ == "__main__":
    unittest.main()
