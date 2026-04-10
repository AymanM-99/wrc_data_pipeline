"""
Dagster Definitions for WRC Scraper Pipeline.

This file is the entry point for Dagster. It registers all assets,
jobs, schedules, and resources that Dagster should know about.

To start Dagster UI:
    dagster dev -f orchestration/definitions.py

Or from project root:
    dagster dev -m orchestration.definitions
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dagster import Definitions, load_assets_from_modules

from orchestration import assets
from orchestration.jobs import (
    scraping_job,
    transformation_job,
    full_pipeline_job,
)


# Load all assets from the assets module
all_assets = load_assets_from_modules([assets])


# Create Dagster Definitions
defs = Definitions(
    assets=all_assets,
    jobs=[
        scraping_job,
        transformation_job,
        full_pipeline_job,
    ],
    # Add schedules here if needed:
    # schedules=[daily_scrape_schedule],
)
