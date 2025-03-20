import os
import unittest
from mcp_openapi_proxy.utils import get_additional_headers

class TestGetAdditionalHeaders(unittest.TestCase):
    def setUp(self):
        # Backup the current environment variable
        self.original_extra_headers = os.environ.get("EXTRA_HEADERS")
        # Ensure EXTRA_HEADERS is unset for a clean slate
        if "EXTRA_HEADERS" in os.environ:
            del os.environ["EXTRA_HEADERS"]

    def tearDown(self):
        # Restore the original environment variable
        if self.original_extra_headers is not None:
            os.environ["EXTRA_HEADERS"] = self.original_extra_headers
        elif "EXTRA_HEADERS" in os.environ:
            del os.environ["EXTRA_HEADERS"]

    def test_empty_headers(self):
        # When EXTRA_HEADERS is not set, should return an empty dictionary
        self.assertEqual(get_additional_headers(), {})

    def test_single_header(self):
        # Test with a single header in EXTRA_HEADERS
        os.environ["EXTRA_HEADERS"] = "Notion-Version: 2022-06-28"
        expected = {"Notion-Version": "2022-06-28"}
        self.assertEqual(get_additional_headers(), expected)

    def test_multiple_headers(self):
        # Test with multiple headers separated by newlines
        os.environ["EXTRA_HEADERS"] = "Header1: Value1\nHeader2: Value2\nHeader3: Value3"
        expected = {
            "Header1": "Value1",
            "Header2": "Value2",
            "Header3": "Value3"
        }
        self.assertEqual(get_additional_headers(), expected)

    def test_invalid_line(self):
        # Test lines without a colon are ignored and only valid header lines are processed
        os.environ["EXTRA_HEADERS"] = "InvalidHeader\nHeader: Valid"
        expected = {"Header": "Valid"}
        self.assertEqual(get_additional_headers(), expected)

if __name__ == "__main__":
    unittest.main()
