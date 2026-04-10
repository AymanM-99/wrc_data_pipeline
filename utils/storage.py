"""
MinIO client wrapper for WRC Scraper Pipeline.

Provides methods for uploading and downloading documents from
S3-compatible object storage (MinIO locally, can be swapped to AWS S3).
"""

import hashlib
from io import BytesIO
from typing import Optional, Tuple
from minio import Minio
from minio.error import S3Error

from config import minio_config
from utils.logging_config import get_logger

logger = get_logger(__name__)


class MinioClient:
    """
    MinIO client wrapper with methods specific to the WRC scraper.
    
    Handles:
    - File upload/download
    - Hash calculation
    - Bucket management
    """
    
    def __init__(self):
        """Initialize MinIO connection."""
        self.client: Optional[Minio] = None
        self._connect()
    
    def _connect(self):
        """Establish connection to MinIO."""
        try:
            self.client = Minio(
                endpoint=minio_config.endpoint,
                access_key=minio_config.root_user,
                secret_key=minio_config.root_password,
                secure=minio_config.secure
            )
            logger.info("Connected to MinIO", endpoint=minio_config.endpoint)
        except Exception as e:
            logger.error("Failed to connect to MinIO", error=str(e))
            raise
    
    def ensure_buckets(self):
        """Ensure required buckets exist."""
        for bucket_name in [minio_config.landing_bucket, minio_config.processed_bucket]:
            try:
                if not self.client.bucket_exists(bucket_name):
                    self.client.make_bucket(bucket_name)
                    logger.info(f"Created bucket: {bucket_name}")
                else:
                    logger.debug(f"Bucket exists: {bucket_name}")
            except S3Error as e:
                logger.error(f"Failed to create bucket: {bucket_name}", error=str(e))
                raise
    
    @staticmethod
    def calculate_hash(content: bytes) -> str:
        """
        Calculate SHA256 hash of file content.
        
        Used for:
        - Detecting changes between runs (idempotency)
        - Verifying file integrity
        
        Args:
            content: File content as bytes
        
        Returns:
            SHA256 hash as hex string
        """
        return hashlib.sha256(content).hexdigest()
    
    def upload_file(
        self,
        bucket_name: str,
        object_name: str,
        content: bytes,
        content_type: str = "application/octet-stream"
    ) -> Tuple[bool, Optional[str]]:
        """
        Upload a file to MinIO.
        
        Args:
            bucket_name: Target bucket name
            object_name: Name of the object (path in bucket)
            content: File content as bytes
            content_type: MIME type of the file
        
        Returns:
            Tuple of (success: bool, file_hash: str or None)
        """
        try:
            file_hash = self.calculate_hash(content)
            
            self.client.put_object(
                bucket_name=bucket_name,
                object_name=object_name,
                data=BytesIO(content),
                length=len(content),
                content_type=content_type
            )
            
            logger.debug(
                "File uploaded",
                bucket=bucket_name,
                object_name=object_name,
                size_bytes=len(content)
            )
            
            return True, file_hash
        except S3Error as e:
            logger.error(
                "Failed to upload file",
                bucket=bucket_name,
                object_name=object_name,
                error=str(e)
            )
            return False, None
    
    def download_file(self, bucket_name: str, object_name: str) -> Optional[bytes]:
        """
        Download a file from MinIO.
        
        Args:
            bucket_name: Source bucket name
            object_name: Name of the object
        
        Returns:
            File content as bytes, or None on error
        """
        try:
            response = self.client.get_object(bucket_name, object_name)
            content = response.read()
            response.close()
            response.release_conn()
            
            return content
        except S3Error as e:
            logger.error(
                "Failed to download file",
                bucket=bucket_name,
                object_name=object_name,
                error=str(e)
            )
            return None
    
    def file_exists(self, bucket_name: str, object_name: str) -> bool:
        """
        Check if a file exists in MinIO.
        
        Args:
            bucket_name: Bucket name
            object_name: Name of the object
        
        Returns:
            True if file exists, False otherwise
        """
        try:
            self.client.stat_object(bucket_name, object_name)
            return True
        except S3Error:
            return False
    
    def get_file_hash_from_storage(self, bucket_name: str, 
                                   object_name: str) -> Optional[str]:
        """
        Download file and calculate its hash.
        
        Used for comparing with stored hash to detect changes.
        
        Args:
            bucket_name: Bucket name
            object_name: Name of the object
        
        Returns:
            SHA256 hash or None if file doesn't exist
        """
        content = self.download_file(bucket_name, object_name)
        if content:
            return self.calculate_hash(content)
        return None
    
    def list_objects(self, bucket_name: str, prefix: str = "") -> list:
        """
        List objects in a bucket with optional prefix filter.
        
        Args:
            bucket_name: Bucket name
            prefix: Optional prefix to filter objects
        
        Returns:
            List of object names
        """
        try:
            objects = self.client.list_objects(bucket_name, prefix=prefix)
            return [obj.object_name for obj in objects]
        except S3Error as e:
            logger.error(
                "Failed to list objects",
                bucket=bucket_name,
                prefix=prefix,
                error=str(e)
            )
            return []
    
    def delete_object(self, bucket_name: str, object_name: str) -> bool:
        """
        Delete an object from MinIO.
        
        Args:
            bucket_name: Bucket name
            object_name: Name of the object
        
        Returns:
            True if deleted, False on error
        """
        try:
            self.client.remove_object(bucket_name, object_name)
            return True
        except S3Error as e:
            logger.error(
                "Failed to delete object",
                bucket=bucket_name,
                object_name=object_name,
                error=str(e)
            )
            return False


def get_content_type(filename: str) -> str:
    """
    Determine content type based on file extension.
    
    Args:
        filename: Name of the file
    
    Returns:
        MIME type string
    """
    extension = filename.lower().split('.')[-1] if '.' in filename else ''
    
    content_types = {
        'pdf': 'application/pdf',
        'doc': 'application/msword',
        'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'html': 'text/html',
        'htm': 'text/html',
        'txt': 'text/plain',
    }
    
    return content_types.get(extension, 'application/octet-stream')
