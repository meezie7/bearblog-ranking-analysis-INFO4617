
import csv
import json
import math
import html
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import defaultdict
from statistics import mean, median

INPUT = Path("ranking_observations.csv")
DEST = Path("docs/index.html")
MT = ZoneInfo("America/Denver")


def number(value):
    if value is None or value == "":
        return None
    return float(value)


def rank_values(values):
    """Return average ranks, including ties."""
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    i = 0

    while i < len(indexed):
        j = i + 1
        while j < len(indexed) and indexed[j][1] == indexed[i][1]:
            j += 1

        average_rank = (i + 1 + j) / 2

        for k in range(i, j):
            ranks[indexed[k][0]] = average_rank

        i = j

    return ranks


def spearman(actual, predicted):
    if len(actual) < 2:
        return None

    x = rank_values(actual)
    y = rank_values(predicted)

    x_mean = mean(x)
    y_mean = mean(y)

    numerator = sum(
        (a - x_mean) * (b - y_mean)
        for a, b in zip(x, y)
    )

    denominator_x = sum((a - x_mean) ** 2 for a in x)
    denominator_y = sum((b - y_mean) ** 2 for b in y)

    denominator = math.sqrt(denominator_x * denominator_y)

    if denominator == 0:
        return None

    return numerator / denominator


def fmt(value, digits=2):
    if value is None:
        return "—"
    return f"{value:.{digits}f}"


def pct(value):
    if value is None:
        return "—"
    return f"{value:.1f}%"


def read_data():
    if not INPUT.exists():
        raise FileNotFoundError(
            f"Cannot find {INPUT.resolve()}"
        )

    with INPUT.open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))

    if not rows:
        raise ValueError("ranking_observations.csv contains no observations.")

    required = [
        "snapshot_id",
        "collected_at",
        "position",
        "title",
        "url",
        "upvotes",
        "predicted_position",
    ]

    missing = [
        column for column in required
        if column not in rows[0]
    ]

    if missing:
        raise ValueError(f"Missing required CSV columns: {missing}")

    observations = []

    for row in rows:
        collected = datetime.fromisoformat(
            row["collected_at"].replace("Z", "+00:00")
        )

        if collected.tzinfo is None:
            raise ValueError(
                "collected_at must include a timezone."
            )

        local_date = collected.astimezone(MT).strftime("%Y-%m-%d")

        actual = int(float(row["position"]))
        predicted = int(float(row["predicted_position"]))

        observations.append({
            "snapshot_id": row["snapshot_id"],
            "collected_at": collected,
            "date": local_date,
            "actual": actual,
            "predicted": predicted,
            "diff": predicted - actual,
            "error": abs(predicted - actual),
            "title": row["title"],
            "url": row["url"],
            "votes": number(row["upvotes"]),
        })

    observations.sort(
        key=lambda x: (x["collected_at"], x["actual"])
    )

    return observations


def analyze(rows):
    grouped = defaultdict(list)

    for row in rows:
        grouped[row["snapshot_id"]].append(row)

    snapshots = []

    for snapshot_id, items in grouped.items():
        actual = [x["actual"] for x in items]
        predicted = [x["predicted"] for x in items]
        errors = [x["error"] for x in items]

        snapshots.append({
            "id": snapshot_id,
            "date": items[0]["date"],
            "collected_at": items[0]["collected_at"],
            "items": items,
            "n": len(items),
            "exact": sum(x == 0 for x in errors) / len(errors) * 100,
            "mae": mean(errors),
            "median": median(errors),
            "rho": spearman(actual, predicted),
        })

    snapshots.sort(key=lambda x: x["collected_at"])

    daily_groups = defaultdict(list)

    for snapshot in snapshots:
        daily_groups[snapshot["date"]].append(snapshot)

    daily = []

    for date, day_snapshots in sorted(daily_groups.items()):
        daily.append({
            "date": date,
            "n": len(day_snapshots),
            "obs": sum(x["n"] for x in day_snapshots),
            "exact": mean(x["exact"] for x in day_snapshots),
            "mae": mean(x["mae"] for x in day_snapshots),
            "median": mean(x["median"] for x in day_snapshots),
            "rho": mean(
                x["rho"] for x in day_snapshots
                if x["rho"] is not None
            ) if any(x["rho"] is not None for x in day_snapshots) else None,
        })

    cumulative = []

    accumulated = []

    for snapshot in snapshots:
        accumulated.extend(snapshot["items"])

        errors = [x["error"] for x in accumulated]
        actual = [x["actual"] for x in accumulated]
        predicted = [x["predicted"] for x in accumulated]

        cumulative.append({
            "date": snapshot["date"],
            "count": len(cumulative) + 1,
            "obs": len(accumulated),
            "exact": sum(x == 0 for x in errors) / len(errors) * 100,
            "mae": mean(errors),
            "median": median(errors),
            "rho": spearman(actual, predicted),
        })

    post_groups = defaultdict(list)

    for row in rows:
        post_groups[(row["url"], row["title"])].append(row)

    postlist = []

    for (url, title), items in post_groups.items():
        errors = [x["error"] for x in items]
        votes = [x["votes"] for x in items if x["votes"] is not None]

        postlist.append({
            "url": url,
            "title": title,
            "n": len(items),
            "mae": mean(errors),
            "maxerr": max(errors),
            "votes": mean(votes) if votes else None,
            "actual": mean(x["actual"] for x in items),
            "pred": mean(x["predicted"] for x in items),
        })

    postlist.sort(
        key=lambda x: (x["mae"], x["n"]),
        reverse=True
    )

    errors = [row["error"] for row in rows]
    exact = sum(row["diff"] == 0 for row in rows)

    overall = {
        "n": len(rows),
        "snapshots": len(snapshots),
        "posts": len(set(row["url"] for row in rows)),
        "exact": exact / len(rows) * 100,
        "exactn": exact,
        "mae": mean(errors),
        "median": median(errors),
        "rho": spearman(
            [row["actual"] for row in rows],
            [row["predicted"] for row in rows],
        ),
        "first": snapshots[0]["date"],
        "last": snapshots[-1]["date"],
    }

    quality = []

    for snapshot in snapshots:
        items = snapshot["items"]
        urls = [x["url"] for x in items]
        positions = [x["actual"] for x in items]

        ok = (
            len(items) == len(set(urls))
            and len(items) == len(set(positions))
            and all(x["url"] and x["title"] for x in items)
        )

        quality.append({
            "id": snapshot["id"],
            "date": snapshot["date"],
            "n": len(items),
            "urls": len(set(urls)),
            "positions": len(set(positions)),
            "range": (
                f"{min(positions)}–{max(positions)}"
                if positions else "—"
            ),
            "ok": ok,
        })

    return overall, snapshots, daily, cumulative, postlist, quality


def table(headers, rows):
    output = [
        "<div class='tablewrap'><table><thead><tr>"
    ]

    for heading in headers:
        output.append(
            f"<th>{html.escape(str(heading))}</th>"
        )

    output.append("</tr></thead><tbody>")

    for row in rows:
        output.append("<tr>")

        for cell in row:
            output.append(f"<td>{cell}</td>")

        output.append("</tr>")

    output.append("</tbody></table></div>")

    return "".join(output)


def make_html(result):
    overall, snapshots, daily, cumulative, posts, quality = result

    cards = [
        ("Observations", f"{overall['n']:,}", "Post appearances across all snapshots"),
        ("Snapshots", f"{overall['snapshots']:,}", "Top-20 feed captures"),
        ("Unique posts", f"{overall['posts']:,}", "Distinct post URLs"),
        ("Exact matches", pct(overall["exact"]), f"{overall['exactn']:,} of {overall['n']:,} observations"),
        ("Mean absolute error", fmt(overall["mae"], 3), "Average positions away from predicted rank"),
        ("Median absolute error", fmt(overall["median"], 1), "Middle absolute rank difference"),
        ("Pooled Spearman", fmt(overall["rho"], 3), "Rank-order association"),
        ("Latest snapshot MAE", fmt(snapshots[-1]["mae"], 3), snapshots[-1]["date"] + f" · {snapshots[-1]['n']} posts"),
    ]

    card_html = "".join(
        f"<article class='metric'><div class='muted'>{html.escape(a)}</div>"
        f"<div class='big'>{html.escape(b)}</div>"
        f"<small>{html.escape(c)}</small></article>"
        for a, b, c in cards
    )

    daily_table = table(
        ["Date (MT)", "Snapshots", "Observations", "Avg. exact match", "Avg. MAE", "Avg. median error", "Avg. Spearman"],
        [
            [
                x["date"], x["n"], x["obs"], pct(x["exact"]),
                fmt(x["mae"]), fmt(x["median"], 1), fmt(x["rho"], 3)
            ]
            for x in reversed(daily)
        ],
    )

    cumulative_table = table(
        ["Through date", "Snapshots included", "Observations", "Cumulative exact match", "Cumulative MAE", "Median error", "Pooled Spearman"],
        [
            [
                x["date"], x["count"], x["obs"], pct(x["exact"]),
                fmt(x["mae"]), fmt(x["median"], 1), fmt(x["rho"], 3)
            ]
            for x in reversed(cumulative)
        ],
    )

    snapshot_table = table(
        ["Snapshot", "Date (MT)", "Posts", "Exact match", "Mean error", "Median error", "Spearman"],
        [
            [
                html.escape(str(x["id"])), x["date"], x["n"],
                pct(x["exact"]), fmt(x["mae"]),
                fmt(x["median"], 1), fmt(x["rho"], 3)
            ]
            for x in reversed(snapshots)
        ],
    )

    post_rows = []

    for item in posts[:20]:
        title = html.escape(item["title"])

        if item["url"]:
            safe_url = html.escape(item["url"], quote=True)
            title = (
                f"<a href='{safe_url}' target='_blank' "
                f"rel='noopener'>{title}</a>"
            )

        post_rows.append([
            title,
            item["n"],
            fmt(item["mae"]),
            fmt(item["maxerr"], 0),
            fmt(item["votes"], 1),
            fmt(item["actual"], 1),
            fmt(item["pred"], 1),
        ])

    post_table = table(
        ["Post", "Appearances", "Avg. absolute error", "Max error", "Avg. upvotes", "Avg. actual rank", "Avg. predicted rank"],
        post_rows,
    )

    quality_table = table(
        ["Snapshot", "Date (MT)", "Rows", "Unique URLs", "Unique positions", "Position range", "Check"],
        [
            [
                html.escape(str(x["id"])),
                x["date"],
                x["n"],
                x["urls"],
                x["positions"],
                x["range"],
                "<b class='good'>PASS</b>" if x["ok"] else "<b class='bad'>CHECK</b>",
            ]
            for x in reversed(quality)
        ],
    )

    latest_items = sorted(
        snapshots[-1]["items"],
        key=lambda x: x["actual"]
    )

    chart_data = json.dumps({
        "daily": daily,
        "cumulative": cumulative,
        "latest": [
            {
                "actual": x["actual"],
                "predicted": x["predicted"],
                "title": x["title"],
            }
            for x in latest_items
        ],
    }, ensure_ascii=False).replace("</", "<\\/")

    generated = datetime.now(MT).strftime(
        "%b %d, %Y at %I:%M %p MT"
    )

    page = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Bear Blog Trending — Ranking Algorithm Analysis</title>
<meta name="description" content="Longitudinal analysis of Bear Blog Trending rankings compared with its published ranking formula.">
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
:root{--bg:#f4f5f7;--panel:#fff;--ink:#202532;--muted:#687181;--line:#e3e6eb;--accent:#5b61d6;--green:#16845b}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
header{background:#20202d;color:white;padding:38px max(24px,calc((100% - 1200px)/2)) 32px}
.eyebrow{font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:#c5c3dc;font-weight:700}
h1{font-size:clamp(28px,4vw,42px);line-height:1.12;margin:10px 0;letter-spacing:-.035em}
.sub{color:#d4d3df;max-width:780px;margin:0}
.meta{color:#b8b7c8;font-size:12px;margin-top:18px}
main{max-width:1200px;margin:28px auto 65px;padding:0 24px}
section{margin-top:30px}
h2{font-size:21px;margin:0;letter-spacing:-.02em}
.intro,.muted{color:var(--muted);font-size:13px;margin:4px 0 13px}
.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:13px}
.metric,.panel,.tablewrap{background:white;border:1px solid var(--line);border-radius:13px;box-shadow:0 8px 28px #1920300e}
.metric{padding:17px;min-height:116px}
.big{font-size:29px;font-weight:750;letter-spacing:-.04em;margin:7px 0 2px}
small{color:var(--muted);font-size:11px}
.charts{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.panel{padding:18px}
.panel strong{display:block;margin-bottom:12px}
canvas{width:100%;height:250px}
.tablewrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:12px;white-space:nowrap}
th,td{padding:10px 12px;text-align:left;border-bottom:1px solid var(--line)}
th{background:#f8f9fb;color:#586174;font-size:10px;text-transform:uppercase;letter-spacing:.06em}
tr:last-child td{border:0}
tbody tr:hover{background:#fafaff}
a{color:#4e57c9;text-decoration:none}
a:hover{text-decoration:underline}
.good{color:var(--green)}
.bad{color:#bd4b4b}
.defs{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.def,.note{background:white;border:1px solid var(--line);border-radius:10px;padding:14px 16px;color:var(--muted);font-size:13px}
.def b{display:block;color:var(--ink);margin-bottom:3px}
.note{margin-top:13px;border-left:3px solid var(--accent);border-radius:0 10px 10px 0}
footer{text-align:center;color:var(--muted);font-size:12px;padding-top:28px}
@media(max-width:800px){.grid{grid-template-columns:repeat(2,1fr)}.charts{grid-template-columns:1fr}}
@media(max-width:520px){main{padding:0 14px}header{padding:28px 18px}.defs{grid-template-columns:1fr}.metric{padding:13px}.big{font-size:23px}}
</style>
</head>
<body>
<header>
<div class="eyebrow">Longitudinal monitoring · INFO 4617</div>
<h1>Bear Blog Trending:<br>Ranking Algorithm Analysis</h1>
<p class="sub">How closely does Bear Blog’s published ranking formula predict the ordering of posts in its Trending feed over time?</p>
<div class="meta">Data: __FIRST__ – __LAST__ (Mountain Time) · Generated __GENERATED__ · Collection remains ongoing</div>
</header>
<main>
<section>
<h2>At a glance</h2>
<p class="intro">All collected post appearances; repeated appearances are counted again.</p>
<div class="grid">__CARDS__</div>
</section>

<section>
<h2>Performance over time</h2>
<p class="intro">Daily snapshot averages and cumulative results as observations accumulate.</p>
<div class="charts">
<div class="panel"><strong>Daily average ranking error</strong><canvas id="d1"></canvas></div>
<div class="panel"><strong>Daily exact-match rate</strong><canvas id="d2"></canvas></div>
<div class="panel"><strong>Cumulative mean absolute error</strong><canvas id="d3"></canvas></div>
<div class="panel"><strong>Latest snapshot: actual vs. predicted position</strong><canvas id="d4"></canvas></div>
</div>
</section>

<section><h2>Daily performance</h2><p class="intro">Each date averages the snapshots collected on that Mountain Time calendar day.</p>__DAILY__</section>
<section><h2>Cumulative performance</h2><p class="intro">Pooled observations from the first snapshot through each successive snapshot.</p>__CUMULATIVE__</section>
<section><h2>Snapshot-by-snapshot results</h2><p class="intro">Individual captures of the Trending feed, newest first.</p>__SNAPSHOTS__</section>
<section><h2>Posts with the largest discrepancies</h2><p class="intro">Posts ranked by average absolute difference between predicted and observed position.</p>__POSTS__</section>
<section><h2>Data quality checks</h2><p class="intro">Checks for duplicate URLs or positions within each snapshot.</p>__QUALITY__</section>

<section>
<h2>How to read the results</h2>
<p class="intro">Metric definitions and interpretation notes.</p>
<div class="defs">
<div class="def"><b>Exact-match rate</b>Percentage of observed posts for which predicted position equals actual Trending position.</div>
<div class="def"><b>Mean absolute error (MAE)</b>Average number of ranking positions separating predicted and actual positions. Lower is better.</div>
<div class="def"><b>Median absolute error</b>Middle absolute rank difference; less affected by unusually large mismatches.</div>
<div class="def"><b>Spearman correlation</b>Measures association between predicted and actual ordering. Values closer to 1 indicate stronger positive rank-order association.</div>
</div>
<div class="note"><b>Interpretation caution.</b> Pooled metrics count each post appearance, including repeat appearances across snapshots. These observations are therefore not statistically independent. Daily averages give each snapshot equal weight within its day. Predictive agreement does not establish that the published formula is the only factor determining Trending order.</div>
</section>

<footer>Automatically generated from ranking_observations.csv · Raw collection data is not modified.</footer>
</main>

<script>
const D = __CHART_DATA__;

const common = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
        legend: { labels: { color: "#596273" } }
    },
    scales: {
        x: {
            ticks: { color: "#737b8b" },
            grid: { color: "#64708a1c" }
        },
        y: {
            ticks: { color: "#737b8b" },
            grid: { color: "#64708a1c" }
        }
    }
};

function lineChart(id, labels, values, label, color) {
    new Chart(document.getElementById(id), {
        type: "line",
        data: {
            labels: labels,
            datasets: [{
                label: label,
                data: values,
                borderColor: color,
                backgroundColor: color + "22",
                fill: true,
                tension: 0.25,
                pointRadius: 3
            }]
        },
        options: common
    });
}

lineChart(
    "d1",
    D.daily.map(x => x.date),
    D.daily.map(x => x.mae),
    "Mean absolute error",
    "#5b61d6"
);

lineChart(
    "d2",
    D.daily.map(x => x.date),
    D.daily.map(x => x.exact),
    "Exact-match rate (%)",
    "#16845b"
);

lineChart(
    "d3",
    D.cumulative.map(x => "#" + x.count),
    D.cumulative.map(x => x.mae),
    "Cumulative MAE",
    "#8d72d6"
);

new Chart(document.getElementById("d4"), {
    type: "line",
    data: {
        labels: D.latest.map(x => "#" + x.actual),
        datasets: [
            {
                label: "Actual position",
                data: D.latest.map(x => x.actual),
                borderColor: "#16845b"
            },
            {
                label: "Predicted position",
                data: D.latest.map(x => x.predicted),
                borderColor: "#5b61d6"
            }
        ]
    },
    options: {
        ...common,
        scales: {
            ...common.scales,
            y: {
                ...common.scales.y,
                reverse: true,
                min: 1
            }
        },
        plugins: {
            tooltip: {
                callbacks: {
                    title: function(items) {
                        return D.latest[items[0].dataIndex]?.title || items[0].label;
                    }
                }
            }
        }
    }
});
</script>
</body>
</html>"""

    replacements = {
        "__FIRST__": html.escape(overall["first"]),
        "__LAST__": html.escape(overall["last"]),
        "__GENERATED__": html.escape(generated),
        "__CARDS__": card_html,
        "__DAILY__": daily_table,
        "__CUMULATIVE__": cumulative_table,
        "__SNAPSHOTS__": snapshot_table,
        "__POSTS__": post_table,
        "__QUALITY__": quality_table,
        "__CHART_DATA__": chart_data,
    }

    for key, value in replacements.items():
        page = page.replace(key, value)

    return page


def main():
    rows = read_data()
    result = analyze(rows)

    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(make_html(result), encoding="utf-8")

    overall = result[0]

    print("DASHBOARD BUILD COMPLETE")
    print("------------------------")
    print(f"Created: {DEST}")
    print(f"Snapshots: {overall['snapshots']}")
    print(f"Observations: {overall['n']}")
    print(f"Unique posts: {overall['posts']}")
    print(f"Exact matches: {pct(overall['exact'])}")
    print(f"Mean absolute error: {overall['mae']:.3f}")
    print("Original collection CSV was not modified.")


if __name__ == "__main__":
    main()

