
"""
Bear Blog Ranking Analysis
INFO4617 Fall 2026

Collects snapshots of Bear Blog's public Trending RSS feed,
retrieves public upvote counts, and calculates predicted rankings
using Bear Blog's published ranking formula.
"""

import csv
import json
import math
import time
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import feedparser
import requests
from bs4 import BeautifulSoup


# --------------------------------------------------
# PROJECT SETTINGS
# --------------------------------------------------

PROJECT_NAME = "Bear Blog Ranking Analysis"
REPOSITORY_URL = (
    "https://github.com/meezie7/bearblog-ranking-analysis-INFO4617"
)

FEED_URL = "https://bearblog.dev/discover/feed/"
OUTPUT_FILE = Path("ranking_observations.csv")

USER_AGENT = (
    f"{PROJECT_NAME}/1.0 (+{REPOSITORY_URL})"
)

STOP_DATE = date(2026, 12, 6)
LOCAL_TIMEZONE = ZoneInfo("America/Denver")

# Published ranking formula:
# Score = log10(upvotes) + seconds_since_2020 / (B * 86,400)
BUOYANCY = 3
EPOCH = datetime(2020, 1, 1, tzinfo=timezone.utc)

REQUEST_TIMEOUT = 20
REQUEST_DELAY_SECONDS = 0.5

CSV_FIELDS = [
    "snapshot_id",
    "collected_at",
    "position",
    "title",
    "url",
    "published",
    "upvotes",
    "predicted_score",
    "predicted_position",
    "rank_difference",
    "absolute_rank_difference",
]


# --------------------------------------------------
# REQUEST SESSION
# --------------------------------------------------

def create_session():
    """Create a session with an identifiable User-Agent."""

    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    })

    return session


def get_response(session, url):
    """Retrieve a URL with a timeout and a short courtesy delay."""

    response = session.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    time.sleep(REQUEST_DELAY_SECONDS)

    return response


# --------------------------------------------------
# FEED COLLECTION
# --------------------------------------------------

def collect_feed(session):
    """Retrieve and validate the public Trending RSS feed."""

    response = get_response(session, FEED_URL)
    feed = feedparser.parse(response.content)

    if not feed.entries:
        raise RuntimeError("The RSS feed returned no entries.")

    posts = []

    for position, entry in enumerate(feed.entries, start=1):

        title = entry.get("title", "").strip()
        url = entry.get("link", "").strip()
        published_struct = entry.get("published_parsed")

        if not title or not url:
            raise ValueError(
                f"Feed entry {position} is missing a title or URL."
            )

        if not published_struct:
            raise ValueError(
                f"Publication timestamp missing for: {title}"
            )

        # Feed timestamps are interpreted as UTC.
        published_timestamp = time.mktime(published_struct)
        published = datetime.fromtimestamp(
            published_timestamp,
            tz=timezone.utc
        )

        posts.append({
            "position": position,
            "title": title,
            "url": url,
            "published": published,
        })

    return posts


# --------------------------------------------------
# PUBLIC UPVOTE COUNTS
# --------------------------------------------------

def get_upvote_count(session, post_url):
    """
    Retrieve a post's public upvote count.

    The post page contains a public upvote form with a UID.
    The UID is used to query the post's public upvote-info endpoint.

    The endpoint's token is deliberately not stored.
    """

    page_response = get_response(session, post_url)
    soup = BeautifulSoup(page_response.text, "html.parser")

    form = soup.select_one("#upvote-form")

    if form is None:
        raise ValueError(
            f"Could not find the upvote form for {post_url}"
        )

    uid_input = form.select_one('input[name="uid"]')

    if uid_input is None or not uid_input.get("value"):
        raise ValueError(
            f"Could not find the post UID for {post_url}"
        )

    uid = uid_input["value"]

    parsed_url = urlparse(post_url)

    endpoint = (
        f"{parsed_url.scheme}://{parsed_url.netloc}"
        f"/upvote-info/{uid}/"
    )

    vote_response = get_response(session, endpoint)
    vote_data = vote_response.json()

    if "upvote_count" not in vote_data:
        raise ValueError(
            f"Upvote count missing from endpoint for {post_url}"
        )

    upvotes = int(vote_data["upvote_count"])

    if upvotes < 0:
        raise ValueError(
            f"Invalid upvote count for {post_url}"
        )

    return upvotes


# --------------------------------------------------
# RANKING CALCULATIONS
# --------------------------------------------------

def calculate_score(upvotes, published):
    """Calculate the score using Bear Blog's published formula."""

    if upvotes <= 0:
        raise ValueError(
            "The published formula uses log10(upvotes), "
            "which is undefined for zero upvotes. "
            "Snapshot not saved."
        )

    seconds_since_epoch = (published - EPOCH).total_seconds()

    score = (
        math.log10(upvotes)
        + seconds_since_epoch / (BUOYANCY * 86400)
    )

    return score


def calculate_predicted_positions(rows):
    """Rank posts by predicted score, highest score first."""

    ranked_rows = sorted(
        rows,
        key=lambda row: (
            -row["predicted_score"],
            row["position"]
        )
    )

    predicted_positions = {
        row["url"]: position
        for position, row in enumerate(ranked_rows, start=1)
    }

    for row in rows:
        predicted_position = predicted_positions[row["url"]]

        row["predicted_position"] = predicted_position
        row["rank_difference"] = (
            predicted_position - row["position"]
        )
        row["absolute_rank_difference"] = abs(
            row["rank_difference"]
        )

    return rows


# --------------------------------------------------
# CSV OUTPUT
# --------------------------------------------------

def append_snapshot(rows):
    """
    Append a complete snapshot to the longitudinal CSV.

    Data is written only after every post has been collected
    and ranked successfully.
    """

    file_exists = OUTPUT_FILE.exists()

    if file_exists and OUTPUT_FILE.stat().st_size > 0:
        with OUTPUT_FILE.open(
            "r",
            newline="",
            encoding="utf-8"
        ) as existing_file:
            reader = csv.reader(existing_file)
            existing_header = next(reader, [])

        if existing_header != CSV_FIELDS:
            raise ValueError(
                "The existing CSV columns do not match "
                "the collector's expected schema."
            )

    with OUTPUT_FILE.open(
        "a",
        newline="",
        encoding="utf-8"
    ) as csv_file:

        writer = csv.DictWriter(
            csv_file,
            fieldnames=CSV_FIELDS
        )

        if not file_exists or OUTPUT_FILE.stat().st_size == 0:
            writer.writeheader()

        writer.writerows(rows)


# --------------------------------------------------
# MAIN COLLECTION
# --------------------------------------------------

def main():

    local_today = datetime.now(LOCAL_TIMEZONE).date()

    if local_today > STOP_DATE:
        print(
            f"Collection period ended on {STOP_DATE}. "
            "No data collected."
        )
        return

    collected_at = datetime.now(timezone.utc)
    collected_at_string = collected_at.isoformat()

    snapshot_id = collected_at.strftime("%Y%m%dT%H%M%SZ")

    print(f"Starting snapshot: {snapshot_id}")
    print(f"Collection time (UTC): {collected_at_string}")

    session = create_session()

    # Collect the entire feed first.
    posts = collect_feed(session)

    print(f"Feed entries found: {len(posts)}")

    rows = []

    # Retrieve every upvote count before saving anything.
    for post in posts:

        upvotes = get_upvote_count(
            session,
            post["url"]
        )

        score = calculate_score(
            upvotes,
            post["published"]
        )

        rows.append({
            "snapshot_id": snapshot_id,
            "collected_at": collected_at_string,
            "position": post["position"],
            "title": post["title"],
            "url": post["url"],
            "published": post["published"].isoformat(),
            "upvotes": upvotes,
            "predicted_score": score,
        })

        print(
            f"{post['position']:>2}. "
            f"{post['title']} | "
            f"Upvotes: {upvotes}"
        )

    # Calculate predicted positions and rank differences.
    rows = calculate_predicted_positions(rows)

    # Save only after the complete snapshot succeeds.
    append_snapshot(rows)

    print("\nSnapshot completed successfully.")
    print(f"Posts saved: {len(rows)}")
    print(f"Output file: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
