# Aurora Retriever

A containerized web scraping microservice that extracts articles and documents from public websites, processes the content, and publishes structured data to RabbitMQ queues.

## Overview

The Aurora Retriever is designed to:
- **Scrape Web Content**: Extract articles, PDFs, and other resources from target websites
- **Process Multiple Formats**: Handle HTML content extraction and PDF text extraction
- **Handle Complex Navigation**: Follow server and client-side redirects automatically
- **Queue Management**: Publish scraped content to RabbitMQ for downstream processing using the shared `rabbitmq-client` library
- **Modular Architecture**: Easy to extend with new scraper implementations
- **Configuration Management**: Centralized settings using Pydantic Settings with environment variable support

### Current Scrapers
- **Wi-Fi Alliance Resource Center**: Scrapes articles, white papers, and technical documents

## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Web Sources   │───▶│  Aurora         │───▶│   RabbitMQ      │
│                 │    │  Retriever      │    │   Queue         │
│ • Wi-Fi Alliance│    │                 │    │                 │
│ • Future Sites  │    │ • HTML Parsing  │    │ • Structured    │
│                 │    │ • PDF Text      │    │   Messages      │
│                 │    │ • Redirects     │    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## Prerequisites

- Docker
- Make
- Environment variables configured (see Environment Setup below)

## Environment Setup

Copy the environment template and configure your settings:

```bash
cp .env.example .env
```

Edit `.env` with your specific configuration values. The template includes all required environment variables for:
- Docker network settings
- RabbitMQ connection details
- Scraper configuration (delays, redirects)
- Logging levels
- API settings

See [../.env.example](../.env.example) for the complete configuration template.

## Deployment

### Quick Start

From the retriever directory:

```bash
# Deploy using shared infrastructure (recommended)
make deploy-local
```

This will:
1. Validate environment variables
2. Ensure RabbitMQ is running (starts if needed)
3. Build the retriever Docker image
4. Deploy the scraper container with proper networking

### Development Mode

For complete isolation during development:

```bash
# Deploy with isolated infrastructure
make deploy-isolated
```

This creates a completely isolated environment with its own RabbitMQ instance on different ports.

## Available Commands

```bash
make help             # Show all available commands
make deploy-local     # Deploy on shared network (recommended)
make deploy-isolated  # Deploy with isolated infrastructure
make clean-isolated   # Clean ALL isolated environments (all services)
make clean-shared     # Clean shared resources (use with caution)
make nuke            # Remove everything (containers + images + cleanup)
```

## Message Format

Scraped resources are published to RabbitMQ as JSON messages with the following structure:

```json
{
  "title": "Wi-Fi CERTIFIED 7: Next Evolution of Wi-Fi",
  "url": "https://www.wi-fi.org/news-events/newsroom/wi-fi-certified-7-next-evolution-of-wi-fi",
  "resource_type": "article",
  "content": "Full extracted text content from the webpage or PDF...",
  "publish_date": "2024-01-15",
  "source": "wi-fi-alliance",
  "timestamp": 1699123456.789
}
```

### Field Descriptions

- **title**: Document/article title
- **url**: Original resource URL
- **resource_type**: Type classification (article, white paper, specification, etc.)
- **content**: Full text extracted from HTML or PDF
- **publish_date**: Publication date (ISO format when available)
- **source**: Source identifier (currently "wi-fi-alliance") 
- **timestamp**: Unix timestamp when the resource was published

## Monitoring & Management

### RabbitMQ Management

- **Shared Mode**: http://localhost:15672
- **Isolated Mode**: http://localhost:15673
- **Default Credentials**: See your `.env` file (RABBITMQ_USER/RABBITMQ_PASSWORD)

### Queue Monitoring

- Monitor message counts and consumers in RabbitMQ Management UI
- Check queue `scraped_content` for published messages
- View message rates and processing statistics