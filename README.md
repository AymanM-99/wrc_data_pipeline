# WRC Legal Documents Scraper Pipeline

A scalable data pipeline for scraping legal decisions and determinations from Ireland's [Workplace Relations Commission](https://www.workplacerelations.ie/) website.

## Overview

This pipeline:
1. **Scrapes** documents from 4 legal bodies (Labour Court, WRC, Equality Tribunal, Employment Appeals Tribunal)
2. **Stores** raw files in object storage (MinIO) and metadata in MongoDB
3. **Transforms** HTML documents by extracting relevant content (removing navigation, headers, footers)
4. **Orchestrates** the workflow using Dagster with proper dependency handling

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           DAGSTER ORCHESTRATOR                          │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   ┌─────────────────┐         ┌─────────────────────────────────────┐  │
│   │  INGESTION JOB  │────────▶│        TRANSFORMATION JOB           │  │
│   │  (Scrapy)       │ depends │        (BeautifulSoup)              │  │
│   └────────┬────────┘   on    └──────────────┬──────────────────────┘  │
│            │                                  │                         │
└────────────┼──────────────────────────────────┼─────────────────────────┘
             │                                  │
             ▼                                  ▼
┌─────────────────────────┐      ┌─────────────────────────────────────┐
│   LANDING ZONE (Raw)    │      │      PROCESSED ZONE (Clean)         │
├─────────────────────────┤      ├─────────────────────────────────────┤
│  MongoDB: landing_docs  │      │  MongoDB: processed_docs            │
│  MinIO: landing-bucket  │      │  MinIO: processed-bucket            │
└─────────────────────────┘      └─────────────────────────────────────┘
```

## Prerequisites

- **Python 3.10+**
- **Docker Desktop** (for MongoDB and MinIO)
- **Git** (for version control)

## Quick Start

### 1. Clone and Setup

```bash
# Clone the repository
git clone <your-repo-url>
cd data_pipeline

# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
# Copy example environment file
cp .env.example .env

# Edit .env with your settings (defaults work for local development)
```

### 3. Start Infrastructure

```bash
# Start MongoDB and MinIO containers
docker-compose up -d

# Verify containers are running
docker ps
```

**Access points:**
- MinIO Console: http://localhost:9001 (minioadmin / minioadmin123)
- MongoDB: localhost:27017 (admin / password123)

### 4. Run the Pipeline

#### Option A: Using Dagster (Recommended)

```bash
# Start Dagster UI
dagster dev -f orchestration/definitions.py

# Open http://localhost:3000 in your browser
# Navigate to Jobs > full_pipeline_job
# Click "Materialize all"
# Enter config:
#   start_date: "2024-01-01"
#   end_date: "2024-03-31"
```

#### Option B: Using CLI

```bash
# Run scraper directly
cd scraper
scrapy crawl wrc -a start_date=2024-01-01 -a end_date=2024-03-31

# Run transformation
cd ..
python -m transform.transformer --start-date 2024-01-01 --end-date 2024-03-31
```

## Configuration

All settings are configurable via environment variables in `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `MONGO_HOST` | localhost | MongoDB host |
| `MONGO_PORT` | 27017 | MongoDB port |
| `MONGO_USERNAME` | admin | MongoDB username |
| `MONGO_PASSWORD` | password123 | MongoDB password |
| `MINIO_HOST` | localhost | MinIO host |
| `MINIO_PORT` | 9000 | MinIO API port |
| `MINIO_ROOT_USER` | minioadmin | MinIO access key |
| `MINIO_ROOT_PASSWORD` | minioadmin123 | MinIO secret key |
| `PARTITION_SIZE_DAYS` | 30 | Days per scraping partition |
| `CONCURRENT_REQUESTS` | 8 | Scrapy concurrent requests |
| `DOWNLOAD_DELAY` | 1.0 | Delay between requests (seconds) |

## Project Structure

```
data_pipeline/
├── docker-compose.yml      # Infrastructure (MongoDB, MinIO)
├── .env                    # Local configuration (not in git)
├── .env.example            # Configuration template
├── requirements.txt        # Python dependencies
│
├── config/                 # Configuration module
│   ├── __init__.py
│   └── settings.py         # Loads config from environment
│
├── utils/                  # Shared utilities
│   ├── __init__.py
│   ├── logging_config.py   # JSON structured logging
│   ├── database.py         # MongoDB client
│   └── storage.py          # MinIO client
│
├── scraper/                # Scrapy project
│   ├── scrapy.cfg
│   └── wrc_scraper/
│       ├── items.py        # Data structures
│       ├── settings.py     # Scrapy settings
│       ├── middlewares.py  # Request processing
│       ├── pipelines.py    # Data storage
│       └── spiders/
│           └── wrc_spider.py   # Main spider
│
├── transform/              # Transformation module
│   ├── __init__.py
│   └── transformer.py      # HTML processing
│
├── orchestration/          # Dagster orchestration
│   ├── __init__.py
│   ├── assets.py           # Dagster assets
│   ├── jobs.py             # Dagster jobs
│   └── definitions.py      # Dagster entry point
│
├── README.md               # This file
└── ARCHITECTURE.md         # Design decisions
```

## Key Features

### Idempotency

Running the pipeline twice on the same date range will not:
- Create duplicate records
- Re-download unchanged files

This is achieved by:
- Using file content hashes (SHA256) to detect changes
- Upserting documents by identifier (not insert)

### Structured Logging

All logs are in JSON format for easy parsing:

```json
{
  "timestamp": "2024-07-17T10:30:00Z",
  "level": "INFO",
  "message": "Scrape partition complete",
  "partition_date": "2024-07",
  "body": "Labour Court",
  "records_found": 150,
  "records_scraped": 148
}
```

### Rate Limiting

The scraper respects the target website:
- AutoThrottle adjusts speed based on server response
- Exponential backoff on errors (429, 503)
- Rotating User-Agent headers

## Stopping the Pipeline

```bash
# Stop Docker containers
docker-compose down

# To also remove data volumes:
docker-compose down -v
```

## Troubleshooting

### Docker containers won't start
```bash
# Check if ports are in use
netstat -an | findstr "27017 9000 9001"

# Check Docker logs
docker-compose logs mongodb
docker-compose logs minio
```

### Scraper gets blocked
- Increase `DOWNLOAD_DELAY` in `.env`
- Decrease `CONCURRENT_REQUESTS`
- Check if IP is blocked (try from different network)

### MongoDB connection refused
```bash
# Verify MongoDB is running
docker ps | findstr mongo

# Check MongoDB logs
docker logs wrc_mongodb
```

## License

[Add your license here]
