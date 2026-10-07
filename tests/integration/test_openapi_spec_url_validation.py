"""
Integration test to validate all OpenAPI spec URLs in example configs using the same curl-based logic as production.
"""

import os
import glob
import json
import pytest
import subprocess


def extract_spec_urls(config_path):
    """Extract all OpenAPI spec URLs from a config file (handles nested mcpServers)."""
    with open(config_path, "r") as f:
        config = json.load(f)
    urls = set()

    def find_urls(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "mcpServers" and isinstance(v, list):
                    for server in v:
                        if isinstance(server, dict) and "OPENAPI_SPEC_URL" in server:
                            urls.add(server["OPENAPI_SPEC_URL"])
                else:
                    find_urls(v)
        elif isinstance(obj, list):
            for item in obj:
                find_urls(item)

    find_urls(config)
    return list(urls)


EXAMPLES_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../examples")
)
EXAMPLE_CONFIGS = glob.glob(os.path.join(EXAMPLES_DIR, "*.json"))


@pytest.mark.parametrize("config_path", EXAMPLE_CONFIGS)
def test_example_config_openapi_urls_reachable(config_path):
    urls = extract_spec_urls(config_path)
    for url in urls:
        if url.startswith("file://"):
            continue  # skip local files
        curl_cmd = ["curl", "-I", "--max-time", "15", url]
        result = subprocess.run(curl_cmd, capture_output=True, text=True)
        status_line = (
            result.stdout.splitlines()[0] if result.stdout else result.stderr.strip()
        )
        assert (
            result.returncode == 0 and "200" in status_line
        ), f"URL {url} not reachable: {status_line}"
