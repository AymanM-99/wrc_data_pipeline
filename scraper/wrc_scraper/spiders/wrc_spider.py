"""
WRC Spider - Main spider for scraping Workplace Relations Commission decisions.

This spider:
1. Takes start_date and end_date as inputs
2. Iterates through date partitions (monthly by default)
3. Scrapes all four bodies for each partition
4. Extracts metadata and document links
5. Handles pagination automatically

Usage:
    scrapy crawl wrc -a start_date=2024-01-01 -a end_date=2024-12-31
"""

import sys
import os
from datetime import datetime, timedelta
from typing import Iterator, Dict, Any, Optional
from urllib.parse import urlencode

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

import scrapy
from scrapy.http import Response

from wrc_scraper.items import WrcDocumentItem
from config import scraping_config, WRC_BASE_URL
from utils.logging_config import get_logger, setup_logging

# Setup logging
setup_logging()
logger = get_logger(__name__)


class WrcSpider(scrapy.Spider):
    """
    Spider for scraping WRC decisions and determinations.
    
    Arguments:
        start_date: Start of date range (YYYY-MM-DD format)
        end_date: End of date range (YYYY-MM-DD format)
        body: Optional - specific body index to scrape (1-4)
              If not provided, scrapes all bodies
    
    Example:
        scrapy crawl wrc -a start_date=2024-01-01 -a end_date=2024-03-31
    """
    
    name = "wrc"
    allowed_domains = ["workplacerelations.ie"]
    
    # Body mapping (as discovered from URL analysis)
    BODIES = {
        1: "Employment Appeals Tribunal",
        2: "Equality Tribunal", 
        3: "Labour Court",
        4: "Workplace Relations Commission",
    }
    
    BASE_SEARCH_URL = f"{WRC_BASE_URL}/en/search/"
    
    def __init__(self, start_date: str = None, end_date: str = None, 
                 body: int = None, *args, **kwargs):
        """
        Initialize spider with date range and optional body filter.
        
        Args:
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format
            body: Optional body index (1-4) to scrape only one body
        """
        super().__init__(*args, **kwargs)
        
        # Validate and parse dates
        if not start_date or not end_date:
            raise ValueError("Both start_date and end_date are required. "
                           "Example: scrapy crawl wrc -a start_date=2024-01-01 -a end_date=2024-12-31")
        
        try:
            self.start_date = datetime.strptime(start_date, "%Y-%m-%d")
            self.end_date = datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError as e:
            raise ValueError(f"Invalid date format. Use YYYY-MM-DD. Error: {e}")
        
        if self.start_date > self.end_date:
            raise ValueError("start_date must be before end_date")
        
        # Optional: filter to specific body
        self.body_filter = int(body) if body else None
        if self.body_filter and self.body_filter not in self.BODIES:
            raise ValueError(f"Invalid body index. Must be 1-4. Got: {self.body_filter}")
        
        # Get partition size from config (default: 30 days)
        self.partition_days = scraping_config.partition_size_days
        
        # Statistics tracking
        self.stats = {
            'records_found': 0,
            'records_scraped': 0,
            'records_failed': 0,
            'partitions_processed': 0,
            'failed_urls': [],
        }
        
        logger.info(
            f"Spider initialized",
            extra={
                'start_date': start_date,
                'end_date': end_date,
                'body_filter': self.body_filter,
                'partition_days': self.partition_days
            }
        )
    
    def start_requests(self) -> Iterator[scrapy.Request]:
        """
        Generate initial requests for all partitions and bodies.
        
        This creates requests for:
        - Each date partition (e.g., monthly)
        - Each body (Labour Court, WRC, etc.)
        - Page 1 of each combination
        """
        # Determine which bodies to scrape
        bodies_to_scrape = (
            [self.body_filter] if self.body_filter 
            else list(self.BODIES.keys())
        )
        
        # Generate partitions
        for partition_start, partition_end in self._generate_partitions():
            partition_date = partition_start.strftime("%Y-%m")
            
            for body_id in bodies_to_scrape:
                body_name = self.BODIES[body_id]
                
                logger.info(
                    f"Starting partition scrape",
                    extra={
                        'partition_date': partition_date,
                        'body': body_name
                    }
                )
                
                # Build search URL
                url = self._build_search_url(
                    from_date=partition_start,
                    to_date=partition_end,
                    body_id=body_id,
                    page=1
                )
                
                yield scrapy.Request(
                    url=url,
                    callback=self.parse_search_results,
                    meta={
                        'partition_date': partition_date,
                        'partition_start': partition_start,
                        'partition_end': partition_end,
                        'body_id': body_id,
                        'body_name': body_name,
                        'page': 1,
                    }
                )
    
    def _generate_partitions(self) -> Iterator[tuple]:
        """
        Generate date partitions between start and end date.
        
        Yields:
            Tuples of (partition_start, partition_end) datetime objects
        """
        current_start = self.start_date
        
        while current_start <= self.end_date:
            # Calculate partition end (partition_days later or end_date, whichever is first)
            partition_end = min(
                current_start + timedelta(days=self.partition_days - 1),
                self.end_date
            )
            
            yield (current_start, partition_end)
            
            # Move to next partition
            current_start = partition_end + timedelta(days=1)
    
    def _build_search_url(self, from_date: datetime, to_date: datetime,
                          body_id: int, page: int = 1) -> str:
        """
        Build the search URL with all parameters.
        
        Args:
            from_date: Start date
            to_date: End date
            body_id: Body index (1-4)
            page: Page number
        
        Returns:
            Complete search URL
        """
        # Format dates as D/M/YYYY (as used by the website)
        # Using f-string for Windows compatibility (strftime %-d doesn't work on Windows)
        from_str = f"{from_date.day}/{from_date.month}/{from_date.year}"
        to_str = f"{to_date.day}/{to_date.month}/{to_date.year}"
        
        params = {
            'decisions': '1',
            'body': str(body_id),
            'from': from_str,
            'to': to_str,
            'pageNumber': str(page),
        }
        
        return f"{self.BASE_SEARCH_URL}?{urlencode(params)}"
    
    def parse_search_results(self, response: Response) -> Iterator[Any]:
        """
        Parse search results page and extract document items.
        
        Extracts:
        - Identifier (e.g., ADJ-00054658)
        - Description (case title)
        - Published date
        - Link to document page
        
        Also handles pagination by following next page links.
        """
        partition_date = response.meta['partition_date']
        body_id = response.meta['body_id']
        body_name = response.meta['body_name']
        current_page = response.meta['page']
        
        # Debug: log response info
        logger.debug(f"Response URL: {response.url}, Length: {len(response.text)}")
        
        # Extract total results count (e.g., "Shows 1 to 10 of 845 results")
        # Use regex with flexible whitespace
        import re
        text_content = ' '.join(response.css('*::text').getall())
        results_match = re.search(r'Shows\s+\d+\s+to\s+\d+\s+of\s+(\d+)\s+results', text_content)
        total_results = int(results_match.group(1)) if results_match else 0
        
        if current_page == 1:
            logger.info(
                f"Found {total_results} results",
                extra={
                    'partition_date': partition_date,
                    'body': body_name,
                    'records_found': total_results
                }
            )
            self.stats['records_found'] += total_results
        
        # Extract each result item
        # Based on the HTML structure, results are in h2 > a elements
        result_blocks = response.css('h2 > a[href*="/cases/"]')
        logger.debug(f"Found {len(result_blocks)} result blocks")
        
        for result in result_blocks:
            identifier = result.css('::text').get()
            document_url = result.css('::attr(href)').get()
            
            if not identifier or not document_url:
                continue
            
            # Clean identifier
            identifier = identifier.strip()
            
            # Get the parent container to find description and date
            # Navigate up to find the containing block
            parent = result.xpath('./ancestor::*[contains(@class, "result") or self::div or self::article][1]')
            
            # Try to extract description (case title)
            # Based on the fetched content: "Zara Yaffe V Lynott Jewellery Holdings Limited"
            description = ""
            date_str = ""
            
            # Look for text content near the identifier
            # The description usually follows the identifier/date
            container = result.xpath('./ancestor::*[position()<=3]')
            all_text = container.css('*::text').getall()
            all_text = [t.strip() for t in all_text if t.strip()]
            
            # Look for date pattern (DD/MM/YYYY)
            import re
            for text in all_text:
                # Check for date
                date_match = re.search(r'\d{1,2}/\d{1,2}/\d{4}', text)
                if date_match:
                    date_str = date_match.group()
                # Check for "V" or "v" which typically separates parties
                elif ' V ' in text.upper() and not description:
                    description = text
                # Or "Ref no:" line
                elif text.startswith('Ref no:'):
                    continue
            
            # If no description found, try getting nearby text
            if not description:
                sibling_text = result.xpath('./following::text()[normalize-space()][position()<=5]').getall()
                for text in sibling_text:
                    text = text.strip()
                    if text and ' V ' in text.upper():
                        description = text
                        break
            
            # Create item
            item = WrcDocumentItem()
            item['identifier'] = identifier
            item['description'] = description
            item['published_date'] = date_str
            item['document_url'] = document_url
            item['body'] = body_name
            item['partition_date'] = partition_date
            
            logger.debug(
                f"Extracted item: {identifier}",
                extra={
                    'identifier': identifier,
                    'body': body_name,
                    'partition_date': partition_date
                }
            )
            
            yield item
        
        # Handle pagination - check for next page
        # Pagination links are like: pageNumber=2, pageNumber=3, etc.
        next_page = current_page + 1
        next_page_link = response.css(f'a[href*="pageNumber={next_page}"]::attr(href)').get()
        
        if next_page_link:
            logger.debug(f"Following pagination to page {next_page}")
            
            yield scrapy.Request(
                url=response.urljoin(next_page_link),
                callback=self.parse_search_results,
                meta={
                    **response.meta,
                    'page': next_page,
                }
            )
        else:
            # No more pages - partition complete
            self.stats['partitions_processed'] += 1
            logger.info(
                f"Partition complete",
                extra={
                    'partition_date': partition_date,
                    'body': body_name,
                    'page': current_page
                }
            )
    
    def closed(self, reason: str):
        """
        Called when spider closes. Log final statistics.
        
        This produces the summary required by the specification.
        """
        logger.info(
            f"Spider closed: {reason}",
            extra={
                'reason': reason,
                'records_found': self.stats['records_found'],
                'records_scraped': self.stats['records_scraped'],
                'records_failed': self.stats['records_failed'],
                'partitions_processed': self.stats['partitions_processed'],
            }
        )
        
        if self.stats['failed_urls']:
            logger.warning(
                f"Failed downloads summary",
                extra={
                    'failed_count': len(self.stats['failed_urls']),
                    'failed_urls': self.stats['failed_urls'][:10]  # First 10
                }
            )
