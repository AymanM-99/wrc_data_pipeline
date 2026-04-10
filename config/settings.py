"""
Configuration module for WRC Scraper Pipeline.

All settings are loaded from environment variables with sensible defaults.
This ensures no hardcoded values and easy configuration across environments.
"""

import os
from dataclasses import dataclass
from typing import List
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


def get_env(key: str, default: str = None, cast_type: type = str):
    """Get environment variable with type casting."""
    value = os.getenv(key, default)
    if value is None:
        return None
    if cast_type == bool:
        return value.lower() in ('true', '1', 'yes')
    return cast_type(value)


@dataclass
class MongoConfig:
    """MongoDB connection configuration."""
    username: str = get_env('MONGO_USERNAME', 'admin')
    password: str = get_env('MONGO_PASSWORD', 'password123')
    host: str = get_env('MONGO_HOST', 'localhost')
    port: int = get_env('MONGO_PORT', '27017', int)
    database: str = get_env('MONGO_DATABASE', 'wrc_scraper')
    
    @property
    def connection_string(self) -> str:
        """Generate MongoDB connection string."""
        return f"mongodb://{self.username}:{self.password}@{self.host}:{self.port}"
    
    @property
    def landing_collection(self) -> str:
        return get_env('LANDING_COLLECTION', 'landing_docs')
    
    @property
    def processed_collection(self) -> str:
        return get_env('PROCESSED_COLLECTION', 'processed_docs')


@dataclass
class MinioConfig:
    """MinIO connection configuration."""
    root_user: str = get_env('MINIO_ROOT_USER', 'minioadmin')
    root_password: str = get_env('MINIO_ROOT_PASSWORD', 'minioadmin123')
    host: str = get_env('MINIO_HOST', 'localhost')
    port: int = get_env('MINIO_PORT', '9000', int)
    secure: bool = get_env('MINIO_SECURE', 'false', bool)
    
    @property
    def endpoint(self) -> str:
        """Generate MinIO endpoint."""
        return f"{self.host}:{self.port}"
    
    @property
    def landing_bucket(self) -> str:
        return get_env('LANDING_BUCKET', 'landing-bucket')
    
    @property
    def processed_bucket(self) -> str:
        return get_env('PROCESSED_BUCKET', 'processed-bucket')


@dataclass
class ScrapingConfig:
    """Scraping behavior configuration."""
    partition_size_days: int = get_env('PARTITION_SIZE_DAYS', '30', int)
    concurrent_requests: int = get_env('CONCURRENT_REQUESTS', '8', int)
    download_delay: float = get_env('DOWNLOAD_DELAY', '1.0', float)
    autothrottle_enabled: bool = get_env('AUTOTHROTTLE_ENABLED', 'true', bool)
    autothrottle_start_delay: float = get_env('AUTOTHROTTLE_START_DELAY', '1.0', float)
    autothrottle_max_delay: float = get_env('AUTOTHROTTLE_MAX_DELAY', '10.0', float)
    autothrottle_target_concurrency: float = get_env('AUTOTHROTTLE_TARGET_CONCURRENCY', '4.0', float)
    retry_times: int = get_env('RETRY_TIMES', '3', int)
    
    @property
    def retry_http_codes(self) -> List[int]:
        codes_str = get_env('RETRY_HTTP_CODES', '500,502,503,504,408,429')
        return [int(code.strip()) for code in codes_str.split(',')]


@dataclass
class LoggingConfig:
    """Logging configuration."""
    level: str = get_env('LOG_LEVEL', 'INFO')
    format: str = get_env('LOG_FORMAT', 'json')


# WRC Website Configuration (constants - unlikely to change)
WRC_BASE_URL = "https://www.workplacerelations.ie"
WRC_SEARCH_URL = f"{WRC_BASE_URL}/en/cases/search"

# The four bodies to scrape
WRC_BODIES = [
    "Employment Appeals Tribunal",
    "Equality Tribunal",
    "Labour Court",
    "Workplace Relations Commission"
]


# Global config instances
mongo_config = MongoConfig()
minio_config = MinioConfig()
scraping_config = ScrapingConfig()
logging_config = LoggingConfig()
