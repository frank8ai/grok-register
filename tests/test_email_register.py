import unittest
from itertools import count
from unittest.mock import Mock, patch

import email_register


class CloudflareTempDomainSelectionTests(unittest.TestCase):
    def test_default_fixed_pool_is_empty(self):
        self.assertEqual(email_register.DEFAULT_CLOUDFLARE_TEMP_UNIFIED_POOL, [])

    def test_default_random_subdomain_roots_keeps_25_random_roots(self):
        self.assertEqual(
            email_register.CLOUDFLARE_TEMP_RANDOM_SUBDOMAIN_ROOTS,
            [
                "alpha.bitflow.cc.cd",
                "alpha.bitflow.ccwu.cc",
                "alpha.bitfusionpay.com",
                "alpha.flowpay.cc.cd",
                "alpha.leon08.cc.cd",
                "alpha.relayon.cc.cd",
                "alpha.yzw.io",
                "assets.bitflow.cc.cd",
                "assets.bitflow.ccwu.cc",
                "assets.flowpay.cc.cd",
                "assets.leon08.cc.cd",
                "assets.relayon.cc.cd",
                "beta.bitflow.cc.cd",
                "beta.bitflow.ccwu.cc",
                "beta.flowpay.cc.cd",
                "beta.leon08.cc.cd",
                "beta.relayon.cc.cd",
                "billing.bitpowerhub.com",
                "bitflow.cc.cd",
                "bitflow.ccwu.cc",
                "bitfusionpay.com",
                "bitpowerhub.com",
                "circle.yizhiwa.com.cn",
                "club.yizhiwa.com.cn",
                "console.yizhiwa.com.cn",
            ],
        )
        self.assertEqual(len(email_register.CLOUDFLARE_TEMP_RANDOM_SUBDOMAIN_ROOTS), 25)

    def test_excluded_domains_are_removed_from_configured_pool(self):
        self.assertFalse(
            set(email_register.CLOUDFLARE_TEMP_EXCLUDED_DOMAINS)
            & set(email_register.CLOUDFLARE_TEMP_DOMAINS)
        )

    def test_prioritizes_random_subdomains_for_preferred_root(self):
        settings = {
            "randomSubdomainDomains": [
                "alpha.finchaintalk.com",
                "beta.finchaintalk.com",
                "alpha.example.com",
            ],
            "domains": [
                "finchaintalk.com",
                "docs.finchaintalk.com",
                "example.com",
            ],
        }

        self.assertEqual(
            email_register._build_cloudflare_temp_domain_candidates(
                settings=settings,
                preferred_root_domain="finchaintalk.com",
                prefer_random_subdomain=True,
            ),
            [
                "alpha.finchaintalk.com",
                "beta.finchaintalk.com",
                "docs.finchaintalk.com",
                "finchaintalk.com",
            ],
        )

    def test_falls_back_to_root_domain_when_no_random_subdomain_matches(self):
        settings = {
            "randomSubdomainDomains": ["alpha.example.com"],
            "domains": [
                "finchaintalk.com",
                "support.example.com",
            ],
        }

        self.assertEqual(
            email_register._build_cloudflare_temp_domain_candidates(
                settings=settings,
                preferred_root_domain="finchaintalk.com",
                prefer_random_subdomain=True,
            ),
            ["finchaintalk.com"],
        )

    def test_prefers_explicit_configured_pool_over_root_filtering(self):
        settings = {
            "randomSubdomainDomains": ["alpha.example.com"],
            "domains": ["finchaintalk.com"],
        }

        self.assertEqual(
            email_register._build_cloudflare_temp_domain_candidates(
                settings=settings,
                preferred_root_domain="finchaintalk.com",
                prefer_random_subdomain=True,
                configured_domains=[
                    "beta.bitpowerhub.com",
                    "assets.finchaintalk.com",
                    "beta.bitpowerhub.com",
                ],
            ),
            ["beta.bitpowerhub.com", "assets.finchaintalk.com"],
        )

    def test_choose_domain_rotates_configured_pool_sequentially(self):
        original_index = email_register._cloudflare_temp_domain_index
        original_domains = email_register.CLOUDFLARE_TEMP_DOMAINS[:]
        try:
            email_register._cloudflare_temp_domain_index = 0
            email_register.CLOUDFLARE_TEMP_DOMAINS[:] = [
                "alpha.yzw.io",
                "support.yzw.io",
                "status.yzw.io",
            ]

            self.assertEqual(email_register._choose_cloudflare_temp_domain({}), "alpha.yzw.io")
            self.assertEqual(email_register._choose_cloudflare_temp_domain({}), "support.yzw.io")
            self.assertEqual(email_register._choose_cloudflare_temp_domain({}), "status.yzw.io")
            self.assertEqual(email_register._choose_cloudflare_temp_domain({}), "alpha.yzw.io")
        finally:
            email_register._cloudflare_temp_domain_index = original_index
            email_register.CLOUDFLARE_TEMP_DOMAINS[:] = original_domains

    def test_choose_domain_entry_uses_random_roots_when_fixed_pool_empty(self):
        original_index = email_register._cloudflare_temp_domain_index
        original_domains = email_register.CLOUDFLARE_TEMP_DOMAINS[:]
        original_roots = email_register.CLOUDFLARE_TEMP_RANDOM_SUBDOMAIN_ROOTS[:]
        try:
            email_register._cloudflare_temp_domain_index = 0
            email_register.CLOUDFLARE_TEMP_DOMAINS[:] = []
            email_register.CLOUDFLARE_TEMP_RANDOM_SUBDOMAIN_ROOTS[:] = [
                "alpha.yzw.io",
                "beta.bitpowerhub.com",
            ]

            self.assertEqual(email_register._choose_cloudflare_temp_domain_entry({}), ("alpha.yzw.io", True))
            self.assertEqual(email_register._choose_cloudflare_temp_domain_entry({}), ("beta.bitpowerhub.com", True))
            self.assertEqual(email_register._choose_cloudflare_temp_domain_entry({}), ("alpha.yzw.io", True))
        finally:
            email_register._cloudflare_temp_domain_index = original_index
            email_register.CLOUDFLARE_TEMP_DOMAINS[:] = original_domains
            email_register.CLOUDFLARE_TEMP_RANDOM_SUBDOMAIN_ROOTS[:] = original_roots

    def test_filter_supported_random_subdomain_roots_uses_service_allowlist(self):
        settings = {
            "randomSubdomainDomains": [
                "alpha.bitflow.cc.cd",
                "alpha.bitfusionpay.com",
                "alpha.yzw.io",
            ]
        }

        filtered = email_register._filter_supported_random_subdomain_roots(
            settings,
            [
                "alpha.bitflow.cc.cd",
                "assets.bitflow.cc.cd",
                "alpha.bitfusionpay.com",
                "alpha.yzw.io",
                "bitpowerhub.com",
            ],
        )

        self.assertEqual(
            filtered,
            [
                "alpha.bitflow.cc.cd",
                "alpha.bitfusionpay.com",
                "alpha.yzw.io",
            ],
        )

    def test_build_domain_entries_skips_random_roots_not_supported_by_service(self):
        original_domains = email_register.CLOUDFLARE_TEMP_DOMAINS[:]
        original_roots = email_register.CLOUDFLARE_TEMP_RANDOM_SUBDOMAIN_ROOTS[:]
        try:
            email_register.CLOUDFLARE_TEMP_DOMAINS[:] = []
            email_register.CLOUDFLARE_TEMP_RANDOM_SUBDOMAIN_ROOTS[:] = [
                "alpha.bitflow.cc.cd",
                "assets.bitflow.cc.cd",
                "alpha.bitfusionpay.com",
            ]

            entries = email_register._build_cloudflare_temp_domain_entries(
                {
                    "randomSubdomainDomains": [
                        "alpha.bitflow.cc.cd",
                        "alpha.bitfusionpay.com",
                    ]
                }
            )

            self.assertEqual(
                entries,
                [
                    ("assets.bitflow.cc.cd", False),
                    ("alpha.bitflow.cc.cd", True),
                    ("alpha.bitfusionpay.com", True),
                ],
            )
        finally:
            email_register.CLOUDFLARE_TEMP_DOMAINS[:] = original_domains
            email_register.CLOUDFLARE_TEMP_RANDOM_SUBDOMAIN_ROOTS[:] = original_roots

    def test_unsupported_random_subdomain_roots_are_downgraded_to_fixed_domains(self):
        settings = {
            "randomSubdomainDomains": [
                "alpha.bitflow.cc.cd",
                "alpha.bitfusionpay.com",
            ]
        }

        downgraded = email_register._unsupported_random_subdomain_roots(
            settings,
            [
                "alpha.bitflow.cc.cd",
                "assets.bitflow.cc.cd",
                "alpha.bitfusionpay.com",
                "circle.yizhiwa.com.cn",
            ],
        )

        self.assertEqual(
            downgraded,
            [
                "assets.bitflow.cc.cd",
                "circle.yizhiwa.com.cn",
            ],
        )


class CloudflareTempCreateEmailTests(unittest.TestCase):
    def test_create_email_disables_random_subdomain_in_admin_request(self):
        session = object()
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "address": "tester@alpha.yzw.io",
            "jwt": "jwt-token",
            "password": "",
        }

        with (
            patch.object(email_register, "_fetch_cloudflare_temp_settings", return_value={}),
            patch.object(email_register, "_choose_cloudflare_temp_domain_entry", return_value=("alpha.yzw.io", False)),
            patch.object(email_register, "_create_http_session", return_value=(session, False)),
            patch.object(email_register, "_generate_cloudflare_temp_name", return_value="tester"),
            patch.object(email_register, "_do_request", return_value=response) as request_mock,
        ):
            email_register.create_cloudflare_temp_email()

        payload = request_mock.call_args.kwargs["json"]
        self.assertEqual(payload["domain"], "alpha.yzw.io")
        self.assertFalse(payload["enableRandomSubdomain"])

    def test_create_email_enables_random_subdomain_for_random_root_entry(self):
        session = object()
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "address": "tester@random.alpha.yzw.io",
            "jwt": "jwt-token",
            "password": "",
        }

        with (
            patch.object(email_register, "_fetch_cloudflare_temp_settings", return_value={}),
            patch.object(email_register, "_choose_cloudflare_temp_domain_entry", return_value=("alpha.yzw.io", True)),
            patch.object(email_register, "_create_http_session", return_value=(session, False)),
            patch.object(email_register, "_generate_cloudflare_temp_name", return_value="tester"),
            patch.object(email_register, "_do_request", return_value=response) as request_mock,
        ):
            email_register.create_cloudflare_temp_email()

        payload = request_mock.call_args.kwargs["json"]
        self.assertEqual(payload["domain"], "alpha.yzw.io")
        self.assertTrue(payload["enableRandomSubdomain"])


class VerificationCodePollingTests(unittest.TestCase):
    def test_wait_for_verification_code_ignores_old_mail_and_uses_first_mail_after_request(self):
        with (
            patch.object(email_register, "fetch_emails", return_value=[
                {"id": "200", "createdAt": "2026-04-23T14:12:50Z"},
                {"id": "100", "createdAt": "2026-04-23T14:01:00Z"},
            ]),
            patch.object(email_register, "fetch_email_detail", side_effect=[
                {"subject": "您的 OpenAI 临时验证码", "text": "668095"},
            ]),
            patch.object(email_register.time, "sleep"),
        ):
            email_register.mark_verification_request_started("token-1", 1745417400.0)
            code = email_register.wait_for_verification_code("token-1", timeout=3)

        self.assertEqual(code, "668095")

    def test_wait_for_verification_code_falls_back_to_message_list_content_when_detail_is_empty(self):
        with (
            patch.object(email_register, "fetch_emails", return_value=[
                {
                    "id": "300",
                    "createdAt": "2026-04-23T14:12:50Z",
                    "subject": "您的 OpenAI 临时验证码",
                    "text": "输入此临时验证码以继续：668095",
                },
            ]),
            patch.object(email_register, "fetch_email_detail", return_value={}),
            patch.object(email_register.time, "sleep"),
        ):
            email_register.mark_verification_request_started("token-2", 1745417400.0)
            code = email_register.wait_for_verification_code("token-2", timeout=3)

        self.assertEqual(code, "668095")

    def test_wait_for_verification_code_retries_same_message_until_detail_is_ready(self):
        message = {
            "id": "400",
            "createdAt": "2026-04-23T14:12:50Z",
            "subject": "您的 OpenAI 临时验证码",
        }

        with (
            patch.object(email_register, "fetch_emails", side_effect=[[message], [message]]),
            patch.object(email_register, "fetch_email_detail", side_effect=[{}, {"text": "668095"}]),
            patch.object(email_register.time, "sleep"),
            patch.object(email_register.time, "time", side_effect=count()),
        ):
            code = email_register.wait_for_verification_code("token-3", timeout=5)

        self.assertEqual(code, "668095")

    def test_extract_verification_code_from_raw_mime_email(self):
        raw_email = """Subject: =?UTF-8?B?5oKo55qEIE9wZW5BSSDpqozor4HnoIE=?=
MIME-Version: 1.0
Content-Type: multipart/alternative; boundary="boundary"

--boundary
Content-Type: text/plain; charset="utf-8"
Content-Transfer-Encoding: quoted-printable

Your verification code is 668095
--boundary--
"""

        code = email_register.extract_verification_code(
            email_register._mail_content({"raw": raw_email})
        )

        self.assertEqual(code, "668095")

    def test_parse_naive_mail_timestamp_as_utc(self):
        parsed = email_register._parse_mail_timestamp("2026-04-25 10:21:31")
        expected = 1777112491.0
        self.assertEqual(parsed, expected)


if __name__ == "__main__":
    unittest.main()
