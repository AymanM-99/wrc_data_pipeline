"""
Structured JSON logging configuration.

Produces logs in JSON format as required by the project specification:
- Current partition being processed
- Body being scraped
- Number of records found vs. successfully scraped
- Failed downloads with URLs and error codes
- Summary at the end of each run
"""

import logging
import json
import sys
from datetime import datetime
from typing import Any, Dict, Optional


class JSONFormatter(logging.Formatter):
    """
    Custom formatter that outputs log records as JSON.
    
    This ensures all logs are machine-readable and can be easily
    parsed by log aggregation tools (ELK, Datadog, etc.)
    """
    
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        
        # Add extra fields if present
        if hasattr(record, 'partition_date'):
            log_data['partition_date'] = record.partition_date
        if hasattr(record, 'body'):
            log_data['body'] = record.body
        if hasattr(record, 'records_found'):
            log_data['records_found'] = record.records_found
        if hasattr(record, 'records_scraped'):
            log_data['records_scraped'] = record.records_scraped
        if hasattr(record, 'url'):
            log_data['url'] = record.url
        if hasattr(record, 'error_code'):
            log_data['error_code'] = record.error_code
        if hasattr(record, 'identifier'):
            log_data['identifier'] = record.identifier
        if hasattr(record, 'error'):
            log_data['error'] = str(record.error)
        if hasattr(record, 'duration_seconds'):
            log_data['duration_seconds'] = record.duration_seconds
        
        # Add exception info if present
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)
        
        return json.dumps(log_data)


class StructuredLogger:
    """
    Logger wrapper that makes it easy to add structured context to logs.
    
    Usage:
        logger = StructuredLogger('scraper')
        logger.info('Starting scrape', partition_date='2024-01', body='Labour Court')
        logger.error('Download failed', url='http://...', error_code=404)
    """
    
    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
    
    def _log(self, level: int, message: str, **kwargs):
        """Internal method to log with extra fields."""
        extra = {k: v for k, v in kwargs.items() if v is not None}
        self.logger.log(level, message, extra=extra)
    
    def debug(self, message: str, **kwargs):
        self._log(logging.DEBUG, message, **kwargs)
    
    def info(self, message: str, **kwargs):
        self._log(logging.INFO, message, **kwargs)
    
    def warning(self, message: str, **kwargs):
        self._log(logging.WARNING, message, **kwargs)
    
    def error(self, message: str, **kwargs):
        self._log(logging.ERROR, message, **kwargs)
    
    def critical(self, message: str, **kwargs):
        self._log(logging.CRITICAL, message, **kwargs)
    
    def log_scrape_start(self, partition_date: str, body: str):
        """Log the start of a scraping partition."""
        self.info(
            "Starting scrape partition",
            partition_date=partition_date,
            body=body
        )
    
    def log_scrape_progress(self, partition_date: str, body: str, 
                            records_found: int, records_scraped: int):
        """Log progress during scraping."""
        self.info(
            "Scrape progress",
            partition_date=partition_date,
            body=body,
            records_found=records_found,
            records_scraped=records_scraped
        )
    
    def log_scrape_complete(self, partition_date: str, body: str,
                            records_found: int, records_scraped: int,
                            duration_seconds: float):
        """Log completion of a scraping partition."""
        self.info(
            "Scrape partition complete",
            partition_date=partition_date,
            body=body,
            records_found=records_found,
            records_scraped=records_scraped,
            duration_seconds=round(duration_seconds, 2)
        )
    
    def log_download_failed(self, url: str, error_code: int, 
                           identifier: Optional[str] = None,
                           error: Optional[str] = None):
        """Log a failed download with details."""
        self.error(
            "Download failed",
            url=url,
            error_code=error_code,
            identifier=identifier,
            error=error
        )
    
    def log_run_summary(self, total_records: int, successful: int, 
                        failed: int, duration_seconds: float,
                        partitions_processed: int):
        """Log summary at the end of a run."""
        self.info(
            "Run complete - Summary",
            records_found=total_records,
            records_scraped=successful,
            records_failed=failed,
            duration_seconds=round(duration_seconds, 2),
            partitions_processed=partitions_processed
        )


def setup_logging(level: str = "INFO", format_type: str = "json"):
    """
    Configure logging for the entire application.
    
    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        format_type: 'json' for structured logs, 'text' for human-readable
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))
    
    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, level.upper()))
    
    if format_type.lower() == 'json':
        console_handler.setFormatter(JSONFormatter())
    else:
        console_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        ))
    
    root_logger.addHandler(console_handler)


def get_logger(name: str) -> StructuredLogger:
    """
    Get a structured logger instance.
    
    Args:
        name: Logger name (usually module name)
    
    Returns:
        StructuredLogger instance
    """
    return StructuredLogger(name)
