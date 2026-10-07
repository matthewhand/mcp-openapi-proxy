import requests


def test_petstore_api_exists():
    """
    Integration test to verify that the Petstore API is up and running.
    It calls the /pet/findByStatus endpoint and asserts that the response is successful.
    """
    base_url = "http://petstore.swagger.io/v2"
    endpoint = "/pet/findByStatus"
    params = {"status": "available"}
    response = requests.get(base_url + endpoint, params=params)
    assert (
        response.status_code == 200
    ), f"Expected status code 200 but got {response.status_code}. Response text: {response.text}"
    try:
        data = response.json()
    except ValueError:
        assert False, "Response is not valid JSON"
    assert isinstance(data, list), "Expected the response to be a list of pets"


if __name__ == "__main__":
    test_petstore_api_exists()
    print("Petstore API exists and returned valid JSON data.")
