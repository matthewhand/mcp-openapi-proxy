import os
from dotenv import load_dotenv

load_dotenv()
import json
import pytest
import logging
import requests

logger = logging.getLogger(__name__)


@pytest.mark.skipif(
    "OPENWEBUI_API_KEY" not in os.environ
    or os.environ["OPENWEBUI_API_KEY"] == "test_token_placeholder",
    reason="Valid OPENWEBUI_API_KEY not provided for integration tests",
)
@pytest.mark.parametrize(
    "test_mode,params",
    [
        (
            "simple",
            {
                "model": os.environ.get("OPENWEBUI_MODEL", "litellm.llama3.2"),
                "messages": [
                    {"role": "user", "content": "Hello, what's the meaning of life?"}
                ],
            },
        ),
        (
            "complex",
            {
                "model": os.environ.get("OPENWEBUI_MODEL", "litellm.llama3.2"),
                "messages": [
                    {
                        "role": "user",
                        "content": "Explain quantum computing in 3 paragraphs",
                        "name": "physics_student",
                    },
                    {"role": "system", "content": "You are a physics professor"},
                ],
                "temperature": 0.7,
                "max_tokens": 300,
                "top_p": 0.9,
                "stream": True,
            },
        ),
    ],
)
def test_chat_completion_modes(test_mode, params, reset_env_and_module):
    env_key = reset_env_and_module
    api_key = os.environ.get("OPENWEBUI_API_KEY", "test_token_placeholder")
    os.environ["API_KEY"] = api_key
    spec_url = "http://localhost:3000/openapi.json"
    base_url = "http://localhost:3000/"  # Trailing slash
    os.environ[env_key] = spec_url
    os.environ["SERVER_URL_OVERRIDE"] = base_url

    # Check if OpenWebUI is up
    try:
        response = requests.get(spec_url, timeout=2)
        response.raise_for_status()
        spec = response.json()
        logger.debug(f"Raw OpenWebUI spec: {json.dumps(spec, indent=2)}")
    except (requests.RequestException, json.JSONDecodeError) as e:
        pytest.skip(f"OpenWebUI not available at {spec_url}: {e}")

    # Check available models from /api/models
    try:
        headers = {"Authorization": f"Bearer {api_key}"}
        models_response = requests.get(
            f"{base_url}api/models", headers=headers, timeout=2
        )
        models_response.raise_for_status()
        models_data = models_response.json()
        logger.debug(f"Raw models response: {json.dumps(models_data, indent=2)}")

        # Extract model names - adjust based on actual response structure
        if isinstance(models_data, list):
            model_names = models_data
        elif "data" in models_data:
            model_names = [m.get("id", m.get("name", "")) for m in models_data["data"]]
        else:
            model_names = [models_data.get("id", models_data.get("name", ""))]

        logger.debug(f"Available models: {model_names}")
        if params["model"] not in model_names:
            pytest.skip(f"Model {params['model']} not available in {model_names}")
    except (requests.RequestException, json.JSONDecodeError) as e:
        pytest.skip(f"Failed to fetch models from {base_url}api/models: {e}")

    from mcp_openapi_proxy.server_fastmcp import list_functions, call_function

    logger.debug(f"Env before list_functions: {env_key}={os.environ.get(env_key)}")
    tools_json = list_functions(env_key=env_key)
    tools = json.loads(tools_json)
    print(f"DEBUG: OpenWebUI tools: {tools_json}")
    assert len(tools) > 0, f"No tools generated from OpenWebUI spec: {tools_json}"

    logger.debug(f"Filtering tools for chat completions: {[t['name'] for t in tools]}")
    chat_completion_func = next(
        (
            t["name"]
            for t in tools
            if "/api/chat/completions" in t.get("original_name", "").lower()
            and t.get("method", "").upper() == "POST"
        ),
        None,
    )
    assert (
        chat_completion_func
    ), f"No POST chat/completions function found in tools: {tools_json}"

    logger.info(
        f"Calling chat completion function: {chat_completion_func} in {test_mode} mode"
    )
    response_json = call_function(
        function_name=chat_completion_func, parameters=params, env_key=env_key
    )
    response = json.loads(response_json)

    if test_mode == "simple":
        assert "choices" in response, "Simple mode response missing 'choices'"
        assert len(response["choices"]) > 0, "Simple mode response has no choices"
        assert (
            "message" in response["choices"][0]
        ), "Simple mode response choice missing 'message'"
        assert (
            "content" in response["choices"][0]["message"]
        ), "Simple mode response choice missing 'content'"
    elif test_mode == "complex":
        assert isinstance(
            response, dict
        ), "Complex mode (streaming) response should be a dict"
        assert (
            "error" not in response
        ), f"Complex mode response contains error: {response.get('error')}"
