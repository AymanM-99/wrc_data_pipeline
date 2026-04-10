"""
Dagster Assets for WRC Scraper Pipeline.

Assets represent data artifacts produced by the pipeline.
Think of them as "things that exist" after a computation runs.

Two main assets:
1. scraped_documents - Raw documents in landing zone (produced by scraper)
2. processed_documents - Transformed documents (depends on scraped_documents)
"""

import sys
import os
import subprocess
from datetime import datetime, timedelta
from typing import Dict, Any

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dagster import (
    asset,
    AssetExecutionContext,
    Config,
    MaterializeResult,
    MetadataValue,
)

from transform.transformer import run_transformation
from config import mongo_config
from utils.database import MongoDBClient
from utils.logging_config import setup_logging

setup_logging()


class DateRangeConfig(Config):
    """
    Configuration for date range parameters.
    
    These are provided when triggering a job run,
    either via UI or command line.
    """
    start_date: str  # Format: YYYY-MM-DD
    end_date: str    # Format: YYYY-MM-DD


@asset(
    description="Raw documents scraped from WRC website and stored in landing zone",
    group_name="ingestion",
    compute_kind="scrapy",
)
def scraped_documents(context: AssetExecutionContext, config: DateRangeConfig) -> MaterializeResult:
    """
    Run the Scrapy spider to scrape documents.
    
    This asset:
    1. Executes the Scrapy spider with date parameters
    2. Spider downloads documents and stores in MinIO
    3. Spider saves metadata to MongoDB (landing_docs)
    
    Returns:
        MaterializeResult with metadata about the scrape
    """
    start_date = config.start_date
    end_date = config.end_date
    
    context.log.info(f"Starting scrape: {start_date} to {end_date}")
    
    # Build scrapy command
    # Run from the scraper directory
    scraper_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'scraper'
    )
    
    cmd = [
        sys.executable, '-m', 'scrapy', 'crawl', 'wrc',
        '-a', f'start_date={start_date}',
        '-a', f'end_date={end_date}',
    ]
    
    context.log.info(f"Running command: {' '.join(cmd)}")
    
    # Execute scrapy
    try:
        result = subprocess.run(
            cmd,
            cwd=scraper_dir,
            capture_output=True,
            text=True,
            timeout=3600  # 1 hour timeout
        )
        
        if result.returncode != 0:
            context.log.error(f"Scrapy failed: {result.stderr}")
            raise Exception(f"Scrapy exited with code {result.returncode}")
        
        context.log.info(f"Scrapy output: {result.stdout[-2000:]}")  # Last 2000 chars
        
    except subprocess.TimeoutExpired:
        context.log.error("Scrapy timed out after 1 hour")
        raise
    
    # Get count from MongoDB
    db_client = MongoDBClient()
    try:
        count = db_client.count_documents(
            mongo_config.landing_collection,
            {"partition_date": {"$gte": start_date[:7], "$lte": end_date[:7]}}
        )
    finally:
        db_client.close()
    
    context.log.info(f"Scrape complete. Documents in landing zone: {count}")
    
    return MaterializeResult(
        metadata={
            "start_date": MetadataValue.text(start_date),
            "end_date": MetadataValue.text(end_date),
            "documents_count": MetadataValue.int(count),
            "storage_location": MetadataValue.text("landing-bucket"),
            "collection": MetadataValue.text(mongo_config.landing_collection),
        }
    )


@asset(
    deps=[scraped_documents],  # Depends on scraped_documents
    description="Processed documents with cleaned HTML, stored in processed zone",
    group_name="transformation",
    compute_kind="python",
)
def processed_documents(context: AssetExecutionContext, config: DateRangeConfig) -> MaterializeResult:
    """
    Run transformation on scraped documents.
    
    This asset:
    1. Reads documents from landing zone
    2. Transforms HTML (extracts relevant content)
    3. Renames files to identifier.extension
    4. Stores in processed zone
    
    Depends on: scraped_documents (won't run until scraping completes)
    
    Returns:
        MaterializeResult with transformation statistics
    """
    start_date = config.start_date
    end_date = config.end_date
    
    context.log.info(f"Starting transformation: {start_date} to {end_date}")
    
    # Run transformation
    stats = run_transformation(start_date, end_date)
    
    context.log.info(f"Transformation complete: {stats}")
    
    return MaterializeResult(
        metadata={
            "start_date": MetadataValue.text(start_date),
            "end_date": MetadataValue.text(end_date),
            "processed": MetadataValue.int(stats['processed']),
            "skipped": MetadataValue.int(stats['skipped']),
            "failed": MetadataValue.int(stats['failed']),
            "html_transformed": MetadataValue.int(stats['html_transformed']),
            "pdf_copied": MetadataValue.int(stats['pdf_copied']),
            "doc_copied": MetadataValue.int(stats['doc_copied']),
            "storage_location": MetadataValue.text("processed-bucket"),
            "collection": MetadataValue.text(mongo_config.processed_collection),
        }
    )
