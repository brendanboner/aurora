# Messaging Client Library

A shared Python library for interacting with RabbitMQ across Aurora microservices.

## Overview

`rabbitmq-client` provides a standardized interface for all Aurora microservices to publish and consume messages via RabbitMQ. It supports both producer and consumer patterns with automatic JSON serialization.

## Installation

### Development Installation (Editable)

From the Aurora root directory:

```bash
pip install -e ./rabbitmq-client
```

### In Microservices

Add to your `requirements.txt`:

```
-e ../rabbitmq-client
```

## Usage

### Consumer Pattern (Digester Service)

```python
from rabbitmq_client import RabbitMQConsumer

def process_message(message: dict) -> bool:
    """Process a message. Return True if successful."""
    try:
        print(f"Processing: {message['title']}")
        # Your processing logic here
        return True
    except Exception as e:
        print(f"Error: {e}")
        return False

# Initialize consumer with your config
consumer = RabbitMQConsumer(
    host="localhost",
    port=5672,
    user="guest",
    password="guest",
    queue="document_queue"
)

# Start consuming
consumer.consume(process_message)
```

### Producer Pattern (Retriever Service)

```python
from rabbitmq_client import RabbitMQProducer

# Initialize producer with your config
producer = RabbitMQProducer(
    host="localhost",
    port=5672,
    user="guest",
    password="guest",
    queue="document_queue"
)

# Connect
producer.connect()

# Publish a message
message = {
    "title": "Document Title",
    "url": "https://example.com/doc",
    "category": "white paper",
    "content": "Document content...",
    "publish_date": "2024-01-15",
    "source": "wi-fi-alliance",
    "scraped_at": 1699123456.78
}

producer.publish(message)

# Close when done
producer.close()
```

### Context Manager Support

```python
from rabbitmq_client import RabbitMQProducer

with RabbitMQProducer(host="localhost", user="guest", password="guest", queue="my_queue") as producer:
    producer.publish({"data": "value"})
    producer.publish({"more": "data"})
# Connection automatically closed
```

### Batch Publishing

```python
from rabbitmq_client import RabbitMQProducer

producer = RabbitMQProducer(host="localhost", user="guest", password="guest", queue="my_queue")
producer.connect()

messages = [
    {"title": "Doc 1", "url": "https://example.com/1"},
    {"title": "Doc 2", "url": "https://example.com/2"},
    {"title": "Doc 3", "url": "https://example.com/3"},
]

producer.publish_batch(messages)
producer.close()
```

## Features

### RabbitMQConsumer
- ✅ Auto-reconnect on connection loss
- ✅ Message acknowledgment/rejection
- ✅ Automatic JSON deserialization
- ✅ Error handling with requeue
- ✅ Graceful shutdown on KeyboardInterrupt
- ✅ Queue auto-declaration (durable)
- ✅ Prefetch control (QoS)
- ✅ Optional logger injection
- ✅ **Multi-threaded processing** (NEW!)
- ✅ **Configurable heartbeat** for long-running tasks

### RabbitMQProducer
- ✅ Simple publish interface
- ✅ Batch publishing support
- ✅ Automatic JSON serialization
- ✅ Message persistence (delivery_mode=2)
- ✅ Context manager support
- ✅ Queue auto-declaration (durable)
- ✅ Optional logger injection

## Multi-threaded Processing (NEW)

For long-running message processing tasks (e.g., LLM calls, API requests), enable multi-threaded processing:

```python
from rabbitmq_client import RabbitMQConsumer

consumer = RabbitMQConsumer(
    host="localhost",
    queue="document_queue",
    max_workers=4,      # Enable 4 worker threads
    heartbeat=180       # 3 minute heartbeat (prevents timeout)
)

# Increase prefetch to keep workers busy
consumer.consume(
    callback=process_message,
    prefetch_count=8    # Generally max_workers * 2
)
```

**Benefits:**
- Process multiple messages concurrently
- Prevents connection timeouts during long processing
- Better resource utilization for I/O-bound tasks

**See**: `TECHNICAL_DETAILS.md` for implementation details and best practices.

## Configuration

The library is **configuration-agnostic**. Each microservice:
1. Loads its own configuration (from .env, settings, etc.)
2. Passes configuration to the client at initialization

```python
# In your microservice
from your_service.config import settings
from rabbitmq_client import RabbitMQConsumer

consumer = RabbitMQConsumer(
    host=settings.rabbitmq_host,
    port=settings.rabbitmq_port,
    user=settings.rabbitmq_user,
    password=settings.rabbitmq_password,
    queue=settings.rabbitmq_queue,
    logger_instance=your_logger,  # Optional
    max_workers=settings.max_workers,  # Optional: enable multi-threading
    heartbeat=settings.heartbeat  # Optional: increase for long tasks
)
```

## Architecture

```
rabbitmq_client/
├── __init__.py           # Public API
├── consumer.py           # Message consumer
└── producer.py           # Message publisher
```

## Error Handling

### Consumer
- **JSON decode errors**: Message acknowledged (removed) to prevent infinite loops
- **Processing errors**: Message rejected and requeued for retry
- **Connection errors**: Logged with full traceback

### Producer
- **Connection errors**: Raised as exceptions
- **Serialization errors**: Raised as exceptions (validate before publishing)

## Use Cases

### Digester Service (Consumer)
```python
from rabbitmq_client import RabbitMQConsumer
from config.settings import settings

consumer = RabbitMQConsumer(
    host=settings.rabbitmq_host,
    port=settings.rabbitmq_port,
    user=settings.rabbitmq_user,
    password=settings.rabbitmq_password,
    queue=settings.rabbitmq_queue
)

def process_document(message):
    # Extract metadata, validate, insert to graph
    return True

consumer.consume(process_document)
```

### Retriever Service (Producer)
```python
from rabbitmq_client import RabbitMQProducer
from config.settings import settings

producer = RabbitMQProducer(
    host=settings.rabbitmq_host,
    port=settings.rabbitmq_port,
    user=settings.rabbitmq_user,
    password=settings.rabbitmq_password,
    queue=settings.rabbitmq_queue
)

producer.connect()

# Scrape documents and publish
for doc in scraped_documents:
    producer.publish({
        "title": doc.title,
        "url": doc.url,
        "content": doc.content,
        # ...
    })

producer.close()
```

### Future Analytics Service (Both)
```python
from rabbitmq_client import RabbitMQConsumer, RabbitMQProducer

# Consume from one queue
consumer = RabbitMQConsumer(queue="raw_data_queue")

# Publish to another queue
producer = RabbitMQProducer(queue="processed_data_queue")
producer.connect()

def process_and_forward(message):
    # Process
    result = analyze(message)
    # Forward
    producer.publish(result)
    return True

consumer.consume(process_and_forward)
```

## Advanced Usage

### Custom Logger

```python
import logging
from rabbitmq_client import RabbitMQProducer

my_logger = logging.getLogger("my_service")
my_logger.setLevel(logging.DEBUG)

producer = RabbitMQProducer(
    host="localhost",
    user="guest",
    password="guest",
    queue="my_queue",
    logger_instance=my_logger
)
```

### Multiple Queues

```python
from rabbitmq_client import RabbitMQProducer

# Publish to different queues
high_priority = RabbitMQProducer(host="localhost", user="guest", password="guest", queue="high_priority")
low_priority = RabbitMQProducer(host="localhost", user="guest", password="guest", queue="low_priority")

high_priority.connect()
low_priority.connect()

if message["urgent"]:
    high_priority.publish(message)
else:
    low_priority.publish(message)
```

## Requirements

- Python 3.10+
- pika >= 1.3.2
- RabbitMQ 3.x

## License

Proprietary
