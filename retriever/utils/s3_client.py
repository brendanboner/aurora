"""
S3 Document Storage Service

Handles document storage and retrieval from AWS S3 for user uploads.
"""

import boto3
from botocore.exceptions import ClientError
import hashlib
from datetime import datetime
import logging
from typing import Optional
from settings import settings

logger = logging.getLogger(__name__)


def get_content_hash(file_content: bytes) -> str:
    """Generate SHA256 hash of file content for duplicate detection."""
    return hashlib.sha256(file_content).hexdigest()


class S3DocumentStorage:
    """Handle document storage in AWS S3."""
    
    def __init__(self):
        self.s3_client = boto3.client(
            's3',
            region_name=settings.aws_region,
            # Credentials from environment or IAM role
        )
        self.bucket_name = settings.s3_document_bucket
        logger.info(f"S3DocumentStorage initialized with bucket: {self.bucket_name}")
    
    async def upload_document(
        self, 
        file_content: bytes, 
        original_filename: str, 
        user_uuid: str,
        content_type: str
    ) -> dict:
        """
        Upload a document to S3.
        
        Args:
            file_content: Raw file bytes
            original_filename: Original filename from upload
            user_uuid: UUID of the user uploading the document
            content_type: MIME type of the file
        
        Returns:
            dict with s3_key, s3_bucket, s3_url, file_size_bytes, content_hash
        """
        s3_key = f"uploads/{user_uuid}/{original_filename}"
        s3_url = f"s3://{self.bucket_name}/{s3_key}"
        content_hash = get_content_hash(file_content)
        
        try:
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=s3_key,
                Body=file_content,
                ContentType=content_type,
                Metadata={
                    'uploaded-by': user_uuid,
                    'original-filename': original_filename,
                    'upload-timestamp': datetime.utcnow().isoformat(),
                    'content-hash': content_hash
                },
                ServerSideEncryption='AES256'  # Server-side encryption
            )
            
            logger.info(f"Uploaded document to S3: {s3_key} ({len(file_content)} bytes)")
            
            return {
                's3_bucket': self.bucket_name,
                's3_key': s3_key,
                's3_url': s3_url,
                'file_size_bytes': len(file_content),
                'content_hash': content_hash
            }
            
        except ClientError as e:
            logger.error(f"Failed to upload document to S3: {e}")
            raise
    
    def generate_presigned_url(self, s3_key: str, expiration: int = 3600) -> str:
        """
        Generate a presigned URL for secure document download.
        
        Args:
            s3_key: The S3 object key
            expiration: URL expiration time in seconds (default 1 hour)
            
        Returns:
            Presigned URL string
        """
        try:
            url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': self.bucket_name,
                    'Key': s3_key
                },
                ExpiresIn=expiration
            )
            logger.debug(f"Generated presigned URL for {s3_key} (expires in {expiration}s)")
            return url
        except ClientError as e:
            logger.error(f"Failed to generate presigned URL: {e}")
            raise
    
    async def delete_document(self, s3_key: str) -> bool:
        """
        Delete a document from S3.
        
        Args:
            s3_key: The S3 object key to delete
            
        Returns:
            True if deleted successfully, False otherwise
        """
        try:
            self.s3_client.delete_object(
                Bucket=self.bucket_name,
                Key=s3_key
            )
            logger.info(f"Deleted document from S3: {s3_key}")
            return True
        except ClientError as e:
            logger.error(f"Failed to delete document from S3: {e}")
            return False
    
    def check_document_exists(self, s3_key: str) -> bool:
        """
        Check if a document exists in S3.
        
        Args:
            s3_key: The S3 object key to check
            
        Returns:
            True if exists, False otherwise
        """
        try:
            self.s3_client.head_object(
                Bucket=self.bucket_name,
                Key=s3_key
            )
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                return False
            logger.error(f"Error checking document existence: {e}")
            raise
    
    def get_document_metadata(self, s3_key: str) -> Optional[dict]:
        """
        Get metadata for a document in S3.
        
        Args:
            s3_key: The S3 object key
            
        Returns:
            dict with metadata or None if not found
        """
        try:
            response = self.s3_client.head_object(
                Bucket=self.bucket_name,
                Key=s3_key
            )
            return {
                'content_type': response.get('ContentType'),
                'content_length': response.get('ContentLength'),
                'last_modified': response.get('LastModified'),
                'metadata': response.get('Metadata', {})
            }
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                return None
            logger.error(f"Error getting document metadata: {e}")
            raise
