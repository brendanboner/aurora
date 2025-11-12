from typing import Dict, Any, List
from datetime import datetime
from dateutil import parser
from utils.logger import setup_logger
from settings import settings


logger = setup_logger(__name__, settings.log_level)


class MetadataValidator:
    """Validate extracted metadata."""
    
    @staticmethod
    def validate_metadata(metadata: Dict[str, Any]) -> bool:
        """
        Validate that metadata contains required fields and correct types.
        
        Args:
            metadata: The metadata dictionary to validate
            
        Returns:
            True if valid, raises ValueError if invalid
        """
        required_fields = [
            "title", "url", "category", "datasource_id", "summary", "scraped_at", "content_hash"
        ]
        
        # Check required fields
        for field in required_fields:
            if field not in metadata:
                raise ValueError(f"Missing required field: {field}")
            if not metadata[field]:
                raise ValueError(f"Field cannot be empty: {field}")
        
        # Validate list fields
        list_fields = [
            "topics", "standards", "standard_editions",
        ]
        
        for field in list_fields:
            if field in metadata:
                if not isinstance(metadata[field], list):
                    raise ValueError(f"Field must be a list: {field}")
                # Ensure all items are strings
                metadata[field] = [str(item).strip() for item in metadata[field] if item]
        
        # Validate URL format
        url = metadata.get("url", "")
        if not (url.startswith("http://") or url.startswith("https://")):
            logger.warning(f"Invalid URL format: {url}")
        
        # Validate publish_date if present
        if "publish_date" in metadata and metadata["publish_date"]:
            try:
                MetadataValidator.parse_date(metadata["publish_date"])
            except Exception as e:
                logger.warning(f"Invalid publish_date: {metadata['publish_date']}, error: {e}")
                metadata["publish_date"] = None
        
        logger.info("Metadata validation passed")
        return True
    
    @staticmethod
    def parse_date(date_str: str) -> datetime:
        """Parse a date string into a datetime object."""
        if not date_str:
            return None
        try:
            return parser.parse(date_str)
        except Exception as e:
            logger.error(f"Failed to parse date: {date_str}, error: {e}")
            return None
