#!/usr/bin/env python3
"""Import Thai-origin TV series first aired between 2025-01-01 and today from TMDB."""

import json
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_BASE = "https://api.themoviedb.org/3/discover/tv"
START_DATE = os.getenv("START_DATE", "2025-01-01")
END_DATE = os.getenv("END_DATE", date.today().isoformat())
OUTPUT_PATH = Path(os.getenv("OUTPUT_PATH", "data/series.json"))
MAX_PAGES = 500  # TMDB Discover API page limit


def api_get(params, token, attempts=4):
    url = f"{API_BASE}?{urlencode(params)}"
    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "accept": "application/json",
            "User-Agent": "Thai-Series-Hub/1.0",
        },
    )
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code == 429 or 500 <= exc.code < 600:
                if attempt < attempts - 1:
                    time.sleep(2 ** attempt)
                    continue
            raise RuntimeError(f"TMDB API returned HTTP {exc.code}: {exc.reason}") from exc
        except (URLError, TimeoutError) as exc:
            if attempt < attempts - 1:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"Could not reach TMDB API: {exc}") from exc
    raise RuntimeError("TMDB request failed after retries")


def clean_record(item):
    return {
        "id": item.get("id"),
        "name": (item.get("name") or "").strip(),
        "original_name": (item.get("original_name") or "").strip(),
        "overview": (item.get("overview") or "").strip(),
        "first_air_date": item.get("first_air_date") or "",
        "origin_country": item.get("origin_country") or [],
        "original_language": item.get("original_language") or "",
        "genre_ids": item.get("genre_ids") or [],
        "poster_path": item.get("poster_path"),
        "backdrop_path": item.get("backdrop_path"),
        "vote_average": item.get("vote_average", 0),
        "vote_count": item.get("vote_count", 0),
        "popularity": item.get("popularity", 0),
        "tmdb_url": f"https://www.themoviedb.org/tv/{item['id']}" if item.get("id") else "",
    }


def main():
    token = os.getenv("TMDB_API_READ_ACCESS_TOKEN", "").strip()
    if not token:
        print("ERROR: Set the TMDB_API_READ_ACCESS_TOKEN environment variable.", file=sys.stderr)
        return 2

    # Use explicit sort and date filters; do not filter by genre, so BL/GL and other genres
    # are not intentionally excluded. TMDB's country metadata may still be incomplete.
    base_params = {
        "include_adult": "false",
        "include_null_first_air_dates": "false",
        "language": "en-US",
        "sort_by": "first_air_date.asc",
        "with_origin_country": "TH",
        "first_air_date.gte": START_DATE,
        "first_air_date.lte": END_DATE,
        "page": 1,
    }

    first_page = api_get(base_params, token)
    total_pages = min(int(first_page.get("total_pages", 1)), MAX_PAGES)
    all_items = list(first_page.get("results", []))
    print(f"TMDB reports {first_page.get('total_results', len(all_items))} matching results across {first_page.get('total_pages', 1)} pages; importing up to {total_pages} pages.")

    for page in range(2, total_pages + 1):
        params = dict(base_params)
        params["page"] = page
        payload = api_get(params, token)
        all_items.extend(payload.get("results", []))
        if page % 25 == 0 or page == total_pages:
            print(f"Fetched page {page}/{total_pages}")
        time.sleep(0.15)

    # Deduplicate by TMDB ID and validate dates/country locally too.
    by_id = {}
    for item in all_items:
        series_id = item.get("id")
        air_date = item.get("first_air_date") or ""
        countries = item.get("origin_country") or []
        if not series_id or not air_date or not (START_DATE <= air_date <= END_DATE):
            continue
        if "TH" not in countries:
            continue
        record = clean_record(item)
        if not record["name"]:
            continue
        by_id[series_id] = record

    records = sorted(by_id.values(), key=lambda x: (x["first_air_date"], x["name"].casefold()))
    output = {
        "source": "The Movie Database (TMDB)",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "date_range": {"from": START_DATE, "to": END_DATE},
        "count": len(records),
        "series": records,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {len(records)} unique Thai series to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
