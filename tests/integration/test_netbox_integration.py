import os
import pytest
import requests


@pytest.mark.integration
class TestNetboxIntegration:
    @classmethod
    def setup_class(cls):
        # Only run tests if NETBOX_API_KEY and SERVER_URL_OVERRIDE are set and not placeholders
        cls.token = os.environ.get("NETBOX_API_KEY")
        cls.base_url = os.environ.get(
            "SERVER_URL_OVERRIDE", "http://localhost:8000/api"
        )
        if not cls.token or "your_key" in cls.token.lower():
            pytest.skip("No valid NETBOX_API_KEY set in environment.")
        if not cls.base_url or "localhost" in cls.base_url:
            pytest.skip("No valid SERVER_URL_OVERRIDE set for Netbox integration.")
        cls.headers = {"Authorization": f"Token {cls.token}"}

    def test_devices_list(self):
        """Test the /dcim/devices/ endpoint (list devices)"""
        resp = requests.get(f"{self.base_url}/dcim/devices/", headers=self.headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert "results" in data
        assert isinstance(data["results"], list)

    def test_ip_addresses_list(self):
        """Test the /ipam/ip-addresses/ endpoint (list IP addresses)"""
        resp = requests.get(f"{self.base_url}/ipam/ip-addresses/", headers=self.headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert "results" in data
        assert isinstance(data["results"], list)
