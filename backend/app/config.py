"""Configuration and Environment Loading.

Task A2: Typed, validated configuration loading using Pydantic Settings.
References: DOC2 §15, DOC3 §1.2, DOC3 §2.1, DOC3 §2.6, docs/tasks/A/A2.md.
"""

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import yaml
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """Application configuration loaded from environment variables and .env files."""

    # Application execution environment
    ENVIRONMENT: Literal["development", "production", "test"] = "development"

    # Default dataset scope for queries (DOC3 §2.1, §2.6)
    DEFAULT_DATASET: Literal["synthetic_demo", "live_public"] = "synthetic_demo"

    # Controls whether the live adapter runs (DOC2 §6.5, DOC3 Invariant 7)
    LIVE_ADAPTER_ENABLED: bool = False

    # Neo4j connection settings (DOC2 §15)
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: Optional[str] = "password"

    # LLM provider settings (DOC2 §12A, DOC3 §14)
    LLM_PROVIDER: str = "mock"
    LLM_API_KEY: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=(".env", "config/.env", "../config/.env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_production_requirements(self) -> "Config":
        """Enforce strict configuration requirements outside of local-dev mode."""
        if self.ENVIRONMENT not in ("development", "test"):
            missing = []
            if not self.NEO4J_URI or self.NEO4J_URI == "bolt://localhost:7687":
                missing.append("NEO4J_URI must be configured for non-development environments")
            if not self.NEO4J_USER:
                missing.append("NEO4J_USER must be configured for non-development environments")
            if not self.NEO4J_PASSWORD or self.NEO4J_PASSWORD == "password":
                missing.append("NEO4J_PASSWORD must be configured for non-development environments")
            if self.LLM_PROVIDER not in ("mock", "none") and not self.LLM_API_KEY:
                missing.append(
                    f"LLM_API_KEY must be provided when LLM_PROVIDER is '{self.LLM_PROVIDER}'"
                )

            if missing:
                raise ValueError(
                    f"Missing required configuration outside development mode: {'; '.join(missing)}"
                )
        return self


def find_adapters_config_path(explicit_path: Optional[Path | str] = None) -> Path:
    """Resolve the location of config/adapters.yaml."""
    if explicit_path:
        p = Path(explicit_path)
        if p.exists():
            return p
        raise FileNotFoundError(f"Adapters config file not found at: {explicit_path}")

    candidates = [
        Path("config/adapters.yaml"),
        Path("../config/adapters.yaml"),
        Path(__file__).resolve().parent.parent.parent / "config" / "adapters.yaml",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    raise FileNotFoundError("Could not locate config/adapters.yaml in expected search paths")


def load_adapters_config(yaml_path: Optional[Path | str] = None) -> List[Dict[str, Any]]:
    """Load and validate adapter configuration from adapters.yaml (DOC3 §1.2)."""
    resolved_path = find_adapters_config_path(yaml_path)
    with open(resolved_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict) or "adapters" not in data:
        raise ValueError("Invalid adapters.yaml format: missing top-level 'adapters' key")

    adapters = data["adapters"]
    required_keys = {"adapter_id", "source_type", "dataset", "mode", "enabled", "poll_interval_seconds"}
    for item in adapters:
        missing = required_keys - set(item.keys())
        if missing:
            raise ValueError(f"Adapter entry '{item.get('adapter_id')}' missing required keys: {missing}")
        if item["dataset"] not in ("synthetic_demo", "live_public"):
            raise ValueError(
                f"Adapter entry '{item.get('adapter_id')}' has invalid dataset '{item.get('dataset')}'"
            )
        if item["mode"] not in ("batch", "poll"):
            raise ValueError(
                f"Adapter entry '{item.get('adapter_id')}' has invalid mode '{item.get('mode')}'"
            )
        if item["mode"] == "poll" and item["poll_interval_seconds"] is None:
            raise ValueError(
                f"Adapter entry '{item.get('adapter_id')}' with mode='poll' requires poll_interval_seconds"
            )

    return adapters


@lru_cache()
def get_config() -> Config:
    """Return a cached Config singleton instance."""
    return Config()


# Default singleton instance
config = get_config()
