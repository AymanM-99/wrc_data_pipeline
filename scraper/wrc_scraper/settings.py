"""
Scrapy settings for WRC Scraper project.

Settings are loaded from environment variables via the config module,
ensuring no hardcoded values as required by the specification.
"""

import sys
import os

# Add parent directory to path so we can import from config/utils
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config import scraping_config

BOT_NAME = "wrc_scraper"

SPIDER_MODULES = ["wrc_scraper.spiders"]
NEWSPIDER_MODULE = "wrc_scraper.spiders"

# Crawl responsibly by identifying yourself
USER_AGENT = "WRC-Legal-Scraper/1.0 (+https://github.com/yourrepo)"

# Obey robots.txt rules
ROBOTSTXT_OBEY = True

# Configure maximum concurrent requests (from config)
CONCURRENT_REQUESTS = scraping_config.concurrent_requests

# Configure a delay for requests (from config)
DOWNLOAD_DELAY = scraping_config.download_delay

# Disable cookies (not needed for this site)
COOKIES_ENABLED = False

# Enable and configure the AutoThrottle extension (from config)
AUTOTHROTTLE_ENABLED = scraping_config.autothrottle_enabled
AUTOTHROTTLE_START_DELAY = scraping_config.autothrottle_start_delay
AUTOTHROTTLE_MAX_DELAY = scraping_config.autothrottle_max_delay
AUTOTHROTTLE_TARGET_CONCURRENCY = scraping_config.autothrottle_target_concurrency
AUTOTHROTTLE_DEBUG = False

# Configure retry settings (from config)
RETRY_ENABLED = True
RETRY_TIMES = scraping_config.retry_times
RETRY_HTTP_CODES = scraping_config.retry_http_codes

# Enable HTTP caching for development (reduces load on server during testing)
HTTPCACHE_ENABLED = False
HTTPCACHE_EXPIRATION_SECS = 3600
HTTPCACHE_DIR = ".scrapy/httpcache"

# Configure item pipelines
# Lower number = higher priority (runs first)
ITEM_PIPELINES = {
    "wrc_scraper.pipelines.ValidationPipeline": 100,      # Validate items first
    "wrc_scraper.pipelines.FileDownloadPipeline": 200,    # Download files
    "wrc_scraper.pipelines.StoragePipeline": 300,         # Store to MinIO + MongoDB
}

# Configure middlewares
DOWNLOADER_MIDDLEWARES = {
    "wrc_scraper.middlewares.RandomUserAgentMiddleware": 400,
    "wrc_scraper.middlewares.RetryWithBackoffMiddleware": 550,
}

# Logging
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"

# Request fingerprinting (Scrapy 2.7+)
REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"

# Feed exports (not used - we store directly to MongoDB)
FEEDS = {}

# Set settings whose default value is deprecated to a future-proof value
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
