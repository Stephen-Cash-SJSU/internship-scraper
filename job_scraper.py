import os
import json
import logging
from datetime import datetime, timezone

import gspread
from google.oauth2.service_account import Credentials
from serpapi import GoogleSearch

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SERPAPI_KEY = os.environ["SERPAPI_KEY"]
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
SHEET_NAME = os.environ.get("SHEET_NAME", "Internships")

SEARCH_QUERIES = [
    "Marketing internship",
    "Business Analytics internship",
    "Sales internship",
    "Finance internship",
    "Supply Chain internship",
    "Procurement internship",
    "Operations internship",
    "Business Development internship",
]

MAX_AGE_DAYS = 7


def get_sheet():
    creds_json = os.environ["GOOGLE_SHEETS_CREDS"]
    creds_dict = json.loads(creds_json)
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    try:
        worksheet = spreadsheet.worksheet(SHEET_NAME)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=SHEET_NAME, rows=1000, cols=10)
        log.info("Created new worksheet: %s", SHEET_NAME)
    return worksheet


def ensure_headers(worksheet):
    headers = [
        "Job Title",
        "Company",
        "Location",
        "Date Posted",
        "Apply Link",
        "Source Query",
        "Date Added to Sheet",
    ]
    if not worksheet.get_all_values():
        worksheet.append_row(headers, value_input_option="RAW")
        log.info("Added headers to sheet.")


def search_jobs(query):
    params = {
        "engine": "google_jobs",
        "q": query,
        "api_key": SERPAPI_KEY,
        "chips": "date_posted:" + str(MAX_AGE_DAYS) + "d",
        "hl": "en",
        "gl": "us",
        "num": 10,
    }
    search = GoogleSearch(params)
    results = search.get_dict()
    jobs = results.get("jobs_results", [])
    log.info("Found %d results for: %s", len(jobs), query)
    return jobs


def get_existing_links(worksheet):
    try:
        all_values = worksheet.get_all_values()
        if len(all_values) <= 1:
            return set()
        link_col_index = 4
        return {row[link_col_index] for row in all_values[1:] if len(row) > link_col_index}
    except Exception as e:
        log.warning("Could not fetch existing links: %s", e)
        return set()


def parse_job(job, query):
    title = job.get("title", "").strip()
    company = job.get("company_name", "").strip()
    location = job.get("location", "").strip()
    detected = job.get("detected_extensions", {})
    posted = detected.get("posted_at", "Unknown")
    apply_options = job.get("apply_options", [])
    link = apply_options[0].get("link", "") if apply_options else job.get("share_link", "")
    if not link:
        return None
    return {
        "title": title,
        "company": company,
        "location": location,
        "posted": posted,
        "link": link,
        "query": query,
    }


def main():
    log.info("=== Internship Scraper Started ===")
    worksheet = get_sheet()
    ensure_headers(worksheet)
    existing_links = get_existing_links(worksheet)
    log.info("Sheet already contains %d listings.", len(existing_links))
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    new_rows = []
    for query in SEARCH_QUERIES:
        log.info("Searching: %s", query)
        try:
            jobs = search_jobs(query)
        except Exception as e:
            log.error("Search failed for %s: %s", query, e)
            continue
        for job in jobs:
            parsed = parse_job(job, query)
            if parsed is None:
                continue
            if parsed["link"] in existing_links:
                log.info("Skipping duplicate: %s", parsed["title"])
                continue
            new_rows.append([
                parsed["title"],
                parsed["company"],
                parsed["location"],
                parsed["posted"],
                parsed["link"],
                parsed["query"],
                today,
            ])
            existing_links.add(parsed["link"])
    if new_rows:
        worksheet.append_rows(new_rows, value_input_option="USER_ENTERED")
        log.info("Added %d new internship(s) to the sheet.", len(new_rows))
    else:
        log.info("No new internships found this run.")
    log.info("=== Done ===")


if __name__ == "__main__":
    main()
