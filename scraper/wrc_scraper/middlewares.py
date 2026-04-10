"""
Scrapy Middlewares for WRC Scraper.

Middlewares process requests/responses before they reach spiders or pipelines.
Similar to Django middleware, but for web scraping.
"""

import random
import time
from scrapy import signals
from scrapy.downloadermiddlewares.retry import RetryMiddleware
from scrapy.utils.response import response_status_message


class RandomUserAgentMiddleware:
    """
    Rotates User-Agent headers to avoid detection.
    
    Why: Some websites block requests that appear to be from bots.
    Rotating user agents makes requests look like they come from
    different browsers/devices.
    """
    
    USER_AGENTS = [
        # Chrome on Windows
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        # Firefox on Windows
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        # Chrome on Mac
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        # Safari on Mac
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
        # Edge on Windows
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    ]
    
    def process_request(self, request, spider):
        """Set a random User-Agent for each request."""
        request.headers['User-Agent'] = random.choice(self.USER_AGENTS)
        return None


class RetryWithBackoffMiddleware(RetryMiddleware):
    """
    Enhanced retry middleware with exponential backoff.
    
    Why: When a server returns errors (429 Too Many Requests, 503, etc.),
    we should wait before retrying. Each subsequent retry waits longer
    (exponential backoff) to give the server time to recover.
    
    Example: 1st retry: 2s, 2nd retry: 4s, 3rd retry: 8s
    """
    
    def __init__(self, settings):
        super().__init__(settings)
        self.base_delay = 2  # Base delay in seconds
        self.max_delay = 60  # Maximum delay
    
    def process_response(self, request, response, spider):
        """Handle response and apply backoff for certain status codes."""
        if response.status in [429, 503]:
            # Server is overloaded - wait before retrying
            retry_count = request.meta.get('retry_times', 0)
            delay = min(self.base_delay * (2 ** retry_count), self.max_delay)
            
            spider.logger.warning(
                f"Got {response.status}, backing off for {delay}s before retry"
            )
            time.sleep(delay)
        
        return super().process_response(request, response, spider)
    
    def process_exception(self, request, exception, spider):
        """Handle connection errors with backoff."""
        retry_count = request.meta.get('retry_times', 0)
        delay = min(self.base_delay * (2 ** retry_count), self.max_delay)
        
        spider.logger.warning(
            f"Connection error: {exception}, backing off for {delay}s"
        )
        time.sleep(delay)
        
        return super().process_exception(request, exception, spider)


class SpiderStatsMiddleware:
    """
    Collects statistics about the spider run.
    
    Why: Required by specification to log:
    - Number of records found vs. successfully scraped
    - Failed downloads with URLs and error codes
    """
    
    @classmethod
    def from_crawler(cls, crawler):
        middleware = cls()
        crawler.signals.connect(middleware.spider_opened, signal=signals.spider_opened)
        crawler.signals.connect(middleware.spider_closed, signal=signals.spider_closed)
        return middleware
    
    def spider_opened(self, spider):
        """Initialize stats when spider starts."""
        spider.stats = {
            'records_found': 0,
            'records_scraped': 0,
            'records_failed': 0,
            'failed_urls': [],
        }
    
    def spider_closed(self, spider, reason):
        """Log final stats when spider finishes."""
        spider.logger.info(f"Spider closed: {reason}")
        spider.logger.info(f"Records found: {spider.stats.get('records_found', 0)}")
        spider.logger.info(f"Records scraped: {spider.stats.get('records_scraped', 0)}")
        spider.logger.info(f"Records failed: {spider.stats.get('records_failed', 0)}")
        
        if spider.stats.get('failed_urls'):
            spider.logger.warning(f"Failed URLs: {spider.stats['failed_urls']}")
