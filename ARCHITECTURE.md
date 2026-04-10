# Architecture Decisions

This document explains the key design decisions, trade-offs, and scalability considerations for the WRC Legal Documents Scraper Pipeline.

## Date Partition Size

**Decision:** 30-day (monthly) partitions

**Reasoning:**
- **Balance between granularity and efficiency**: Smaller partitions (daily) would create too many API calls. Larger partitions (yearly) risk timeouts and large memory usage.
- **Typical data volume**: ~500-1000 documents per month across all bodies. This fits comfortably in memory.
- **Resumability**: If a partition fails, we only re-scrape one month, not an entire year.
- **Website behavior**: The WRC search page handles monthly ranges well without performance degradation.

**Trade-offs:**
- Monthly partitions may be too large if daily updates are critical
- For incremental daily syncs, would switch to 1-day partitions

## Retry and Rate Limiting Strategy

**Implementation:**
1. **AutoThrottle** (Scrapy built-in): Dynamically adjusts request rate based on server response times
2. **Exponential Backoff**: On 429/503 errors, wait 2s → 4s → 8s → 16s before retry
3. **Rotating User-Agents**: Prevents detection as a single bot
4. **Concurrent Request Limit**: Default 8, configurable down if blocked

**Why this approach:**
- AutoThrottle is self-tuning and respects server load
- Exponential backoff prevents hammering a struggling server
- User-agent rotation is low-cost and effective
- Most government sites have moderate rate limits (not aggressive blocking)

**Alternative considered:**
- Proxy rotation: Not implemented as WRC doesn't appear to block by IP. Would add complexity and cost.

## Deduplication Strategy

**Approach:** Content-based hashing (SHA256)

**How it works:**
```
1. Download file → Calculate SHA256 hash of raw bytes
2. Check MongoDB: Does document with this identifier exist?
3. If exists AND hash matches → Skip (no change)
4. If exists AND hash differs → Re-upload (content updated)
5. If not exists → Upload (new document)
```

**Why SHA256:**
- Deterministic: Same content always produces same hash
- Collision-resistant: Virtually impossible for different files to have same hash
- Fast: Even for large PDFs, hashing takes milliseconds
- Standard: Widely used, well-understood

**Trade-offs:**
- Requires downloading file to check if changed (network cost)
- Alternative: Use HTTP ETag/Last-Modified headers (but not all servers support this)

## Landing Zone vs Processed Zone

**Pattern:** Medallion Architecture (Bronze/Silver)

```
Landing Zone (Bronze)         Processed Zone (Silver)
─────────────────────         ──────────────────────
- Raw, unmodified data        - Cleaned, transformed
- Never deleted/modified      - HTML stripped of nav/UI
- Source of truth             - Renamed to identifier.ext
- Enables reprocessing        - Ready for consumption
```

**Why separate zones:**
1. **Reprocessing**: If transformation logic improves, re-run without re-scraping
2. **Debugging**: Compare raw vs processed to verify transformations
3. **Audit trail**: Required for legal data - what did we originally receive?
4. **Idempotency**: Safe to re-run transformation; landing zone unchanged

## Scaling to 50+ Sources

If this pipeline needed to support 50+ legal text sources globally:

### 1. Source Abstraction Layer

```python
# Current: Hardcoded for WRC
class WrcSpider(scrapy.Spider):
    ...

# Proposed: Plugin architecture
class SourceSpider(ABC):
    @abstractmethod
    def get_search_url(self, params): pass
    
    @abstractmethod
    def parse_results(self, response): pass

class WrcSpider(SourceSpider): ...
class UKTribunalSpider(SourceSpider): ...
class EUCourtSpider(SourceSpider): ...
```

### 2. Configuration-Driven Sources

```yaml
# sources.yaml
sources:
  - name: wrc_ireland
    base_url: https://workplacerelations.ie
    spider: wrc
    rate_limit: 8
    partition_days: 30
    
  - name: uk_tribunals
    base_url: https://www.gov.uk/employment-tribunal-decisions
    spider: uk_tribunal
    rate_limit: 5
    partition_days: 7
```

### 3. Distributed Architecture

**Current:** Single machine, sequential processing

**Scaled:**
```
┌─────────────────────────────────────────────────────────────┐
│                    DAGSTER CLOUD / KUBERNETES               │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐     │
│   │ Worker 1 │ │ Worker 2 │ │ Worker 3 │ │ Worker N │     │
│   │ (WRC)    │ │ (UK)     │ │ (EU)     │ │ (...)    │     │
│   └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘     │
│        │            │            │            │            │
│        └────────────┴────────────┴────────────┘            │
│                           │                                 │
│                    ┌──────▼──────┐                         │
│                    │   Message   │                         │
│                    │   Queue     │                         │
│                    │  (Celery)   │                         │
│                    └──────┬──────┘                         │
│                           │                                 │
└───────────────────────────┼─────────────────────────────────┘
                            │
              ┌─────────────┴─────────────┐
              │                           │
        ┌─────▼─────┐              ┌──────▼──────┐
        │  MongoDB  │              │    MinIO    │
        │  Cluster  │              │   Cluster   │
        └───────────┘              └─────────────┘
```

### 4. Changes Required

| Aspect | Current | At 50+ Sources |
|--------|---------|----------------|
| **Storage** | Single MongoDB/MinIO | Sharded clusters |
| **Orchestration** | Dagster local | Dagster Cloud or Airflow on K8s |
| **Processing** | Sequential | Parallel workers per source |
| **Monitoring** | Logs | Prometheus + Grafana dashboards |
| **Error handling** | Local retries | Dead letter queues, alerts |
| **Rate limiting** | Per-spider config | Centralized rate limit service |

### 5. Additional Considerations

- **Schema evolution**: Sources may change HTML structure. Need version control of parsers.
- **Language handling**: Non-English sources need encoding detection.
- **Legal compliance**: Different jurisdictions have different scraping rules.
- **Data quality**: Need validation pipeline to detect parsing errors.
- **Cost management**: Cloud storage costs scale with volume; implement tiered storage.

## Technology Choices

| Choice | Why |
|--------|-----|
| **Scrapy** | Industry standard for Python scraping. Built-in retries, concurrency, pipelines. |
| **MongoDB** | Flexible schema for varied legal document metadata. Easy to evolve. |
| **MinIO** | S3-compatible, runs locally. Code works unchanged with AWS S3. |
| **Dagster** | Modern Python-native orchestrator. Better DX than Airflow for small teams. |
| **BeautifulSoup + lxml** | Robust HTML parsing. Handles malformed HTML gracefully. |

## Future Improvements

1. **Incremental scraping**: Track last-scraped date per source, only fetch new documents
2. **Content extraction**: Use LLMs to extract structured data from legal documents
3. **Full-text search**: Add Elasticsearch for document search
4. **API layer**: FastAPI service to query processed documents
5. **Alerting**: Notify on scrape failures or unusual patterns
