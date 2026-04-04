"""Tests for configuration management."""

import pytest
import tempfile
import os
from pathlib import Path

from ha_gateway.config import Config, load_or_create_config, get_default_config_path


class TestConfig:
    """Test configuration loading and validation."""

    def test_default_config(self):
        """Test default configuration values."""
        config = Config()

        assert config.home_assistant.url == "http://localhost:8123"
        assert config.home_assistant.auth_type == "long_lived_token"
        assert config.gateway.host == "0.0.0.0"
        assert config.gateway.port == 8124
        assert len(config.devices.include_domains) > 0

    def test_config_validation(self):
        """Test configuration validation."""
        # Valid config
        config = Config()
        config.validate()

        # Invalid - no HA URL
        config.home_assistant.url = ""
        with pytest.raises(ValueError, match="Home Assistant URL is required"):
            config.validate()

        # Invalid - token auth without token
        config.home_assistant.url = "http://localhost:8123"
        config.home_assistant.auth_type = "long_lived_token"
        config.home_assistant.access_token = None
        with pytest.raises(ValueError, match="Access token is required"):
            config.validate()

    def test_save_and_load(self):
        """Test saving and loading configuration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "test_config.yaml"

            # Create and save config
            config = Config()
            config.home_assistant.url = "http://test.example.com"
            config.save(config_path)
            assert config_path.exists()

            # Load config
            loaded_config = Config.from_file(config_path)
            assert loaded_config.home_assistant.url == "http://test.example.com"

    def test_load_or_create(self):
        """Test load or create configuration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"

            # Should create default config if it doesn't exist
            config = load_or_create_config(config_path)
            assert config_path.exists()
            assert config is not None

    def test_device_filtering(self):
        """Test device filtering configuration."""
        config = Config()

        # Test include domains
        assert "light" in config.devices.include_domains
        assert "sensor" in config.devices.include_domains

        # Test empty exclude
        assert len(config.devices.exclude) == 0