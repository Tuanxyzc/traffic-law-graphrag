"""Unit tests for PipelineConfig YAML and environment variable loading."""

from __future__ import annotations

from pathlib import Path

from src.pipeline.config import PipelineConfig


def test_pipeline_config_defaults() -> None:
    """Test default settings without external configuration."""
    cfg = PipelineConfig()
    assert cfg.generator_use_local is False
    assert cfg.rewriter_use_local is False
    assert cfg.enable_query_rewrite is True
    assert cfg.generator_local_model == "Qwen2.5:1.5b"
    assert cfg.rewriter_local_model == "Qwen2.5:1.5b"


def test_pipeline_config_from_yaml_file(tmp_path: Path) -> None:
    """Test loading settings from a custom YAML configuration file."""
    yaml_content = """
llm:
  generator:
    use_local: true
    local:
      endpoint: "http://127.0.0.1:8000/v1"
      model_name: "custom-gen-model"
      temperature: 0.3
      timeout_seconds: 90.0
      api_key: "custom-gen-key"
  rewriter:
    enable_rewrite: false
    use_local: false
    gemini:
      model_name: "gemini-2.5-pro"
      temperature: 0.05
      timeout_seconds: 45.0

pipeline:
  top_k: 8
  enable_dual_query: false
  include_superseded_warning: false
"""
    yaml_file = tmp_path / "custom_config.yaml"
    yaml_file.write_text(yaml_content, encoding="utf-8")

    cfg = PipelineConfig.from_env(config_path=str(yaml_file))

    assert cfg.generator_use_local is True
    assert cfg.generator_local_endpoint == "http://127.0.0.1:8000/v1"
    assert cfg.generator_local_model == "custom-gen-model"
    assert cfg.generator_local_temperature == 0.3
    assert cfg.generator_local_timeout == 90.0
    assert cfg.generator_local_api_key == "custom-gen-key"

    assert cfg.enable_query_rewrite is False
    assert cfg.rewriter_use_local is False
    assert cfg.rewrite_model_name == "gemini-2.5-pro"
    assert cfg.temperature_rewrite == 0.05

    assert cfg.top_k == 8
    assert cfg.enable_dual_query is False
    assert cfg.include_superseded_warning is False


def test_pipeline_config_env_overrides(tmp_path: Path, monkeypatch) -> None:
    """Test environment variable overrides on top of YAML configurations."""
    yaml_content = """
llm:
  generator:
    use_local: false
  rewriter:
    enable_rewrite: true
    use_local: false
"""
    yaml_file = tmp_path / "env_override_config.yaml"
    yaml_file.write_text(yaml_content, encoding="utf-8")

    monkeypatch.setenv("GENERATOR_USE_LOCAL", "true")
    monkeypatch.setenv("REWRITER_USE_LOCAL", "true")
    monkeypatch.setenv("ENABLE_QUERY_REWRITE", "false")
    monkeypatch.setenv("GENERATOR_LOCAL_MODEL", "Llama-3-8B")
    monkeypatch.setenv("REWRITER_LOCAL_MODEL", "Qwen2.5:3b")

    cfg = PipelineConfig.from_env(config_path=str(yaml_file))

    assert cfg.generator_use_local is True
    assert cfg.rewriter_use_local is True
    assert cfg.enable_query_rewrite is False
    assert cfg.generator_local_model == "Llama-3-8B"
    assert cfg.rewriter_local_model == "Qwen2.5:3b"
