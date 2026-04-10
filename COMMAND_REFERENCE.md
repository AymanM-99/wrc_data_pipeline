# Command Reference: How Each Command Works

This document explains how the project's main commands find and execute their components.
Understanding this is essential for debugging and extending the project.

---

## 1. Scrapy: `scrapy crawl wrc`

### The Command
```bash
cd scraper
python -m scrapy crawl wrc -a start_date=2024-01-01 -a end_date=2024-03-31
```

### How Scrapy Finds the Spider

**Step-by-step discovery:**

```
scrapy crawl wrc
       │
       ▼
┌──────────────────────────────────────────────────┐
│ 1. Scrapy looks for scrapy.cfg in current dir   │
│    or parent directories                        │
└──────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────┐
│ 2. scrapy.cfg says:                             │
│    [settings]                                    │
│    default = wrc_scraper.settings               │
└──────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────┐
│ 3. wrc_scraper/settings.py defines:             │
│    SPIDER_MODULES = ["wrc_scraper.spiders"]     │
└──────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────┐
│ 4. Scrapy scans wrc_scraper/spiders/ for        │
│    classes that inherit from scrapy.Spider      │
└──────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────┐
│ 5. WrcSpider has name = "wrc"                   │
│    → This matches "scrapy crawl wrc"            │
└──────────────────────────────────────────────────┘
```

### Key Files Involved

| File | Purpose |
|------|---------|
| `scraper/scrapy.cfg` | Entry point - tells Scrapy where settings are |
| `scraper/wrc_scraper/settings.py` | Defines `SPIDER_MODULES` (where to find spiders) |
| `scraper/wrc_scraper/spiders/wrc_spider.py` | Contains `WrcSpider` class with `name = "wrc"` |

### The sys.path.insert Line

```python
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
```

**Why it's needed:**
- The spider is at `scraper/wrc_scraper/spiders/wrc_spider.py`
- But it needs to import from `config/` and `utils/` at project root
- Python can only import from folders in `sys.path`
- This line adds the project root (`c:\Workbench\data_pipeline`) to `sys.path`

**How it works (from wrc_spider.py):**
```
__file__           = scraper/wrc_scraper/spiders/wrc_spider.py
dirname(__file__)  = scraper/wrc_scraper/spiders/
dirname(dirname)   = scraper/wrc_scraper/
dirname(dirname)   = scraper/
dirname(dirname)   = c:\Workbench\data_pipeline  ← project root!
```

### Arguments Passed

| Argument | Purpose | Accessed In Code |
|----------|---------|------------------|
| `-a start_date=...` | Start of date range | `self.start_date` in spider |
| `-a end_date=...` | End of date range | `self.end_date` in spider |

Scrapy converts `-a name=value` to attributes on the spider class.

---

## 2. Dagster: `dagster dev`

### The Command
```bash
# From project root
dagster dev -f orchestration/definitions.py

# Or using module path
dagster dev -m orchestration.definitions
```

### How Dagster Finds Definitions

**Step-by-step discovery:**

```
dagster dev -f orchestration/definitions.py
            │
            ▼
┌──────────────────────────────────────────────────┐
│ 1. Dagster loads the specified Python file      │
│    (or module with -m)                          │
└──────────────────────────────────────────────────┘
            │
            ▼
┌──────────────────────────────────────────────────┐
│ 2. Dagster looks for a variable named "defs"    │
│    of type Definitions                          │
└──────────────────────────────────────────────────┘
            │
            ▼
┌──────────────────────────────────────────────────┐
│ 3. definitions.py creates:                      │
│    defs = Definitions(                          │
│        assets=[...],                            │
│        jobs=[...],                              │
│    )                                            │
└──────────────────────────────────────────────────┘
            │
            ▼
┌──────────────────────────────────────────────────┐
│ 4. Assets loaded from orchestration/assets.py   │
│    using load_assets_from_modules([assets])     │
└──────────────────────────────────────────────────┘
            │
            ▼
┌──────────────────────────────────────────────────┐
│ 5. Jobs loaded from orchestration/jobs.py       │
│    - scraping_job                               │
│    - transformation_job                         │
│    - full_pipeline_job                          │
└──────────────────────────────────────────────────┘
```

### Key Files Involved

| File | Purpose |
|------|---------|
| `orchestration/definitions.py` | Entry point - creates `defs = Definitions(...)` |
| `orchestration/assets.py` | Defines `@asset` decorated functions |
| `orchestration/jobs.py` | Defines jobs that select which assets to run |

### What Dagster Registers

```python
defs = Definitions(
    assets=all_assets,      # From load_assets_from_modules([assets])
    jobs=[                  # Manually imported
        scraping_job,
        transformation_job,
        full_pipeline_job,
    ],
)
```

**Assets (from assets.py):**
- `scraped_documents` - Runs the Scrapy spider
- `processed_documents` - Runs the transformation

**Jobs (from jobs.py):**
- `scraping_job` - Runs only `scraped_documents`
- `transformation_job` - Runs only `processed_documents`
- `full_pipeline_job` - Runs both in order

### The Config Class

```python
class DateRangeConfig(Config):
    start_date: str  # Required when launching job
    end_date: str    # Required when launching job
```

When you run a job in Dagster UI, you must provide these config values:
```yaml
ops:
  scraped_documents:
    config:
      start_date: "2024-01-01"
      end_date: "2024-03-31"
```

### How Assets Call Each Other

```python
@asset
def scraped_documents(context, config: DateRangeConfig):
    # Runs Scrapy via subprocess
    subprocess.run(['python', '-m', 'scrapy', 'crawl', 'wrc', ...])

@asset
def processed_documents(context, config: DateRangeConfig, scraped_documents):
    #                                                     ↑
    # This parameter creates a DEPENDENCY
    # Dagster will run scraped_documents FIRST
    run_transformation(config.start_date, config.end_date)
```

---

## 3. Transformation: `python -m transform.transformer`

### The Command
```bash
# From project root
python -m transform.transformer --start-date 2024-01-01 --end-date 2024-03-31

# Or via Python import (used by Dagster)
python -c "from transform.transformer import run_transformation; run_transformation('2024-01-01', '2024-03-31')"
```

### How Python Finds the Module

**Using `python -m`:**

```
python -m transform.transformer
           │
           ▼
┌──────────────────────────────────────────────────┐
│ 1. Python looks in current directory for        │
│    a folder called "transform"                  │
└──────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────┐
│ 2. Inside transform/, finds transformer.py      │
│    (transform.transformer = transform/          │
│                             transformer.py)     │
└──────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────┐
│ 3. Python executes the file as __main__         │
│    (runs the if __name__ == "__main__" block)   │
└──────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────┐
│ 4. ArgumentParser reads --start-date and        │
│    --end-date, then calls run_transformation()  │
└──────────────────────────────────────────────────┘
```

### Key Files Involved

| File | Purpose |
|------|---------|
| `transform/__init__.py` | Makes `transform` a Python package |
| `transform/transformer.py` | Contains `run_transformation()` and CLI handling |

### The sys.path.insert Line

```python
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

**From transformer.py:**
```
__file__           = transform/transformer.py
dirname(__file__)  = transform/
dirname(dirname)   = c:\Workbench\data_pipeline  ← project root!
```

This allows importing from `config/` and `utils/`.

### Main Entry Point

```python
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    args = parser.parse_args()
    
    run_transformation(args.start_date, args.end_date)
```

---

## Summary: Command Discovery Pattern

| Command | Config File | Discovery Setting | What It Finds |
|---------|------------|-------------------|---------------|
| `scrapy crawl wrc` | `scrapy.cfg` | `SPIDER_MODULES` in settings.py | Spider with `name = "wrc"` |
| `dagster dev -f ...` | The specified file | `defs = Definitions(...)` | Assets and Jobs |
| `python -m transform.transformer` | None | File path (`transform/transformer.py`) | `__main__` block |

---

## Common Issues

### "Spider not found"
- **Cause:** You're not in the `scraper/` directory, or `scrapy.cfg` is missing
- **Fix:** `cd scraper` before running the command

### "No module named 'config'"
- **Cause:** `sys.path.insert` line is missing or wrong
- **Fix:** Ensure the file has the path manipulation at the top

### "Config required" in Dagster
- **Cause:** Jobs need `start_date` and `end_date` config
- **Fix:** Provide config in the Launchpad UI or via CLI

### "No module named 'transform'"
- **Cause:** Running from wrong directory or missing `__init__.py`
- **Fix:** Run from project root, ensure `transform/__init__.py` exists

---

## Quick Reference

```bash
# From project root:

# 1. Run scraper directly
cd scraper
python -m scrapy crawl wrc -a start_date=2024-01-01 -a end_date=2024-03-31
cd ..

# 2. Run transformation directly
python -m transform.transformer --start-date 2024-01-01 --end-date 2024-03-31

# 3. Run via Dagster UI
dagster dev -f orchestration/definitions.py
# Then open http://localhost:3000 and launch jobs with config
```
