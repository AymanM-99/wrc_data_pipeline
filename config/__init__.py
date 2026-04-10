"""Configuration module."""
from .settings import (
    mongo_config,
    minio_config,
    scraping_config,
    logging_config,
    WRC_BASE_URL,
    WRC_SEARCH_URL,
    WRC_BODIES,
)

__all__ = [
    'mongo_config',
    'minio_config',
    'scraping_config',
    'logging_config',
    'WRC_BASE_URL',
    'WRC_SEARCH_URL',
    'WRC_BODIES',
]
