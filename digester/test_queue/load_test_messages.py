#!/usr/bin/env python3
"""Load test messages from JSON files into RabbitMQ queue."""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import List, Dict, Any

# Add parent directory to path to import rabbitmq_client
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from rabbitmq_client.producer import RabbitMQProducer


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Silence noisy third-party loggers commonly used by pika
for noisy in ('pika', 'pika.adapters', 'pika.frame', 'urllib3'):
    logging.getLogger(noisy).setLevel(logging.WARNING)


def load_json_file(file_path: Path) -> List[Dict[str, Any]]:
    """
    Load messages from a JSON file.
    
    Args:
        file_path: Path to the JSON file
        
    Returns:
        List of message dictionaries
    """
    logger.info(f"Loading messages from {file_path}")
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Ensure data is a list
        if not isinstance(data, list):
            data = [data]
        
        logger.info(f"Loaded {len(data)} messages from {file_path}")
        return data
        
    except FileNotFoundError:
        logger.error(f"File not found: {file_path}")
        raise
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in {file_path}: {e}")
        raise
    except Exception as e:
        logger.error(f"Error loading {file_path}: {e}")
        raise


def get_test_message_files(test_messages_dir: Path, file_pattern: str = None) -> List[Path]:
    """
    Get list of test message JSON files.
    
    Args:
        test_messages_dir: Directory containing test message files
        file_pattern: Optional specific file name or pattern (e.g., 'wfa_test_messages.json' or '*.json')
        
    Returns:
        List of Path objects for JSON files
    """
    if file_pattern and not file_pattern.endswith('.json'):
        file_pattern = f"{file_pattern}.json"
    
    if file_pattern and '*' not in file_pattern:
        # Specific file requested
        file_path = test_messages_dir / file_pattern
        if file_path.exists():
            return [file_path]
        else:
            logger.error(f"Requested file not found: {file_path}")
            return []
    else:
        # Get all JSON files or files matching pattern
        pattern = file_pattern or "*.json"
        json_files = sorted(test_messages_dir.glob(pattern))
        # Exclude the load script itself if it's picked up
        json_files = [f for f in json_files if f.name != 'load_test_messages.json']
        return json_files


def main():
    """Main entry point for loading test messages."""
    parser = argparse.ArgumentParser(
        description='Load test messages from JSON files into RabbitMQ queue',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Load default file (wfa_test_messages.json)
  python load_test_messages.py
  
  # Load specific file
  python load_test_messages.py --file wfa_test_messages.json
  
  # Load all JSON files in directory
  python load_test_messages.py --file all
  
  # Load with custom RabbitMQ settings
  python load_test_messages.py --host localhost --port 5672 --queue scraped_content
"""
    )
    
    parser.add_argument(
        '--host',
        type=str,
        default='localhost',
        help='RabbitMQ host (default: localhost)'
    )
    parser.add_argument(
        '--port',
        type=int,
        default=5672,
        help='RabbitMQ port (default: 5672)'
    )
    parser.add_argument(
        '--user',
        type=str,
        default='user',
        help='RabbitMQ username (default: user)'
    )
    parser.add_argument(
        '--password',
        type=str,
        default='password',
        help='RabbitMQ password (default: password)'
    )
    parser.add_argument(
        '--queue',
        type=str,
        default='scraped_content',
        help='RabbitMQ queue name (default: scraped_content)'
    )
    parser.add_argument(
        '--file',
        type=str,
        default='wfa_public.json',
        help='JSON file to load (default: wfa_public.json). Use "all" to load all JSON files.'
    )
    
    args = parser.parse_args()
    
    # Get directory containing test messages
    # New structure: script is under digester/test_queue/, messages live in digester/test_queue/test_messages
    test_messages_dir = Path(__file__).parent / 'test_messages'
    
    # Determine which files to load
    if args.file.lower() == 'all':
        json_files = get_test_message_files(test_messages_dir, "*.json")
    else:
        json_files = get_test_message_files(test_messages_dir, args.file)
    
    if not json_files:
        logger.error("No test message files found!")
        sys.exit(1)
    
    logger.info(f"Found {len(json_files)} test message file(s) to load")
    
    # Load all messages from all files
    all_messages = []
    for json_file in json_files:
        try:
            messages = load_json_file(json_file)
            all_messages.extend(messages)
        except Exception as e:
            logger.error(f"Failed to load {json_file}: {e}")
            sys.exit(1)
    
    if not all_messages:
        logger.error("No messages to publish!")
        sys.exit(1)
    
    logger.info(f"Total messages to publish: {len(all_messages)}")
    
    # Publish messages to RabbitMQ
    try:
        with RabbitMQProducer(
            host=args.host,
            port=args.port,
            user=args.user,
            password=args.password,
            queue=args.queue,
            logger_instance=logger
        ) as producer:
            logger.info(f"Publishing {len(all_messages)} messages to queue '{args.queue}'")
            producer.publish_batch(all_messages, persistent=True)
            logger.info("✅ All messages published successfully!")
            
    except Exception as e:
        logger.error(f"Failed to publish messages: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
