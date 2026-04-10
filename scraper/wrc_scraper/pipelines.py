"""
Scrapy Pipelines for WRC Scraper.

Pipelines process items after they are scraped by spiders.
Similar to Django's post_save signals, but for scraped data.

Pipeline order (lower number = runs first):
1. ValidationPipeline (100) - Validate required fields
2. FileDownloadPipeline (200) - Download document files
3. StoragePipeline (300) - Store to MinIO + MongoDB
"""

import sys
import os
import hashlib
import requests
from urllib.parse import urljoin

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scrapy.exceptions import DropItem
from config import mongo_config, minio_config, WRC_BASE_URL
from utils.database import MongoDBClient
from utils.storage import MinioClient, get_content_type
from utils.logging_config import get_logger, setup_logging

# Setup logging
setup_logging()
logger = get_logger(__name__)


class ValidationPipeline:
    """
    Validates that items have required fields before processing.
    
    Why: Prevents incomplete records from being stored in the database.
    Items missing required fields are dropped and logged.
    """
    
    REQUIRED_FIELDS = ['identifier', 'document_url', 'body', 'partition_date']
    
    def process_item(self, item, spider):
        """Validate item has required fields."""
        missing_fields = [
            field for field in self.REQUIRED_FIELDS 
            if not item.get(field)
        ]
        
        if missing_fields:
            logger.error(
                f"Item missing required fields: {missing_fields}",
                extra={'identifier': item.get('identifier', 'unknown')}
            )
            raise DropItem(f"Missing fields: {missing_fields}")
        
        return item


class FileDownloadPipeline:
    """
    Downloads document files (PDF, DOC, HTML pages).
    
    Why: The specification requires storing actual documents, not just metadata.
    - PDFs/DOCs: Downloaded directly and stored as-is
    - HTML pages: Page is fetched and stored as .html file
    """
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'WRC-Legal-Scraper/1.0'
        })
    
    def process_item(self, item, spider):
        """Download the document file."""
        document_url = item.get('document_url')
        if not document_url:
            return item
        
        # Make URL absolute if relative
        if document_url.startswith('/'):
            document_url = urljoin(WRC_BASE_URL, document_url)
        
        try:
            response = self.session.get(document_url, timeout=30)
            response.raise_for_status()
            
            # Determine file type from URL or content-type
            content_type = response.headers.get('Content-Type', '')
            
            if 'pdf' in content_type or document_url.lower().endswith('.pdf'):
                item['file_type'] = 'pdf'
                item['file_content'] = response.content
            elif 'msword' in content_type or document_url.lower().endswith('.doc'):
                item['file_type'] = 'doc'
                item['file_content'] = response.content
            elif 'wordprocessingml' in content_type or document_url.lower().endswith('.docx'):
                item['file_type'] = 'docx'
                item['file_content'] = response.content
            else:
                # Assume HTML page
                item['file_type'] = 'html'
                item['file_content'] = response.content
                item['raw_html'] = response.text
            
            logger.debug(
                f"Downloaded {item['file_type']} file",
                extra={
                    'identifier': item['identifier'],
                    'url': document_url,
                    'size_bytes': len(response.content)
                }
            )
            
        except requests.RequestException as e:
            logger.error(
                f"Failed to download file",
                extra={
                    'identifier': item['identifier'],
                    'url': document_url,
                    'error': str(e),
                    'error_code': getattr(e.response, 'status_code', None) if hasattr(e, 'response') else None
                }
            )
            # Track failed download in spider stats
            if hasattr(spider, 'stats'):
                spider.stats['records_failed'] = spider.stats.get('records_failed', 0) + 1
                spider.stats.setdefault('failed_urls', []).append({
                    'url': document_url,
                    'identifier': item['identifier'],
                    'error': str(e)
                })
            raise DropItem(f"Download failed: {e}")
        
        return item


class StoragePipeline:
    """
    Stores items to MinIO (files) and MongoDB (metadata).
    
    Why: The specification requires:
    - Files stored in object storage (MinIO)
    - Metadata stored in NoSQL DB (MongoDB)
    - File hash stored for idempotency checks
    - Path to file stored in metadata
    
    Idempotency: If a file with the same hash already exists,
    we skip re-uploading and just update metadata if needed.
    """
    
    def __init__(self):
        self.db_client = None
        self.storage_client = None
    
    def open_spider(self, spider):
        """Initialize clients when spider starts."""
        self.db_client = MongoDBClient()
        self.db_client.ensure_indexes()
        
        self.storage_client = MinioClient()
        self.storage_client.ensure_buckets()
        
        logger.info("Storage pipeline initialized")
    
    def close_spider(self, spider):
        """Clean up when spider finishes."""
        if self.db_client:
            self.db_client.close()
        logger.info("Storage pipeline closed")
    
    def process_item(self, item, spider):
        """Store file and metadata."""
        file_content = item.get('file_content')
        if not file_content:
            logger.warning(f"No file content for {item['identifier']}")
            return item
        
        identifier = item['identifier']
        file_type = item['file_type']
        
        # Generate file name: identifier.extension (e.g., ADJ-00054658.pdf)
        # Note: For landing zone, we keep original names
        # Transformation phase will rename to identifier.ext
        file_name = f"{identifier}.{file_type}"
        
        # Check if file already exists with same hash (idempotency)
        new_hash = self.storage_client.calculate_hash(file_content)
        existing_doc = self.db_client.get_document_by_identifier(
            mongo_config.landing_collection, 
            identifier
        )
        
        if existing_doc and existing_doc.get('file_hash') == new_hash:
            # File hasn't changed - skip upload
            logger.debug(f"File unchanged, skipping upload: {identifier}")
            item['file_hash'] = new_hash
            item['file_path'] = existing_doc.get('file_path')
        else:
            # Upload file to MinIO
            object_name = f"{item['partition_date']}/{file_name}"
            content_type = get_content_type(file_name)
            
            success, file_hash = self.storage_client.upload_file(
                bucket_name=minio_config.landing_bucket,
                object_name=object_name,
                content=file_content,
                content_type=content_type
            )
            
            if success:
                item['file_hash'] = file_hash
                item['file_path'] = f"{minio_config.landing_bucket}/{object_name}"
                logger.info(
                    f"Uploaded file to MinIO",
                    extra={
                        'identifier': identifier,
                        'path': item['file_path'],
                        'hash': file_hash[:16] + '...'
                    }
                )
            else:
                logger.error(f"Failed to upload file to MinIO: {identifier}")
                raise DropItem(f"MinIO upload failed: {identifier}")
        
        # Store metadata in MongoDB
        metadata = {
            'identifier': item['identifier'],
            'description': item.get('description', ''),
            'published_date': item.get('published_date', ''),
            'document_url': item.get('document_url', ''),
            'body': item['body'],
            'partition_date': item['partition_date'],
            'file_path': item['file_path'],
            'file_hash': item['file_hash'],
            'file_type': item['file_type'],
        }
        
        success = self.db_client.upsert_document(
            mongo_config.landing_collection,
            metadata
        )
        
        if success:
            logger.info(
                f"Stored metadata in MongoDB",
                extra={'identifier': identifier}
            )
            # Track successful scrape in spider stats
            if hasattr(spider, 'stats'):
                spider.stats['records_scraped'] = spider.stats.get('records_scraped', 0) + 1
        else:
            logger.error(f"Failed to store metadata: {identifier}")
            raise DropItem(f"MongoDB insert failed: {identifier}")
        
        # Clear file content from item (not needed anymore)
        del item['file_content']
        if 'raw_html' in item:
            del item['raw_html']
        
        return item
