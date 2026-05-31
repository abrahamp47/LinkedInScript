"""Unit tests for src/config.py — config loading, validation, and logging setup."""

import logging
import pytest
import yaml


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_config_returns_dict_with_keywords(self, tmp_path, sample_config):
        """Test 1: load_config returns dict with search.keywords list when given valid YAML path."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(sample_config))

        from src.config import load_config

        result = load_config(config_file)
        assert isinstance(result, dict)
        assert "search" in result
        assert "keywords" in result["search"]
        assert isinstance(result["search"]["keywords"], list)
        assert len(result["search"]["keywords"]) > 0

    def test_load_config_raises_file_not_found(self, tmp_path):
        """Test 2: load_config raises FileNotFoundError when config.yaml does not exist."""
        from src.config import load_config

        nonexistent = tmp_path / "nonexistent.yaml"
        with pytest.raises(FileNotFoundError):
            load_config(nonexistent)

    def test_load_config_handles_empty_yaml(self, tmp_path):
        """Test 7: load_config handles empty YAML file (returns empty dict triggering validation error)."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("")

        from src.config import load_config

        result = load_config(config_file)
        assert result == {}


class TestValidateConfig:
    """Tests for validate_config function."""

    def test_validate_config_raises_on_empty_keywords(self, sample_config):
        """Test 3: validate_config raises ValueError when search.keywords is empty or missing."""
        from src.config import validate_config

        sample_config["search"]["keywords"] = []
        with pytest.raises(ValueError, match="keywords"):
            validate_config(sample_config)

    def test_validate_config_raises_on_non_list_keywords(self, sample_config):
        """Test 4: validate_config raises ValueError when search.keywords is not a list."""
        from src.config import validate_config

        sample_config["search"]["keywords"] = "not a list"
        with pytest.raises(ValueError, match="keywords"):
            validate_config(sample_config)

    def test_validate_config_raises_on_empty_locations(self, sample_config):
        """Test 5: validate_config raises ValueError when search.locations is empty or missing."""
        from src.config import validate_config

        sample_config["search"]["locations"] = []
        with pytest.raises(ValueError, match="locations"):
            validate_config(sample_config)

    def test_validate_config_accepts_valid_locations_list(self, sample_config):
        """Test 8: validate_config accepts config with search.locations as a list of strings."""
        from src.config import validate_config

        # Should not raise
        validate_config(sample_config)

    def test_validate_config_raises_on_invalid_hours_old(self, sample_config):
        """Test 9: validate_config raises ValueError when search.hours_old is not a positive integer."""
        from src.config import validate_config

        sample_config["search"]["hours_old"] = -1
        with pytest.raises(ValueError, match="hours_old"):
            validate_config(sample_config)

        sample_config["search"]["hours_old"] = 0
        with pytest.raises(ValueError, match="hours_old"):
            validate_config(sample_config)

        sample_config["search"]["hours_old"] = "not a number"
        with pytest.raises(ValueError, match="hours_old"):
            validate_config(sample_config)

    def test_validate_config_raises_on_missing_search_section(self):
        """validate_config raises ValueError when search section is missing entirely."""
        from src.config import validate_config

        with pytest.raises(ValueError):
            validate_config({})


class TestSetupLogging:
    """Tests for setup_logging function."""

    def test_setup_logging_creates_log_directory_and_handler(self, tmp_path, sample_config):
        """Test 6: setup_logging creates logs/ directory and configures RotatingFileHandler."""
        from src.config import setup_logging

        sample_config["logging"]["file"] = "logs/run.log"

        setup_logging(sample_config, tmp_path)

        log_dir = tmp_path / "logs"
        assert log_dir.exists()
        assert log_dir.is_dir()

        # Verify a RotatingFileHandler was added to root logger
        root_logger = logging.getLogger()
        from logging.handlers import RotatingFileHandler

        rotating_handlers = [
            h for h in root_logger.handlers if isinstance(h, RotatingFileHandler)
        ]
        assert len(rotating_handlers) >= 1

        # Clean up handlers to avoid interference with other tests
        for h in rotating_handlers:
            root_logger.removeHandler(h)
            h.close()
