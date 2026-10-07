import os
import pytest
import requests

WOLFRAM_LLM_APP_ID = os.getenv("WOLFRAM_LLM_APP_ID")


@pytest.mark.skipif(
    not WOLFRAM_LLM_APP_ID, reason="No WOLFRAM_LLM_APP_ID set in environment."
)
def test_wolframalpha_llm_api():
    """
    Test the WolframAlpha /api/v1/llm-api endpoint with a simple query.
    Skips if WOLFRAM_LLM_APP_ID is not set.
    """
    params = {"input": "2+2", "appid": WOLFRAM_LLM_APP_ID}
    resp = requests.get("https://www.wolframalpha.com/api/v1/llm-api", params=params)
    assert resp.status_code == 200
    assert resp.text.strip() != ""
    print("WolframAlpha result for '2+2':", resp.text.strip())
