import os
import importlib
import pytest
import sys
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)
import hashlib
from dotenv import load_dotenv

# Load .env once at module level
load_dotenv()

@pytest.fixture(scope="function", autouse=True)
def reset_env_and_module(request):
    # Preserve original env, only tweak OPENAPI_SPEC_URL-related keys
    original_env = os.environ.copy()
    test_name = request.node.name
    env_key = f"OPENAPI_SPEC_URL_{hashlib.md5(test_name.encode()).hexdigest()[:8]}"
    # Clear only OPENAPI_SPEC_URL-related keys
    for key in list(os.environ.keys()):
        if key.startswith("OPENAPI_SPEC_URL"):
            del os.environ[key]
    os.environ["DEBUG"] = "true"
    # Reload the existing module object so functions imported by test modules
    # continue to share the patched module globals.
    if 'mcp_openapi_proxy.server_fastmcp' in sys.modules:
        importlib.reload(sys.modules['mcp_openapi_proxy.server_fastmcp'])
    else:
        import mcp_openapi_proxy.server_fastmcp
    yield env_key
    # Restore original env
    os.environ.clear()
    os.environ.update(original_env)
