import requests


def test_petstore_openapi_access():
    """
    Integration test to verify that the Petstore OpenAPI JSON is accessible and contains expected keys.
    """
    url = "https://raw.githubusercontent.com/seriousme/fastify-openapi-glue/refs/heads/master/examples/petstore/petstore-openapi.v3.json"
    response = requests.get(url)
    assert (
        response.status_code == 200
    ), f"Failed to fetch the specification. HTTP status code: {response.status_code}"
    try:
        data = response.json()
    except ValueError:
        assert False, "Response is not valid JSON"
    for key in ["openapi", "info", "paths"]:
        assert key in data, f"Key '{key}' not found in the specification"
