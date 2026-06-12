"""
Unit tests for the Glama deployment artifacts: Dockerfile and glama.json.

Glama's MCP directory (https://glama.ai/mcp/servers) requires a Dockerfile at
the repository root so the server can be built and hosted, and a glama.json
manifest declaring the maintainers. These tests validate the static contract
without building any image.
"""

import json
import os
import re

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DOCKERFILE_PATH = os.path.join(REPO_ROOT, "Dockerfile")
GLAMA_JSON_PATH = os.path.join(REPO_ROOT, "glama.json")
PYPROJECT_PATH = os.path.join(REPO_ROOT, "pyproject.toml")

PACKAGE_NAME = "mcp-openapi-proxy"


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def test_dockerfile_exists_at_repo_root():
    assert os.path.isfile(DOCKERFILE_PATH), "Dockerfile must exist at the repository root for the Glama listing"


def test_dockerfile_uses_python_slim_base():
    content = _read(DOCKERFILE_PATH)
    assert re.search(r"^FROM\s+python:3\.\d+-slim", content, re.MULTILINE), (
        "Dockerfile should be based on a python slim image"
    )


def test_dockerfile_entrypoint_is_console_script():
    content = _read(DOCKERFILE_PATH)
    match = re.search(r"^ENTRYPOINT\s+(.+)$", content, re.MULTILINE)
    assert match, "Dockerfile must declare an ENTRYPOINT"
    assert PACKAGE_NAME in match.group(1), (
        f"ENTRYPOINT must invoke the {PACKAGE_NAME!r} console script"
    )


def test_dockerfile_installs_package():
    content = _read(DOCKERFILE_PATH)
    assert re.search(r"pip\s+install\b", content), "Dockerfile must pip install the package"


def test_dockerfile_documents_spec_url_env():
    content = _read(DOCKERFILE_PATH)
    assert "OPENAPI_SPEC_URL" in content, (
        "Dockerfile should reference the OPENAPI_SPEC_URL environment variable"
    )


def test_dockerfile_entrypoint_matches_pyproject_script():
    pyproject = _read(PYPROJECT_PATH)
    assert re.search(
        rf"^{re.escape(PACKAGE_NAME)}\s*=", pyproject, re.MULTILINE
    ), f"pyproject.toml must define the {PACKAGE_NAME!r} console script"
    assert f'name = "{PACKAGE_NAME}"' in pyproject


def test_glama_manifest_exists_and_is_valid():
    assert os.path.isfile(GLAMA_JSON_PATH), "glama.json must exist at the repository root"
    manifest = json.loads(_read(GLAMA_JSON_PATH))
    assert manifest.get("$schema") == "https://glama.ai/mcp/schemas/server.json"
    maintainers = manifest.get("maintainers")
    assert isinstance(maintainers, list) and "matthewhand" in maintainers
