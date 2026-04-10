"""
MongoDB client wrapper for WRC Scraper Pipeline.

Provides a clean interface for storing and retrieving document metadata.
Handles connection management, upserts for idempotency, and queries.
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.collection import Collection
from pymongo.database import Database

from config import mongo_config
from utils.logging_config import get_logger

logger = get_logger(__name__)


class MongoDBClient:
    """
    MongoDB client wrapper with methods specific to the WRC scraper.
    
    Handles:
    - Connection management
    - Upsert operations for idempotency
    - Querying by date range
    - Index creation for performance
    """
    
    def __init__(self):
        """Initialize MongoDB connection."""
        self.client: Optional[MongoClient] = None
        self.db: Optional[Database] = None
        self._connect()
    
    def _connect(self):
        """Establish connection to MongoDB."""
        try:
            self.client = MongoClient(mongo_config.connection_string)
            self.db = self.client[mongo_config.database]
            # Test connection
            self.client.admin.command('ping')
            logger.info("Connected to MongoDB", 
                       host=mongo_config.host, 
                       database=mongo_config.database)
        except Exception as e:
            logger.error("Failed to connect to MongoDB", error=str(e))
            raise
    
    def _get_collection(self, collection_name: str) -> Collection:
        """Get a collection by name."""
        return self.db[collection_name]
    
    @property
    def landing_collection(self) -> Collection:
        """Get the landing zone collection."""
        return self._get_collection(mongo_config.landing_collection)
    
    @property
    def processed_collection(self) -> Collection:
        """Get the processed zone collection."""
        return self._get_collection(mongo_config.processed_collection)
    
    def ensure_indexes(self):
        """
        Create indexes for optimal query performance.
        
        Indexes:
        - identifier: unique, for deduplication and lookups
        - partition_date: for date-range queries
        - file_hash: for change detection
        - body + partition_date: compound index for filtered queries
        """
        for collection in [self.landing_collection, self.processed_collection]:
            # Unique index on identifier to prevent duplicates
            collection.create_index(
                [("identifier", ASCENDING)],
                unique=True,
                name="idx_identifier"
            )
            # Index for date range queries
            collection.create_index(
                [("partition_date", DESCENDING)],
                name="idx_partition_date"
            )
            # Index for hash-based change detection
            collection.create_index(
                [("file_hash", ASCENDING)],
                name="idx_file_hash"
            )
            # Compound index for body + date queries
            collection.create_index(
                [("body", ASCENDING), ("partition_date", DESCENDING)],
                name="idx_body_partition"
            )
        
        logger.info("Database indexes created/verified")
    
    def upsert_document(self, collection_name: str, document: Dict[str, Any]) -> bool:
        """
        Insert or update a document based on identifier.
        
        This ensures idempotency - running the scraper multiple times
        won't create duplicate records.
        
        Timestamps:
        - created_at: Set only on first insert (never overwritten)
        - updated_at: Updated every time the document is modified
        
        Args:
            collection_name: Name of the collection
            document: Document data with 'identifier' field
        
        Returns:
            True if document was inserted/updated, False on error
        """
        try:
            collection = self._get_collection(collection_name)
            
            # Remove created_at from document if present (we'll handle it separately)
            document.pop('created_at', None)
            
            # Set updated_at to current time
            now = datetime.utcnow()
            document['updated_at'] = now
            
            result = collection.update_one(
                {"identifier": document["identifier"]},
                {
                    "$set": document,           # Always update these fields
                    "$setOnInsert": {           # Only set on first insert
                        "created_at": now
                    }
                },
                upsert=True
            )
            
            return True
        except Exception as e:
            logger.error(
                "Failed to upsert document",
                identifier=document.get("identifier"),
                error=str(e)
            )
            return False
    
    def get_document_by_identifier(self, collection_name: str, 
                                   identifier: str) -> Optional[Dict[str, Any]]:
        """
        Get a document by its identifier.
        
        Args:
            collection_name: Name of the collection
            identifier: Document identifier (e.g., 'ADJ-00054658')
        
        Returns:
            Document dict or None if not found
        """
        try:
            collection = self._get_collection(collection_name)
            return collection.find_one({"identifier": identifier})
        except Exception as e:
            logger.error(
                "Failed to get document",
                identifier=identifier,
                error=str(e)
            )
            return None
    
    def get_documents_by_date_range(
        self,
        collection_name: str,
        start_date: str,
        end_date: str,
        body: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get documents within a date range.
        
        Args:
            collection_name: Name of the collection
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format
            body: Optional filter by body
        
        Returns:
            List of documents
        """
        try:
            collection = self._get_collection(collection_name)
            
            query = {
                "partition_date": {
                    "$gte": start_date,
                    "$lte": end_date
                }
            }
            
            if body:
                query["body"] = body
            
            return list(collection.find(query))
        except Exception as e:
            logger.error(
                "Failed to query documents by date range",
                start_date=start_date,
                end_date=end_date,
                error=str(e)
            )
            return []
    
    def get_existing_hashes(self, collection_name: str, 
                           identifiers: List[str]) -> Dict[str, str]:
        """
        Get file hashes for a list of identifiers.
        
        Used for change detection - if hash matches, skip re-download.
        
        Args:
            collection_name: Name of the collection
            identifiers: List of document identifiers
        
        Returns:
            Dict mapping identifier to file_hash
        """
        try:
            collection = self._get_collection(collection_name)
            
            docs = collection.find(
                {"identifier": {"$in": identifiers}},
                {"identifier": 1, "file_hash": 1}
            )
            
            return {doc["identifier"]: doc.get("file_hash") for doc in docs}
        except Exception as e:
            logger.error(
                "Failed to get existing hashes",
                error=str(e)
            )
            return {}
    
    def count_documents(self, collection_name: str, 
                       query: Optional[Dict] = None) -> int:
        """Count documents in a collection."""
        try:
            collection = self._get_collection(collection_name)
            return collection.count_documents(query or {})
        except Exception as e:
            logger.error("Failed to count documents", error=str(e))
            return 0
    
    def close(self):
        """Close MongoDB connection."""
        if self.client:
            self.client.close()
            logger.info("MongoDB connection closed")
