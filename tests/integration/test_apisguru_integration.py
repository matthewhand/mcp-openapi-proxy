import os
import pytest
import requests


@pytest.mark.integration
class TestApisGuruIntegration:
    @classmethod
    def setup_class(cls):
        # Set up environment to use the APIs.guru config
        os.environ["OPENAPI_SPEC_URL"] = (
            "https://raw.githubusercontent.com/APIs-guru/openapi-directory/refs/heads/main/APIs/apis.guru/2.2.0/openapi.yaml"
        )
        cls.base_url = "https://api.apis.guru/v2"

    def test_list_apis(self):
        """Test the /list.json endpoint (operationId: listAPIs)"""
        resp = requests.get(f"{self.base_url}/list.json")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert len(data) > 0  # Should have at least one API provider
        assert "1forge.com" in data

    def test_get_metrics(self):
        """Test the /metrics.json endpoint (operationId: getMetrics)"""
        resp = requests.get(f"{self.base_url}/metrics.json")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert "numAPIs" in data or "numSpecs" in data

    def test_get_providers(self):
        """Test the /providers.json endpoint (operationId: getProviders)"""
        resp = requests.get(f"{self.base_url}/providers.json")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert "data" in data
