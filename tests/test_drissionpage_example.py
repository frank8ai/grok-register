import unittest
from unittest.mock import Mock, patch

import DrissionPage_example as script


class BrowserLifecycleTests(unittest.TestCase):
    def tearDown(self):
        script.browser = None
        script.page = None
        script._chrome_temp_dir = ""

    def test_restart_browser_always_restarts_cleanly(self):
        stale_page = Mock()
        script.page = stale_page
        script.browser = Mock()

        with (
            patch.object(script, "stop_browser") as stop_mock,
            patch.object(script, "start_browser") as start_mock,
            patch.object(script.time, "sleep") as sleep_mock,
        ):
            script.restart_browser()

        stop_mock.assert_called_once_with()
        start_mock.assert_called_once_with()
        sleep_mock.assert_called_once_with(0.5)
        stale_page.run_js.assert_not_called()

    def test_start_browser_retries_with_fresh_options_after_failed_connect(self):
        fake_page = Mock(name="page")
        fake_browser = Mock(name="browser")
        fake_browser.user_data_path = r"C:\temp\profile"
        fake_browser.get_tabs.return_value = []
        fake_browser.new_tab.return_value = fake_page

        with (
            patch.object(script, "create_browser_options", side_effect=["opts-1", "opts-2"]) as options_mock,
            patch.object(script, "stop_browser") as stop_mock,
            patch.object(script.time, "sleep") as sleep_mock,
            patch.object(script, "Chromium", side_effect=[Exception("disconnected"), fake_browser]) as chromium_mock,
        ):
            browser, page = script.start_browser()

        self.assertIs(browser, fake_browser)
        self.assertIs(page, fake_page)
        self.assertEqual(script._chrome_temp_dir, r"C:\temp\profile")
        self.assertEqual(options_mock.call_count, 2)
        self.assertEqual(chromium_mock.call_args_list[0].args, ("opts-1",))
        self.assertEqual(chromium_mock.call_args_list[1].args, ("opts-2",))
        stop_mock.assert_called_once_with()
        sleep_mock.assert_called_once_with(0.5)


if __name__ == "__main__":
    unittest.main()
