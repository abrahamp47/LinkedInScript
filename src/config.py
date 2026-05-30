"""Configuration loading, validation, and logging setup for LinkedInScript.

Exports:
    load_config(config_path: Path) -> dict
    validate_config(config: dict) -> None
    setup_logging(config: dict, project_root: Path) -> None
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import yaml
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Resolve project root from this file's location (src/config.py -> project root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_config(config_path: Path) -> dict:
    """Load configuration from a YAML file.

    Args:
        config_path: Path to the config.yaml file.

    Returns:
        Configuration dictionary.

    Raises:
        FileNotFoundError: If config_path does not exist.
    """
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config file not found: {config_path}\n"
            "Run 'python main.py' for first-time setup or copy config.example.yaml"
        )

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    return config


def validate_config(config: dict) -> None:
    """Validate configuration dictionary for required fields and types.

    Args:
        config: Configuration dictionary to validate.

    Raises:
        ValueError: If required fields are missing or invalid.
    """
    if not isinstance(config, dict):
        raise ValueError("Configuration must be a dictionary")

    # Validate search section exists
    search = config.get("search")
    if not search or not isinstance(search, dict):
        raise ValueError("Configuration must contain a 'search' section")

    # Validate keywords
    keywords = search.get("keywords")
    if not keywords:
        raise ValueError("search.keywords must be a non-empty list of search terms")
    if not isinstance(keywords, list):
        raise ValueError("search.keywords must be a non-empty list of search terms")

    # Validate locations
    locations = search.get("locations")
    if not locations:
        raise ValueError("search.locations must be a non-empty list of location strings")
    if not isinstance(locations, list):
        raise ValueError("search.locations must be a non-empty list of location strings")

    # Validate hours_old
    hours_old = search.get("hours_old", 24)
    if not isinstance(hours_old, int) or hours_old <= 0:
        raise ValueError("search.hours_old must be a positive integer")


def setup_logging(config: dict, project_root: Path) -> None:
    """Configure logging with a rotating file handler and console handler.

    Args:
        config: Configuration dictionary containing logging settings.
        project_root: Absolute path to the project root directory.
    """
    log_config = config.get("logging", {})
    log_file_relative = log_config.get("file", "logs/run.log")
    log_level = log_config.get("level", "INFO").upper()
    max_size_mb = log_config.get("max_size_mb", 5)
    backup_count = log_config.get("backup_count", 3)

    # Ensure absolute path resolution
    log_file = project_root / log_file_relative
    log_file.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Rotating file handler
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=max_size_mb * 1024 * 1024,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level, logging.INFO))
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    logger.debug("Logging configured: level=%s, file=%s", log_level, log_file)


def load_env(project_root: Path = None) -> None:
    """Load environment variables from .env file.

    Args:
        project_root: Path to project root. Defaults to detected PROJECT_ROOT.
    """
    root = project_root or PROJECT_ROOT
    env_path = root / ".env"
    load_dotenv(env_path)
