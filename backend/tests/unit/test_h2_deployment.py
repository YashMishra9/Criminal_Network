"""Tests for Task H2: Deployment Scaffolding.

These are static/structural tests — they verify the deployment config files
exist, are well-formed, and enforce Contract Invariant 7
(LIVE_ADAPTER_ENABLED=false by default) without requiring a live Docker
daemon or external platform.

The actual end-to-end smoke test (Docker build + container start) lives in
scripts/smoke_test_deploy.py and is run as a manual / CI step.

Tests (per H2 §12/§13):
  - backend/Dockerfile exists and is syntactically parseable.
  - render.yaml exists and contains required service definition.
  - railway.toml exists and references the correct Dockerfile path.
  - frontend/vercel.json exists and is valid JSON.
  - README.md exists and contains the deployment section.
  - Contract Invariant 7 (DOC3): LIVE_ADAPTER_ENABLED=false is present in
    every committed deployment config file.
  - No fourth platform or undocumented infrastructure is introduced
    (H2 §17 constraint).
"""

import json
import os
import re
import tomllib
from pathlib import Path

import pytest
import yaml

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_DIR = REPO_ROOT / "backend"
FRONTEND_DIR = REPO_ROOT / "frontend"
SCRIPTS_DIR = REPO_ROOT / "scripts"


def _path(relative: str) -> Path:
    return REPO_ROOT / relative


# ===========================================================================
# Dockerfile
# ===========================================================================

def test_dockerfile_exists():
    assert _path("backend/Dockerfile").exists(), "backend/Dockerfile must exist (H2 §9)"


def test_dockerfile_uses_python_base_image():
    content = _path("backend/Dockerfile").read_text(encoding="utf-8")
    assert "FROM python:" in content, "Dockerfile must use a Python base image"


def test_dockerfile_sets_live_adapter_enabled_false():
    """Contract Invariant 7: Dockerfile must set LIVE_ADAPTER_ENABLED=false as default."""
    content = _path("backend/Dockerfile").read_text(encoding="utf-8")
    # Must contain the ENV directive setting it to false
    assert re.search(r"ENV\s+LIVE_ADAPTER_ENABLED\s*=?\s*false", content, re.IGNORECASE), (
        "backend/Dockerfile must set ENV LIVE_ADAPTER_ENABLED=false "
        "(Contract Invariant 7 — DOC3)"
    )


def test_dockerfile_binds_to_port_env_var():
    """uvicorn must bind to $PORT, not a hardcoded port (Render/Railway standard)."""
    content = _path("backend/Dockerfile").read_text(encoding="utf-8")
    assert "${PORT}" in content or "$PORT" in content, (
        "Dockerfile CMD must use $PORT (Render/Railway inject PORT at runtime)"
    )


def test_dockerfile_exposes_a_port():
    content = _path("backend/Dockerfile").read_text(encoding="utf-8")
    assert "EXPOSE" in content, "Dockerfile must EXPOSE a port"


def test_dockerfile_copies_app_directory():
    content = _path("backend/Dockerfile").read_text(encoding="utf-8")
    assert "COPY" in content and "app" in content, (
        "Dockerfile must COPY the app/ directory into the image"
    )


def test_dockerfile_installs_requirements():
    content = _path("backend/Dockerfile").read_text(encoding="utf-8")
    assert "requirements.txt" in content, (
        "Dockerfile must install from requirements.txt"
    )


# ===========================================================================
# render.yaml
# ===========================================================================

def test_render_yaml_exists():
    assert _path("render.yaml").exists(), "render.yaml must exist (H2 §9)"


def test_render_yaml_is_valid_yaml():
    content = _path("render.yaml").read_text(encoding="utf-8")
    # Strip comment lines before parsing (PyYAML handles them, but be safe)
    parsed = yaml.safe_load(content)
    assert parsed is not None, "render.yaml must be valid YAML"


def test_render_yaml_defines_web_service():
    content = _path("render.yaml").read_text(encoding="utf-8")
    parsed = yaml.safe_load(content)
    services = parsed.get("services", [])
    assert any(s.get("type") == "web" for s in services), (
        "render.yaml must define at least one web service"
    )


def test_render_yaml_references_dockerfile():
    content = _path("render.yaml").read_text(encoding="utf-8")
    assert "Dockerfile" in content or "dockerfile" in content.lower(), (
        "render.yaml must reference the backend Dockerfile"
    )


def test_render_yaml_sets_live_adapter_enabled_false():
    """Contract Invariant 7: render.yaml must commit LIVE_ADAPTER_ENABLED=false."""
    content = _path("render.yaml").read_text(encoding="utf-8")
    # The value can appear as YAML string "false" or boolean false
    assert "LIVE_ADAPTER_ENABLED" in content, (
        "render.yaml must set LIVE_ADAPTER_ENABLED (Contract Invariant 7)"
    )
    # Ensure it's set to false (as string or bool — both acceptable)
    assert re.search(r'LIVE_ADAPTER_ENABLED.*["\']?false["\']?', content, re.IGNORECASE), (
        "render.yaml must set LIVE_ADAPTER_ENABLED to false (Contract Invariant 7)"
    )


def test_render_yaml_sets_default_dataset_synthetic_demo():
    content = _path("render.yaml").read_text(encoding="utf-8")
    assert "synthetic_demo" in content, (
        "render.yaml must set DEFAULT_DATASET=synthetic_demo"
    )


# ===========================================================================
# railway.toml
# ===========================================================================

def test_railway_toml_exists():
    assert _path("railway.toml").exists(), "railway.toml must exist (H2 §9)"


def test_railway_toml_is_valid_toml():
    content = _path("railway.toml").read_bytes()
    parsed = tomllib.loads(content.decode("utf-8"))
    assert parsed is not None, "railway.toml must be valid TOML"


def test_railway_toml_references_dockerfile():
    content = _path("railway.toml").read_text(encoding="utf-8")
    assert "Dockerfile" in content or "dockerfile" in content.lower(), (
        "railway.toml must reference the backend Dockerfile"
    )


def test_railway_toml_sets_live_adapter_enabled_false():
    """Contract Invariant 7: railway.toml must commit LIVE_ADAPTER_ENABLED=false."""
    content = _path("railway.toml").read_text(encoding="utf-8")
    assert "LIVE_ADAPTER_ENABLED" in content, (
        "railway.toml must set LIVE_ADAPTER_ENABLED (Contract Invariant 7)"
    )
    assert re.search(r'LIVE_ADAPTER_ENABLED\s*=\s*["\']?false["\']?', content, re.IGNORECASE), (
        "railway.toml must set LIVE_ADAPTER_ENABLED to false (Contract Invariant 7)"
    )


def test_railway_toml_sets_default_dataset():
    content = _path("railway.toml").read_text(encoding="utf-8")
    assert "synthetic_demo" in content, (
        "railway.toml must set DEFAULT_DATASET=synthetic_demo"
    )


# ===========================================================================
# frontend/vercel.json
# ===========================================================================

def test_vercel_json_exists():
    assert _path("frontend/vercel.json").exists(), "frontend/vercel.json must exist (H2 §9)"


def test_vercel_json_is_valid_json():
    content = _path("frontend/vercel.json").read_text(encoding="utf-8")
    # Strip comment lines (our vercel.json uses a _comment key, not inline comments)
    parsed = json.loads(content)
    assert isinstance(parsed, dict), "frontend/vercel.json must be a JSON object"


def test_vercel_json_specifies_nextjs_framework():
    parsed = json.loads(_path("frontend/vercel.json").read_text(encoding="utf-8"))
    assert parsed.get("framework") == "nextjs", (
        "frontend/vercel.json must set framework to 'nextjs'"
    )


def test_vercel_json_has_api_base_url_env():
    parsed = json.loads(_path("frontend/vercel.json").read_text(encoding="utf-8"))
    env = parsed.get("env", {})
    assert "NEXT_PUBLIC_API_BASE_URL" in env, (
        "frontend/vercel.json must define NEXT_PUBLIC_API_BASE_URL in env"
    )


def test_vercel_json_does_not_include_backend_service():
    """Vercel hosts the frontend only — backend is on Render/Railway (DOC2 §15)."""
    content = _path("frontend/vercel.json").read_text(encoding="utf-8")
    # Vercel serverless functions would appear as "functions" key or similar
    parsed = json.loads(content)
    assert "functions" not in parsed or not parsed["functions"], (
        "frontend/vercel.json must not define backend serverless functions — "
        "backend lives on Render/Railway (DOC2 §15)"
    )


# ===========================================================================
# README.md deployment section
# ===========================================================================

def test_readme_exists():
    assert _path("README.md").exists(), "README.md must exist (H2 §9)"


def test_readme_has_deployment_section():
    content = _path("README.md").read_text(encoding="utf-8")
    assert "## Deployment" in content or "# Deployment" in content, (
        "README.md must contain a Deployment section (H2 §9)"
    )


def test_readme_mentions_all_three_platforms():
    content = _path("README.md").read_text(encoding="utf-8")
    for platform in ("Vercel", "Render", "Railway", "Neo4j"):
        assert platform in content, (
            f"README.md deployment section must mention {platform} (DOC2 §15)"
        )


def test_readme_documents_live_adapter_invariant():
    """README must prominently document Contract Invariant 7."""
    content = _path("README.md").read_text(encoding="utf-8")
    assert "LIVE_ADAPTER_ENABLED" in content, (
        "README.md must document the LIVE_ADAPTER_ENABLED=false requirement "
        "(Contract Invariant 7 — DOC3)"
    )


def test_readme_has_environment_variables_section():
    content = _path("README.md").read_text(encoding="utf-8")
    assert "NEO4J_URI" in content and "NEO4J_PASSWORD" in content, (
        "README.md must document required environment variables"
    )


def test_readme_references_smoke_test_script():
    content = _path("README.md").read_text(encoding="utf-8")
    assert "smoke_test_deploy.py" in content, (
        "README.md must reference the smoke_test_deploy.py script (H2 §13)"
    )


# ===========================================================================
# Smoke test script
# ===========================================================================

def test_smoke_test_script_exists():
    assert _path("scripts/smoke_test_deploy.py").exists(), (
        "scripts/smoke_test_deploy.py must exist (H2 §13)"
    )


def test_smoke_test_script_is_syntactically_valid():
    """The script must be importable without syntax errors."""
    import ast
    content = _path("scripts/smoke_test_deploy.py").read_text(encoding="utf-8")
    try:
        ast.parse(content)
    except SyntaxError as e:
        pytest.fail(f"scripts/smoke_test_deploy.py has a syntax error: {e}")


def test_smoke_test_script_checks_invariant7():
    """The smoke test script must verify LIVE_ADAPTER_ENABLED=false."""
    content = _path("scripts/smoke_test_deploy.py").read_text(encoding="utf-8")
    assert "LIVE_ADAPTER_ENABLED" in content, (
        "smoke_test_deploy.py must verify LIVE_ADAPTER_ENABLED=false "
        "(Contract Invariant 7 check)"
    )


# ===========================================================================
# H2 §17 constraint: no fourth platform introduced
# ===========================================================================

def test_no_fourth_platform_config_introduced():
    """H2 §17: only Vercel, Render, Railway, Neo4j Aura are allowed (DOC2 §15)."""
    disallowed = [
        "heroku.yml", "app.yaml", "fly.toml",
        "serverless.yml", "netlify.toml", "k8s", "kubernetes",
    ]
    for name in disallowed:
        path = REPO_ROOT / name
        assert not path.exists(), (
            f"Undocumented platform config '{name}' found — "
            "H2 §17 permits only Vercel/Render/Railway/Neo4j Aura (DOC2 §15)"
        )


def test_no_new_infrastructure_dependencies():
    """H2 must not introduce message brokers, WebSockets, or a second database."""
    # Check requirements.txt has not gained any such packages
    req_content = _path("backend/requirements.txt").read_text(encoding="utf-8")
    forbidden = ["kafka", "rabbitmq", "redis", "celery", "aio-pika", "websockets"]
    for pkg in forbidden:
        assert pkg not in req_content.lower(), (
            f"'{pkg}' found in requirements.txt — "
            "H2 must not add message brokers or a second database (DOC2 Principle 7)"
        )
