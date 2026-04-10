"""
Scrapy Items for WRC Scraper.

Items define the data structure for scraped documents.
Think of these like Django models, but for scraped data.
"""

import scrapy


class WrcDocumentItem(scrapy.Item):
    """
    Represents a single WRC decision/determination document.
    
    Fields match the metadata requirements from the specification:
    - identifier: Unique ID (e.g., ADJ-00054658, LCR23238)
    - description: Case title (e.g., "John Smith V Company Ltd")
    - published_date: Date published on the website
    - document_url: URL to the document page or PDF
    - body: Which body issued the decision (Labour Court, WRC, etc.)
    - partition_date: The date partition this record belongs to (YYYY-MM)
    - file_path: Path to stored file in MinIO (set by pipeline)
    - file_hash: SHA256 hash of the file (set by pipeline)
    - file_type: Type of document (pdf, html, doc)
    - raw_html: The raw HTML content (for HTML pages, stored temporarily)
    - file_content: Binary content of downloaded file (not stored in DB)
    """
    
    # Core metadata from search results
    identifier = scrapy.Field()
    description = scrapy.Field()
    published_date = scrapy.Field()
    document_url = scrapy.Field()
    
    # Scraping context
    body = scrapy.Field()
    partition_date = scrapy.Field()
    
    # Set by storage pipeline
    file_path = scrapy.Field()
    file_hash = scrapy.Field()
    file_type = scrapy.Field()
    
    # Temporary fields (not stored in DB)
    file_content = scrapy.Field()
    raw_html = scrapy.Field()
