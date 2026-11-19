#!/usr/bin/env python3
"""Generate the charts embedded in report.md.

Run from the repository root:
    MPLCONFIGDIR=.mplcache python3 scripts/make_charts.py
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import TwoSlopeNorm

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "charts" / "data"
OUT = ROOT / "charts"

NAVY = "#1f3b5c"
RED = "#b23a3a"
GREEN = "#2e7d5b"
GRAY = "#8a8f98"
GOLD = "#c9a227"

plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 10.5,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.edgecolor": "#777777",
        "axes.labelcolor": "#333333",
        "text.color": "#222222",
        "xtick.color": "#444444",
        "ytick.color": "#444444",
        "figure.facecolor": "white",
        "savefig.facecolor": "white",
        "savefig.dpi": 170,
        "savefig.bbox": "tight",
    }
)


def _footer(fig: plt.Figure, text: str, y: float = -0.02) -> None:
    fig.text(0.01, y, text, fontsize=8, color="#666666", ha="left")


def chart_congress() -> None:
    scores = json.loads((DATA / "congress_21d.json").read_text())
    rows = sorted(scores, key=lambda r: r["mean_excess_disc"])
    names = [r["member"] for r in rows]
    values = [r["mean_excess_disc"] * 100 for r in rows]
    tstats = [r["t_stat"] for r in rows]
    colors = [GREEN if v > 0 else RED for v in values]

    fig, ax = plt.subplots(figsize=(9.2, 5.6))
    bars = ax.barh(names, values, color=colors, height=0.66, alpha=0.92)
    limit = max(abs(v) for v in values) + 2.2
    for bar, value, tstat in zip(bars, values, tstats):
        positive = value >= 0
        ax.text(
            value + (0.15 if positive else -0.15),
            bar.get_y() + bar.get_height() / 2,
            f"{value:+.1f}%   t={tstat:.2f}",
            va="center",
            ha="left" if positive else "right",
            fontsize=9,
            color="#333333",
        )
    ax.axvline(0, color="#444444", linewidth=1)
    ax.set_xlim(-limit, limit)
    ax.set_xlabel("Mean excess return vs QQQ, measured from the disclosure date (%)")
    ax.set_title(
        "Congressional disclosures show no robust edge",
        loc="left",
        fontsize=14,
        fontweight="bold",
        pad=22,
    )
    ax.text(
        0,
        1.015,
        "21 trading days · 4,031 trades · 11 members · significance threshold t ≥ 2",
        transform=ax.transAxes,
        fontsize=9.5,
        color="#666666",
    )
    _footer(
        fig,
        "Source: House Clerk periodic transaction reports (2024–2026), Alpaca IEX bars. "
        "Only Nancy Pelosi shows a positive point estimate (t=1.78, n=25); her weight is 0.08, provisional.",
    )
    fig.savefig(OUT / "congress_excess_21d.png")
    plt.close(fig)


def chart_horizons() -> None:
    horizons = (5, 21, 60)
    data = {
        h: {r["member"]: r for r in json.loads((DATA / f"congress_{h}d.json").read_text())}
        for h in horizons
    }
    members = sorted(
        set(data[21]) & set(data[5]) & set(data[60]),
        key=lambda m: data[21][m]["mean_excess_disc"],
        reverse=True,
    )
    matrix = np.array(
        [[data[h][m]["mean_excess_disc"] * 100 for h in horizons] for m in members]
    )
    limit = max(3.0, float(np.ceil(np.abs(matrix).max())))

    fig, ax = plt.subplots(figsize=(7.6, 5.4))
    image = ax.imshow(
        matrix,
        cmap="RdYlGn",
        norm=TwoSlopeNorm(vmin=-limit, vcenter=0, vmax=limit),
        aspect="auto",
    )
    ax.set_xticks(range(len(horizons)))
    ax.set_xticklabels([f"{h} days" for h in horizons])
    ax.set_yticks(range(len(members)))
    ax.set_yticklabels(members)
    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            value = matrix[i, j]
            ax.text(
                j, i, f"{value:+.1f}",
                ha="center", va="center", fontsize=9,
                color="white" if abs(value) > limit * 0.62 else "#222222",
            )
    colorbar = fig.colorbar(image, ax=ax, fraction=0.035, pad=0.02)
    colorbar.set_label("Excess vs QQQ (%)")
    ax.set_title(
        "The leading member changes with the horizon",
        loc="left",
        fontsize=14,
        fontweight="bold",
        pad=22,
    )
    ax.text(
        0, 1.015,
        "A stable edge should persist; here the ranking reshuffles across 5, 21 and 60 days.",
        transform=ax.transAxes, fontsize=9.5, color="#666666",
    )
    _footer(fig, "Cells show mean excess return from the disclosure date. Different horizons crown different 'winners'.")
    fig.savefig(OUT / "congress_horizon_heatmap.png")
    plt.close(fig)


def chart_funnel() -> None:
    funnel = json.loads((DATA / "funnel.json").read_text())
    panels = [
        ("whitelist", "Curated whitelist (15 accounts)", NAVY),
        ("validation", "Two-year validation (6 accounts)", GOLD),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(11.6, 4.4))
    fig.subplots_adjust(wspace=0.52, bottom=0.2)
    for ax, (key, label, color) in zip(axes, panels):
        block = funnel[key]
        stages = ["Consensus", "Signals", "Noise-filtered", "Downloaded"]
        values = [block["consensus"], block["signals"], block["accepted"], block["downloaded"]]
        bars = ax.barh(stages, values, color=[color, color, color, color], alpha=0.35)
        bars[1].set_alpha(0.6)
        bars[2].set_alpha(0.8)
        bars[3].set_alpha(0.95)
        max_value = block["downloaded"]
        for bar, value in zip(bars, values):
            if value >= max_value * 0.22:
                ax.text(
                    value - max_value * 0.02,
                    bar.get_y() + bar.get_height() / 2,
                    f"{value:,}",
                    va="center", ha="right", fontsize=10,
                    fontweight="bold", color="white",
                )
            else:
                ax.text(
                    max(value, 0) + max_value * 0.025,
                    bar.get_y() + bar.get_height() / 2,
                    f"{value:,}",
                    va="center", fontsize=10, fontweight="bold", color="#222222",
                )
        ax.set_xlim(0, max_value * 1.18)
        ax.set_title(label, loc="left", fontsize=11.5, fontweight="bold")
        ax.set_xlabel("Tweets / signals")
        ax.grid(axis="x", color="#dddddd", linewidth=0.8)
        ax.set_axisbelow(True)
    fig.suptitle(
        "From tweets to consensus: the funnel collapses at the voting stage",
        x=0.01, y=1.03, ha="left", fontsize=14, fontweight="bold",
    )
    _footer(
        fig,
        "Left: the celebrity whitelist produced zero three-account consensus over the period. "
        "Right: two low-weight accounts produced 40 signals, which lost money (see consensus chart).",
    )
    fig.savefig(OUT / "x_funnel.png")
    plt.close(fig)


def chart_weights() -> None:
    recent = {r["handle"]: r for r in json.loads((DATA / "x_discovery.json").read_text())}
    validated = {r["handle"]: r for r in json.loads((DATA / "x_validation.json").read_text())}
    handles = [h for h in validated if h in recent]
    handles.sort(key=lambda h: recent[h]["weight"], reverse=True)

    x = np.arange(len(handles))
    width = 0.36
    fig, ax = plt.subplots(figsize=(9.6, 5.4))
    fig.subplots_adjust(left=0.09, right=0.98, bottom=0.3, top=0.86)
    recent_values = [recent[h]["weight"] for h in handles]
    valid_values = [validated[h]["weight"] for h in handles]
    ax.bar(x - width / 2, recent_values, width, color=GRAY, label="Recent window (400 tweets)")
    ax.bar(x + width / 2, valid_values, width, color=NAVY, label="Two-year search")
    for i, handle in enumerate(handles):
        ax.text(
            i - width / 2, recent_values[i] + 0.006,
            f"n={recent[handle]['n_calls']}", ha="center", fontsize=8, color="#555555",
        )
        ax.text(
            i + width / 2, valid_values[i] + 0.006,
            f"n={validated[handle]['n_calls']}", ha="center", fontsize=8, color="#555555",
        )
    ax.set_xticks(x)
    ax.set_xticklabels(handles, rotation=18, ha="right")
    ax.set_ylabel("Credibility weight (0–1)")
    ax.set_ylim(0, max(max(recent_values), max(valid_values)) + 0.07)
    ax.legend(frameon=False, loc="upper right")
    ax.grid(axis="y", color="#dddddd", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_title(
        "Most discovered 'edges' did not survive a two-year sample",
        loc="left", fontsize=14, fontweight="bold", pad=22,
    )
    ax.text(
        0, 1.015,
        "Weights from the recent timeline vs historical search (2024–2026). n = scored calls.",
        transform=ax.transAxes, fontsize=9.5, color="#666666",
    )
    _footer(fig, "Only darkflowalert and ethan__trader kept a non-zero weight; curiouspejjy and stockmktnewz collapsed to zero.", y=0.015)
    fig.savefig(OUT / "x_weights_recent_vs_2y.png")
    plt.close(fig)


def chart_consensus() -> None:
    block = json.loads((DATA / "consensus_trades.json").read_text())
    trades = sorted(block["trades"], key=lambda t: t["date"])
    excess = np.array([t["excess"] * 100 for t in trades])
    cumulative = np.cumsum(excess)
    x = np.arange(1, len(trades) + 1)

    fig, ax = plt.subplots(figsize=(9.4, 4.6))
    ax.plot(x, cumulative, color=RED, linewidth=2.3, marker="o", markersize=3)
    ax.fill_between(x, cumulative, 0, where=cumulative < 0, color=RED, alpha=0.12)
    ax.axhline(0, color="#444444", linewidth=1)
    ax.set_xlabel("Trade number (chronological)")
    ax.set_ylabel("Cumulative excess return vs SPY (%)")
    ax.grid(axis="y", color="#dddddd", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.annotate(
        f"{cumulative[-1]:+.1f}%",
        xy=(x[-1], cumulative[-1]),
        xytext=(-6, -14), textcoords="offset points",
        ha="right", fontsize=11, fontweight="bold", color=RED,
    )
    ax.set_title(
        "Two-account consensus lost money",
        loc="left", fontsize=14, fontweight="bold", pad=22,
    )
    ax.text(
        0, 1.015,
        f"{block['n']} trades · {block['hit_rate']:.1%} hit rate · "
        f"{block['mean_excess']:+.2%} mean excess per trade",
        transform=ax.transAxes, fontsize=9.5, color="#666666",
    )
    _footer(fig, "Sum of per-trade excess returns (equal weight, not compounded). 7-day window, 2-account quorum; entry at next open, exit at horizon.")
    fig.savefig(OUT / "consensus_cumulative.png")
    plt.close(fig)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    chart_congress()
    chart_horizons()
    chart_funnel()
    chart_weights()
    chart_consensus()
    print("charts written to", OUT)


if __name__ == "__main__":
    main()
