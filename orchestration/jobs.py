"""
Dagster Jobs for WRC Scraper Pipeline.

Jobs define executable pipelines that can be triggered manually or on schedule.

Three jobs:
1. scraping_job - Run only the scraper
2. transformation_job - Run only the transformation
3. full_pipeline_job - Run scraper then transformation
"""

from dagster import (
    define_asset_job,
    AssetSelection,
    ScheduleDefinition,
    DefaultScheduleStatus,
)

from .assets import scraped_documents, processed_documents


# Job 1: Scraping only
# Use this when you just want to ingest new data
scraping_job = define_asset_job(
    name="scraping_job",
    description="Scrape documents from WRC website into landing zone",
    selection=AssetSelection.assets(scraped_documents),
)


# Job 2: Transformation only
# Use this when landing zone already has data and you want to (re)process it
transformation_job = define_asset_job(
    name="transformation_job",
    description="Transform documents from landing zone to processed zone",
    selection=AssetSelection.assets(processed_documents),
)


# Job 3: Full pipeline
# Runs scraping first, then transformation (because of asset dependency)
full_pipeline_job = define_asset_job(
    name="full_pipeline_job",
    description="Full pipeline: scrape documents then transform them",
    selection=AssetSelection.assets(scraped_documents, processed_documents),
)


# Optional: Schedule for daily runs
# This would run every day at 2 AM, scraping the previous day's documents
# Uncomment and configure if needed
#
# daily_scrape_schedule = ScheduleDefinition(
#     job=full_pipeline_job,
#     cron_schedule="0 2 * * *",  # 2 AM daily
#     default_status=DefaultScheduleStatus.STOPPED,  # Start stopped
#     run_config={
#         "ops": {
#             "scraped_documents": {
#                 "config": {
#                     "start_date": "{{ (execution_date - timedelta(days=1)).strftime('%Y-%m-%d') }}",
#                     "end_date": "{{ execution_date.strftime('%Y-%m-%d') }}",
#                 }
#             },
#             "processed_documents": {
#                 "config": {
#                     "start_date": "{{ (execution_date - timedelta(days=1)).strftime('%Y-%m-%d') }}",
#                     "end_date": "{{ execution_date.strftime('%Y-%m-%d') }}",
#                 }
#             }
#         }
#     }
# )
