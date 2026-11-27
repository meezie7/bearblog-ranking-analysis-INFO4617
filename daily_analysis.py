from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy.stats import spearmanr

INPUT = Path("ranking_observations.csv")
OUTPUT = Path("daily_analysis_output")

OUTPUT.mkdir(exist_ok=True)

if not INPUT.exists():
    raise FileNotFoundError(f"Cannot find {INPUT.resolve()}")

df = pd.read_csv(INPUT)

required = [
    "snapshot_id", "collected_at", "position", "title", "url",
    "upvotes", "predicted_position", "rank_difference",
    "absolute_rank_difference"
]

missing = [column for column in required if column not in df.columns]

if missing:
    raise ValueError(f"Missing required columns: {missing}")

df["collected_at"] = pd.to_datetime(df["collected_at"], utc=True)
df["local_date"] = (
    df["collected_at"]
    .dt.tz_convert("America/Denver")
    .dt.strftime("%Y-%m-%d")
)

df = df.sort_values(["collected_at", "position"]).copy()

# Recalculate the metrics independently from the stored rank differences.
df["calculated_rank_difference"] = (
    df["predicted_position"] - df["position"]
)
df["calculated_absolute_error"] = (
    df["calculated_rank_difference"].abs()
)

if not np.array_equal(
    df["calculated_rank_difference"],
    df["rank_difference"]
):
    raise ValueError("Stored rank differences do not match recalculated values.")

if not np.array_equal(
    df["calculated_absolute_error"],
    df["absolute_rank_difference"]
):
    raise ValueError("Stored absolute errors do not match recalculated values.")

# Calculate performance separately for every snapshot.
snapshot_rows = []

for snapshot_id, group in df.groupby("snapshot_id", sort=False):
    correlation = spearmanr(
        group["position"], group["predicted_position"]
    ).statistic

    snapshot_rows.append({
        "snapshot_id": snapshot_id,
        "collected_at": group["collected_at"].iloc[0],
        "local_date": group["local_date"].iloc[0],
        "observations": len(group),
        "exact_matches": (group["calculated_rank_difference"] == 0).sum(),
        "exact_match_percent": (
            group["calculated_rank_difference"] == 0
        ).mean() * 100,
        "mean_absolute_error": group["calculated_absolute_error"].mean(),
        "median_absolute_error": group["calculated_absolute_error"].median(),
        "spearman_correlation": correlation
    })

snapshot_results = pd.DataFrame(snapshot_rows)
snapshot_results = snapshot_results.sort_values("collected_at")

# Aggregate snapshot-level performance by local calendar day.
daily = (
    snapshot_results.groupby("local_date")
    .agg(
        snapshots=("snapshot_id", "nunique"),
        observations=("observations", "sum"),
        average_exact_match_percent=("exact_match_percent", "mean"),
        average_mean_absolute_error=("mean_absolute_error", "mean"),
        average_median_absolute_error=("median_absolute_error", "mean"),
        average_spearman=("spearman_correlation", "mean")
    )
    .reset_index()
)

# Calculate cumulative metrics after each snapshot.
cumulative_rows = []

for i in range(len(snapshot_results)):
    included_ids = snapshot_results.iloc[:i + 1]["snapshot_id"]
    subset = df[df["snapshot_id"].isin(included_ids)]

    cumulative_rows.append({
        "snapshots_included": i + 1,
        "through_local_date": snapshot_results.iloc[i]["local_date"],
        "observations": len(subset),
        "exact_matches": (
            subset["calculated_rank_difference"] == 0
        ).sum(),
        "exact_match_percent": (
            subset["calculated_rank_difference"] == 0
        ).mean() * 100,
        "mean_absolute_error": (
            subset["calculated_absolute_error"].mean()
        ),
        "median_absolute_error": (
            subset["calculated_absolute_error"].median()
        ),
        "pooled_spearman": spearmanr(
            subset["position"], subset["predicted_position"]
        ).statistic
    })

cumulative = pd.DataFrame(cumulative_rows)

# Find posts with the largest recurring discrepancies.
post_results = (
    df.groupby(["url", "title"])
    .agg(
        appearances=("snapshot_id", "nunique"),
        average_absolute_error=("calculated_absolute_error", "mean"),
        maximum_absolute_error=("calculated_absolute_error", "max"),
        average_upvotes=("upvotes", "mean"),
        average_actual_position=("position", "mean"),
        average_predicted_position=("predicted_position", "mean")
    )
    .reset_index()
    .sort_values(
        ["average_absolute_error", "appearances"],
        ascending=[False, False]
    )
)

# Export analysis tables. The original CSV is never modified.
snapshot_results.to_csv(OUTPUT / "snapshot_performance.csv", index=False)
daily.to_csv(OUTPUT / "daily_performance.csv", index=False)
cumulative.to_csv(OUTPUT / "cumulative_performance.csv", index=False)
post_results.to_csv(OUTPUT / "recurring_post_discrepancies.csv", index=False)

# Daily mean absolute error chart.
plt.figure(figsize=(11, 5))
plt.plot(
    daily["local_date"],
    daily["average_mean_absolute_error"],
    marker="o"
)
plt.title("Average Ranking Error by Day")
plt.xlabel("Collection date (Mountain Time)")
plt.ylabel("Mean absolute rank difference")
plt.xticks(rotation=45, ha="right")
plt.grid(alpha=0.25)
plt.tight_layout()
plt.savefig(OUTPUT / "daily_ranking_error.png", dpi=180)
plt.close()

# Daily exact-match chart.
plt.figure(figsize=(11, 5))
plt.plot(
    daily["local_date"],
    daily["average_exact_match_percent"],
    marker="o"
)
plt.title("Exact Ranking Matches by Day")
plt.xlabel("Collection date (Mountain Time)")
plt.ylabel("Average exact-match rate (%)")
plt.ylim(0, 100)
plt.xticks(rotation=45, ha="right")
plt.grid(alpha=0.25)
plt.tight_layout()
plt.savefig(OUTPUT / "daily_exact_match_rate.png", dpi=180)
plt.close()

# Cumulative performance chart.
plt.figure(figsize=(11, 5))
plt.plot(
    cumulative["snapshots_included"],
    cumulative["mean_absolute_error"],
    marker="o",
    label="Mean absolute rank difference"
)
plt.title("Cumulative Ranking Error as Data Accumulates")
plt.xlabel("Snapshots included")
plt.ylabel("Mean absolute rank difference")
plt.grid(alpha=0.25)
plt.legend()
plt.tight_layout()
plt.savefig(OUTPUT / "cumulative_ranking_error.png", dpi=180)
plt.close()

# Print a readable summary.
print("\nDAILY ANALYSIS COMPLETE")
print("-----------------------")
print(f"Snapshots: {len(snapshot_results)}")
print(f"Observations: {len(df)}")
print(f"Unique posts: {df['url'].nunique()}")
print(f"Collection dates: {daily['local_date'].nunique()}")

print("\nDAILY PERFORMANCE")
print(daily.round(3).to_string(index=False))

print("\nLATEST CUMULATIVE RESULT")
print(cumulative.tail(1).round(4).to_string(index=False))

print("\nMOST RECURRING RANKING DISCREPANCIES")
print(post_results.head(10).round(2).to_string(index=False))

print(f"\nFiles saved in: {OUTPUT.resolve()}")
print("Original dataset preserved.")
