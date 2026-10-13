"""Unit tests for Task A2: Configuration & Environment Loading.

Tests:
1. Default values match DOC specifications (DEFAULT_DATASET='synthetic_demo', LIVE_ADAPTER_ENABLED=false).
2. Environment-variable override behavior works as expected.
3. Missing required variables outside development mode raise clear errors.
4. Loading and validation of config/adapters.yaml against AdapterDescriptor requirements.
"""

import os
from unittest.mock import patch
import pytest
from pydantic import ValidationError

from app.config import Config, get_config, load_adapters_config


def test_config_defaults():
    """Verify default values match DOC specifications."""
    # Create fresh Config without custom env overrides
    with patch.dict(os.environ, {}, clear=True):
        cfg = Config()
        assert cfg.DEFAULT_DATASET == "synthetic_demo"
        assert cfg.LIVE_ADAPTER_ENABLED is False
        assert cfg.ENVIRONMENT == "development"
        assert cfg.NEO4J_URI == "bolt://localhost:7687"
        assert cfg.NEO4J_USER == "neo4j"
        assert cfg.NEO4J_PASSWORD == "password"
        assert cfg.LLM_PROVIDER == "mock"
        assert cfg.LLM_API_KEY is None


def test_config_environment_overrides():
    """Verify overriding variables via the environment is reflected correctly."""
    env_overrides = {
        "ENVIRONMENT": "development",
        "DEFAULT_DATASET": "live_public",
        "LIVE_ADAPTER_ENABLED": "true",
        "NEO4J_URI": "bolt://custom-host:7687",
        "NEO4J_USER": "custom_user",
        "NEO4J_PASSWORD": "custom_password",
        "LLM_PROVIDER": "openai",
        "LLM_API_KEY": "sk-test12345",
    }
    with patch.dict(os.environ, env_overrides, clear=True):
        cfg = Config()
        assert cfg.DEFAULT_DATASET == "live_public"
        assert cfg.LIVE_ADAPTER_ENABLED is True
        assert cfg.NEO4J_URI == "bolt://custom-host:7687"
        assert cfg.NEO4J_USER == "custom_user"
        assert cfg.NEO4J_PASSWORD == "custom_password"
        assert cfg.LLM_PROVIDER == "openai"
        assert cfg.LLM_API_KEY == "sk-test12345"


def test_config_invalid_dataset():
    """Verify invalid DEFAULT_DATASET values are rejected."""
    with patch.dict(os.environ, {"DEFAULT_DATASET": "invalid_dataset"}, clear=True):
        with pytest.raises(ValidationError):
            Config()


def test_production_mode_requires_strict_configuration():
    """Verify missing required variables raise a clear error outside dev mode."""
    # In production with default values, validation should fail fast
    prod_env_with_defaults = {
        "ENVIRONMENT": "production",
    }
    with patch.dict(os.environ, prod_env_with_defaults, clear=True):
        with pytest.raises(ValueError) as exc_info:
            Config()
        error_msg = str(exc_info.value)
        assert "Missing required configuration outside development mode" in error_msg
        assert "NEO4J_URI" in error_msg
        assert "NEO4J_PASSWORD" in error_msg


def test_production_mode_requires_llm_key_when_not_mock():
    """Verify production requires LLM_API_KEY when LLM_PROVIDER is non-mock."""
    prod_env = {
        "ENVIRONMENT": "production",
        "NEO4J_URI": "neo4j+s://prod.neo4j.io:7687",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "strong_production_password",
        "LLM_PROVIDER": "openai",
    }
    with patch.dict(os.environ, prod_env, clear=True):
        with pytest.raises(ValueError) as exc_info:
            Config()
        assert "LLM_API_KEY must be provided" in str(exc_info.value)


def test_production_mode_succeeds_with_valid_configuration():
    """Verify production mode succeeds when all required secrets are provided."""
    valid_prod_env = {
        "ENVIRONMENT": "production",
        "NEO4J_URI": "neo4j+s://prod.neo4j.io:7687",
        "NEO4J_USER": "neo4j_admin",
        "NEO4J_PASSWORD": "strong_production_password",
        "LLM_PROVIDER": "openai",
        "LLM_API_KEY": "sk-real-prod-key",
    }
    with patch.dict(os.environ, valid_prod_env, clear=True):
        cfg = Config()
        assert cfg.ENVIRONMENT == "production"
        assert cfg.NEO4J_URI == "neo4j+s://prod.neo4j.io:7687"


def test_adapters_yaml_loading():
    """Verify config/adapters.yaml loads and conforms to AdapterDescriptor shape."""
    adapters = load_adapters_config()
    assert len(adapters) >= 2

    # Check synthetic adapter (guaranteed demo path)
    synthetic = next((a for a in adapters if a["adapter_id"] == "synthetic_v1"), None)
    assert synthetic is not None
    assert synthetic["dataset"] == "synthetic_demo"
    assert synthetic["mode"] == "batch"
    assert synthetic["enabled"] is True

    # Check live adapter (optional polling path)
    live = next((a for a in adapters if a["adapter_id"] == "rss_public_v1"), None)
    assert live is not None
    assert live["dataset"] == "live_public"
    assert live["mode"] == "poll"
    assert live["enabled"] is False
    assert live["poll_interval_seconds"] == 300


def test_load_from_env_example():
    """Verify Config is loadable directly from config/.env.example with documented defaults."""
    env_example_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../config/.env.example"))
    assert os.path.exists(env_example_path), f".env.example not found at {env_example_path}"

    with patch.dict(os.environ, {}, clear=True):
        cfg = Config(_env_file=env_example_path)
        assert cfg.DEFAULT_DATASET == "synthetic_demo"
        assert cfg.LIVE_ADAPTER_ENABLED is False
        assert cfg.ENVIRONMENT == "development"
        assert cfg.NEO4J_URI == "bolt://localhost:7687"
        assert cfg.NEO4J_USER == "neo4j"
        assert cfg.NEO4J_PASSWORD == "password"
        assert cfg.LLM_PROVIDER == "mock"
