import unittest

import email_register


class CloudflareTempDomainSelectionTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
