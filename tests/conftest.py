import os
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
    # Reset shared catalog state without invalidating functions imported by
    # test modules during collection. Deleting sys.modules left stale function
    # globals and could silently pass by exercising the old dummy-spec fallback.
    from mcp_openapi_proxy import server_fastmcp as fast
    fast.spec = None
    fast._FUNCTION_OPERATIONS.clear()
    fast._SPEC_SNAPSHOTS.clear()
    fast._OPERATION_SNAPSHOTS.clear()
    yield env_key
    # Restore original env
    os.environ.clear()
    os.environ.update(original_env)
