"""
Transformation Script for WRC Scraper Pipeline.

This script processes documents from the Landing Zone and stores them
in the Processed Zone.

What it does:
1. Fetches metadata from MongoDB (landing_docs) for a date range
2. Downloads files from MinIO (landing-bucket)
3. For HTML files: Extracts relevant content using BeautifulSoup
4. Renames all files to identifier.extension
5. Calculates new file hash
6. Uploads to MinIO (processed-bucket)
7. Stores metadata in MongoDB (processed_docs)

Usage:
    python -m transform.transformer --start-date 2024-01-01 --end-date 2024-03-31

Note: This does NOT modify the Landing Zone data (as per requirements).
"""

import sys
import os
import argparse
from datetime import datetime
from typing import List, Dict, Any, Optional
import time

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bs4 import BeautifulSoup

from config import mongo_config, minio_config
from utils.database import MongoDBClient
from utils.storage import MinioClient, get_content_type
from utils.logging_config import get_logger, setup_logging

# Setup logging
setup_logging()
logger = get_logger(__name__)


class HTMLContentExtractor:
    """
    Extracts relevant content from HTML pages.
    
    Removes:
    - Navigation bars
    - Headers and footers
    - Buttons and form elements
    - Scripts and styles
    - Cookie notices
    
    Keeps:
    - Main document content
    - Tables (case details)
    - Headings and paragraphs
    """
    
    # Elements to remove (navigation, UI elements, etc.)
    REMOVE_TAGS = [
        'script', 'style', 'nav', 'header', 'footer', 
        'aside', 'form', 'button', 'input', 'select',
        'noscript', 'iframe', 'object', 'embed'
    ]
    
    # Classes/IDs that typically contain navigation or non-content
    REMOVE_CLASSES = [
        'nav', 'navigation', 'menu', 'sidebar', 'footer', 'header',
        'cookie', 'banner', 'advertisement', 'ad', 'social',
        'breadcrumb', 'pagination', 'skip-link', 'toolbar'
    ]
    
    # Classes/IDs that typically contain main content
    CONTENT_CLASSES = [
        'content', 'main', 'article', 'post', 'entry',
        'document', 'case', 'decision', 'determination'
    ]
    
    def extract_content(self, html: str) -> str:
        """
        Extract relevant content from HTML.
        
        Args:
            html: Raw HTML string
        
        Returns:
            Cleaned HTML with only relevant content
        """
        soup = BeautifulSoup(html, 'lxml')
        
        # Remove unwanted tags
        for tag in self.REMOVE_TAGS:
            for element in soup.find_all(tag):
                element.decompose()
        
        # Remove elements with navigation-related classes/IDs
        for class_name in self.REMOVE_CLASSES:
            # Remove by class
            for element in soup.find_all(class_=lambda x: x and class_name in x.lower() if isinstance(x, str) else False):
                element.decompose()
            for element in soup.find_all(class_=lambda x: x and any(class_name in c.lower() for c in x) if isinstance(x, list) else False):
                element.decompose()
            # Remove by ID
            for element in soup.find_all(id=lambda x: x and class_name in x.lower() if x else False):
                element.decompose()
        
        # Try to find main content container
        main_content = None
        
        # Look for semantic main element first
        main_content = soup.find('main')
        
        # If no main, look for article
        if not main_content:
            main_content = soup.find('article')
        
        # If no article, look for content-related classes
        if not main_content:
            for class_name in self.CONTENT_CLASSES:
                main_content = soup.find(class_=lambda x: x and class_name in str(x).lower() if x else False)
                if main_content:
                    break
        
        # If no specific content container found, look for the div with most text
        if not main_content:
            main_content = self._find_content_by_text_density(soup)
        
        # If still nothing, use body
        if not main_content:
            main_content = soup.find('body') or soup
        
        # Clean up the content
        self._clean_content(main_content)
        
        # Return cleaned HTML
        return str(main_content)
    
    def _find_content_by_text_density(self, soup: BeautifulSoup) -> Optional[Any]:
        """
        Find the container with the highest text density.
        
        This is a heuristic: the main content usually has the most text.
        """
        candidates = soup.find_all(['div', 'section'])
        
        if not candidates:
            return None
        
        # Score each candidate by text length
        best_candidate = None
        best_score = 0
        
        for candidate in candidates:
            text = candidate.get_text(strip=True)
            # Prefer containers with substantial text but not the entire page
            if 500 < len(text) < 50000:
                # Score considers text length and depth (shallower is better)
                depth = len(list(candidate.parents))
                score = len(text) / (depth + 1)
                if score > best_score:
                    best_score = score
                    best_candidate = candidate
        
        return best_candidate
    
    def _clean_content(self, element: Any) -> None:
        """
        Clean up content element in place.
        
        - Remove empty elements
        - Remove hidden elements
        - Clean up whitespace
        """
        if element is None:
            return
        
        # Remove elements with display:none or visibility:hidden
        for el in element.find_all(style=lambda x: x and ('display:none' in x or 'display: none' in x or 'visibility:hidden' in x) if x else False):
            el.decompose()
        
        # Remove empty divs and spans (common clutter)
        for el in element.find_all(['div', 'span']):
            if not el.get_text(strip=True) and not el.find(['img', 'table', 'svg']):
                el.decompose()
    
    def extract_text_only(self, html: str) -> str:
        """
        Extract just the text content (no HTML tags).
        
        Useful for text analysis or if HTML structure isn't needed.
        """
        cleaned_html = self.extract_content(html)
        soup = BeautifulSoup(cleaned_html, 'lxml')
        return soup.get_text(separator='\n', strip=True)


class Transformer:
    """
    Main transformation class.
    
    Processes documents from Landing Zone to Processed Zone:
    1. Fetches documents by date range
    2. Downloads files
    3. Transforms HTML files (extracts relevant content)
    4. Renames files to identifier.extension
    5. Stores in processed zone
    """
    
    def __init__(self):
        """Initialize database and storage clients."""
        self.db_client = MongoDBClient()
        self.storage_client = MinioClient()
        self.html_extractor = HTMLContentExtractor()
        
        # Ensure processed bucket exists
        self.storage_client.ensure_buckets()
        
        # Statistics
        self.stats = {
            'processed': 0,
            'skipped': 0,
            'failed': 0,
            'html_transformed': 0,
            'pdf_copied': 0,
            'doc_copied': 0,
        }
    
    def run(self, start_date: str, end_date: str) -> Dict[str, int]:
        """
        Run transformation for a date range.
        
        Args:
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format
        
        Returns:
            Statistics dictionary
        """
        start_time = time.time()
        
        # Convert dates to partition format (YYYY-MM) for querying
        # partition_date in DB is stored as YYYY-MM
        start_partition = start_date[:7]  # "2026-03-01" -> "2026-03"
        end_partition = end_date[:7]      # "2026-03-31" -> "2026-03"
        
        logger.info(
            f"Starting transformation",
            extra={
                'start_date': start_date,
                'end_date': end_date,
                'start_partition': start_partition,
                'end_partition': end_partition
            }
        )
        
        # Fetch documents from landing zone using partition dates
        documents = self.db_client.get_documents_by_date_range(
            collection_name=mongo_config.landing_collection,
            start_date=start_partition,
            end_date=end_partition
        )
        
        logger.info(f"Found {len(documents)} documents to process")
        
        for doc in documents:
            try:
                self._process_document(doc)
            except Exception as e:
                logger.error(
                    f"Failed to process document",
                    extra={
                        'identifier': doc.get('identifier'),
                        'error': str(e)
                    }
                )
                self.stats['failed'] += 1
        
        duration = time.time() - start_time
        
        logger.info(
            f"Transformation complete",
            extra={
                'duration_seconds': round(duration, 2),
                'processed': self.stats['processed'],
                'skipped': self.stats['skipped'],
                'failed': self.stats['failed'],
                'html_transformed': self.stats['html_transformed'],
                'pdf_copied': self.stats['pdf_copied'],
                'doc_copied': self.stats['doc_copied'],
            }
        )
        
        return self.stats
    
    def _process_document(self, doc: Dict[str, Any]) -> None:
        """
        Process a single document.
        
        Args:
            doc: Document metadata from MongoDB
        """
        identifier = doc.get('identifier')
        file_type = doc.get('file_type', 'html')
        file_path = doc.get('file_path', '')
        
        if not identifier or not file_path:
            logger.warning(f"Skipping document with missing data: {doc.get('_id')}")
            self.stats['skipped'] += 1
            return
        
        # Check if already processed with same hash (idempotency)
        existing = self.db_client.get_document_by_identifier(
            mongo_config.processed_collection,
            identifier
        )
        
        if existing and existing.get('source_hash') == doc.get('file_hash'):
            logger.debug(f"Document already processed: {identifier}")
            self.stats['skipped'] += 1
            return
        
        # Parse file path to get bucket and object name
        # Format: "bucket-name/partition/filename.ext"
        path_parts = file_path.split('/', 1)
        if len(path_parts) != 2:
            logger.error(f"Invalid file path format: {file_path}")
            self.stats['failed'] += 1
            return
        
        source_bucket = path_parts[0]
        source_object = path_parts[1]
        
        # Download file from landing zone
        content = self.storage_client.download_file(source_bucket, source_object)
        
        if content is None:
            logger.error(f"Failed to download file: {file_path}")
            self.stats['failed'] += 1
            return
        
        # Process based on file type
        if file_type == 'html':
            # Transform HTML - extract relevant content
            try:
                html_str = content.decode('utf-8', errors='replace')
                cleaned_html = self.html_extractor.extract_content(html_str)
                content = cleaned_html.encode('utf-8')
                self.stats['html_transformed'] += 1
            except Exception as e:
                logger.warning(
                    f"HTML transformation failed, using original: {identifier}",
                    extra={'error': str(e)}
                )
        elif file_type == 'pdf':
            # PDF - no transformation, just copy
            self.stats['pdf_copied'] += 1
        elif file_type in ('doc', 'docx'):
            # DOC/DOCX - no transformation, just copy
            self.stats['doc_copied'] += 1
        
        # Calculate new hash
        new_hash = self.storage_client.calculate_hash(content)
        
        # Create new filename: identifier.extension
        new_filename = f"{identifier}.{file_type}"
        
        # Upload to processed bucket
        # Organize by partition date
        partition_date = doc.get('partition_date', 'unknown')
        new_object_name = f"{partition_date}/{new_filename}"
        content_type = get_content_type(new_filename)
        
        success, _ = self.storage_client.upload_file(
            bucket_name=minio_config.processed_bucket,
            object_name=new_object_name,
            content=content,
            content_type=content_type
        )
        
        if not success:
            logger.error(f"Failed to upload processed file: {identifier}")
            self.stats['failed'] += 1
            return
        
        # Store metadata in processed collection
        processed_doc = {
            'identifier': identifier,
            'description': doc.get('description', ''),
            'published_date': doc.get('published_date', ''),
            'document_url': doc.get('document_url', ''),
            'body': doc.get('body', ''),
            'partition_date': partition_date,
            'file_path': f"{minio_config.processed_bucket}/{new_object_name}",
            'file_hash': new_hash,
            'file_type': file_type,
            # Track source for idempotency
            'source_hash': doc.get('file_hash'),
            'source_path': file_path,
        }
        
        success = self.db_client.upsert_document(
            mongo_config.processed_collection,
            processed_doc
        )
        
        if success:
            logger.info(
                f"Processed document",
                extra={
                    'identifier': identifier,
                    'file_type': file_type,
                    'new_path': processed_doc['file_path']
                }
            )
            self.stats['processed'] += 1
        else:
            logger.error(f"Failed to store processed metadata: {identifier}")
            self.stats['failed'] += 1
    
    def close(self):
        """Clean up resources."""
        if self.db_client:
            self.db_client.close()


def run_transformation(start_date: str, end_date: str) -> Dict[str, int]:
    """
    Run transformation as a function (for Dagster integration).
    
    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
    
    Returns:
        Statistics dictionary
    """
    transformer = Transformer()
    try:
        return transformer.run(start_date, end_date)
    finally:
        transformer.close()


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Transform documents from Landing Zone to Processed Zone'
    )
    parser.add_argument(
        '--start-date',
        required=True,
        help='Start date (YYYY-MM-DD format)'
    )
    parser.add_argument(
        '--end-date',
        required=True,
        help='End date (YYYY-MM-DD format)'
    )
    
    args = parser.parse_args()
    
    # Validate date format
    try:
        datetime.strptime(args.start_date, '%Y-%m-%d')
        datetime.strptime(args.end_date, '%Y-%m-%d')
    except ValueError as e:
        print(f"Error: Invalid date format. Use YYYY-MM-DD. {e}")
        sys.exit(1)
    
    # Run transformation
    stats = run_transformation(args.start_date, args.end_date)
    
    # Print summary
    print("\n=== Transformation Summary ===")
    print(f"Processed: {stats['processed']}")
    print(f"Skipped (already processed): {stats['skipped']}")
    print(f"Failed: {stats['failed']}")
    print(f"  - HTML transformed: {stats['html_transformed']}")
    print(f"  - PDF copied: {stats['pdf_copied']}")
    print(f"  - DOC copied: {stats['doc_copied']}")


if __name__ == '__main__':
    main()
