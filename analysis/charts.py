"""Charts of the notebook; `python -m analysis.charts` writes the README ones to assets/charts/."""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from analysis import style
from analysis.style import (
    BORDER,
    BRONZE,
    CHAMPAGNE,
    CORAL,
    DEEP_BRONZE,
    EMERALD,
    GOLD,
    IVORY,
    MUTED,
    SURFACE,
)
from analysis.warehouse import ROOT, connect, run

OUT = ROOT / "assets" / "charts"


def short(name: str) -> str:
    """'Khvicha Kvaratskhelia' -> 'Kvaratskhelia' (labels inside charts)."""
    return {"Lamine Yamal": "Yamal", "Fabián Ruiz": "Fabián Ruiz"}.get(name, name.split()[-1])


def volume_vs_efficiency(df: pd.DataFrame) -> plt.Figure:
    """Q1: goals (volume) against non-penalty G+A per 90 (efficiency)."""
    winner = df.loc[df.vote_rank == 1, "player"].item()
    fig, ax = plt.subplots(figsize=(10, 5.6))
    d = df.assign(_focus=df.player == winner).sort_values("_focus")      # the winner drawn last, on top
    ax.scatter(d.goals, d.np_ga_per90, s=d.minutes / 14, c=style.focus_colours(d.player, winner),
               edgecolor=SURFACE, linewidth=1.5, zorder=3)
    ax.axhline(df.np_ga_per90.mean(), color=DEEP_BRONZE, ls="--", lw=1)
    ax.text(-2, df.np_ga_per90.mean() + 0.03, "average of the ten", ha="left", color=MUTED, fontsize=9)
    offsets = {"Erling Haaland": (-42, 16), "Kylian Mbappé": (12, -18), "Ousmane Dembélé": (-30, 15),
               "Michael Olise": (12, -17), "Khvicha Kvaratskhelia": (-118, 4), "Lamine Yamal": (11, -16),
               "Harry Kane": (-20, 17)}
    for _, r in d.iterrows():
        focus = r.player == winner
        ax.annotate(f"{short(r.player)}  #{r.vote_rank}", (r.goals, r.np_ga_per90),
                    xytext=offsets.get(r.player, (11, 5)), textcoords="offset points",
                    fontsize=10.5 if focus else 10, color=style.BRIGHT if focus else IVORY,
                    fontweight="semibold" if focus else "normal")
    ax.set_xlabel("Goals, all competitions (penalties included)")
    ax.set_ylabel("Non-penalty G+A per 90")
    ax.set_xlim(-4, 82)
    ax.set_ylim(-0.05, 1.7)
    ax.set_title("Most goals of anyone, only the fifth-best rate")
    style.subtitle(ax, "Bubble = minutes played · #n = place in the vote · 20 of the winner's 74 goals were penalties")
    style.source(fig)
    return fig


def big_games(df: pd.DataFrame) -> plt.Figure:
    """Q2: G+A in Champions League and World Cup knockouts."""
    d = df.sort_values(["big_stage_ko_ga", "vote_rank"], ascending=[True, False])
    winner = df.loc[df.vote_rank == 1, "player"].item()
    fig, ax = plt.subplots(figsize=(10, 5.6))
    bars = ax.barh([short(p) for p in d.player], d.big_stage_ko_ga, color=style.focus_colours(d.player, winner),
                   height=0.62, zorder=3)
    for b, (_, r) in zip(bars, d.iterrows()):
        ax.text(b.get_width() + 0.2, b.get_y() + b.get_height() / 2,
                f"{int(r.big_stage_ko_ga)}  ·  {int(r.big_stage_ko_matches)} matches",
                va="center", fontsize=9.5, color=IVORY if r.player != winner else style.BRIGHT)
    ax.set_xlim(0, d.big_stage_ko_ga.max() * 1.35)
    ax.grid(axis="y", visible=False)
    ax.tick_params(axis="y", length=0, labelsize=10.5, labelcolor=IVORY)
    ax.set_xlabel("Goals + assists in Champions League and World Cup knockout matches")
    ax.set_title("Nobody delivered more on the big stage")
    style.subtitle(ax, "Knockout rounds only · the winner in gold")
    style.source(fig)
    return fig


def index_vs_vote(df: pd.DataFrame, rho: float) -> plt.Figure:
    """Q4: index rank against the actual rank."""
    winner = df.loc[df.vote_rank == 1, "player"].item()
    fig, ax = plt.subplots(figsize=(8.6, 7))
    ax.plot([0.5, 10.5], [0.5, 10.5], color=BORDER, lw=1.2, zorder=1)
    ax.fill_between([0.5, 10.5], [0.5, 10.5], [10.5, 10.5], color=CORAL, alpha=0.05, zorder=0)
    ax.fill_between([0.5, 10.5], [0.5, 0.5], [0.5, 10.5], color=EMERALD, alpha=0.05, zorder=0)
    ax.scatter(df.vote_rank, df.index_rank, s=190, c=style.focus_colours(df.player, winner),
               edgecolor=SURFACE, linewidth=1.5, zorder=3)
    for _, r in df.iterrows():
        ax.annotate(short(r.player), (r.vote_rank, r.index_rank), xytext=(10, -4), textcoords="offset points",
                    fontsize=10, color=style.BRIGHT if r.player == winner else IVORY)
    ax.set_xlim(0.5, 10.5)
    ax.set_ylim(10.5, 0.5)
    ax.set_xticks(range(1, 11))
    ax.set_yticks(range(1, 11))
    ax.set_xlabel("Actual place in the vote")
    ax.set_ylabel("Place by the index (40% output · 35% trophies · 25% big games)")
    ax.text(9.9, 1.4, "index rates him\nhigher than voters", ha="right", color=EMERALD, fontsize=9, alpha=0.8)
    ax.text(1.1, 9.9, "index rates him\nlower than voters", ha="left", color=CORAL, fontsize=9, alpha=0.8)
    ax.set_title("The index finds the winner, not the order")
    style.subtitle(ax, f"On the diagonal = index agrees with the vote · places 2–10: Spearman ρ = {rho:+.2f}")
    style.source(fig)
    return fig


def vote_margin(df: pd.DataFrame) -> plt.Figure:
    """Q7: points of the top 10."""
    d = df.sort_values("vote_rank", ascending=False)
    fig, ax = plt.subplots(figsize=(10, 5.6))
    colours = [GOLD if r == 1 else (CHAMPAGNE if r == 2 else BRONZE) for r in d.vote_rank]
    bars = ax.barh([short(p) for p in d.player], d.points, color=colours, height=0.62, zorder=3)
    for b, p in zip(bars, d.points):
        ax.text(b.get_width() + 12, b.get_y() + b.get_height() / 2, f"{p:,}", va="center", fontsize=9.5, color=IVORY)
    top2 = df.nsmallest(2, "vote_rank").points.tolist()
    ax.text(top2[0] + 115, 8.5, f"+{top2[0] - top2[1]} points\n({(top2[0] - top2[1]) / top2[1]:.1%} ahead)",
            va="center", ha="left", color=style.BRIGHT, fontsize=10.5, fontweight="semibold", linespacing=1.3)
    ax.set_xlim(0, max(top2) * 1.3)
    ax.grid(axis="y", visible=False)
    ax.tick_params(axis="y", length=0, labelsize=10.5, labelcolor=IVORY)
    ax.set_xlabel("Ballon d'Or points")
    ax.set_title("The closest finish at the top")
    style.subtitle(ax, "2026 Ballon d'Or, points of the top 10")
    style.source(fig, "Data: Wikipedia, 2026 Ballon d'Or")
    return fig


def winner_form(df: pd.DataFrame, player: str) -> plt.Figure:
    """Q6: rolling five-match G+A of the winner."""
    d = df.copy()
    d["match_date"] = pd.to_datetime(d.match_date)
    fig, ax = plt.subplots(figsize=(12, 4.8))
    ax.fill_between(d.match_date, d.ga_rolling_5, color=GOLD, alpha=0.12, lw=0)
    ax.plot(d.match_date, d.ga_rolling_5, color=GOLD, lw=2.4, zorder=3)
    big = d[d.goals + d.assists >= 3]
    ax.scatter(big.match_date, big.ga_rolling_5, s=36, color=style.BRIGHT, edgecolor=SURFACE, zorder=4)
    ax.hlines(d.ga_rolling_5.mean(), d.match_date.min(), d.match_date.max(), color=MUTED, ls="--", lw=1)
    end = d.match_date.max() + pd.Timedelta(days=6)                      # label right of the line's end
    ax.text(end, d.ga_rolling_5.mean(), f"season\naverage\n{d.ga_rolling_5.mean():.2f}", ha="left", va="center",
            color=MUTED, fontsize=9, linespacing=1.2)
    ax.set_xlim(d.match_date.min() - pd.Timedelta(days=4), d.match_date.max() + pd.Timedelta(days=34))
    ax.set_ylim(0, None)
    ax.set_ylabel("G+A per match, last five matches")
    ax.xaxis.set_major_formatter(plt.matplotlib.dates.DateFormatter("%b %y"))
    ax.set_title(f"{player}: the season, match by match")
    style.subtitle(ax, f"{len(d)} matches in all competitions · dots = matches with 3+ goals and assists")
    style.source(fig)
    return fig


def finishing(df: pd.DataFrame) -> plt.Figure:
    """Q5: non-penalty goals minus npxG."""
    d = df.sort_values("np_goals_minus_npxg")
    fig, ax = plt.subplots(figsize=(10, 5.6))
    colours = [EMERALD if v > 0 else CORAL for v in d.np_goals_minus_npxg]
    bars = ax.barh([short(p) for p in d.player], d.np_goals_minus_npxg, color=colours, height=0.62, zorder=3)
    for b, v in zip(bars, d.np_goals_minus_npxg):
        ax.text(v + (0.3 if v >= 0 else -0.3), b.get_y() + b.get_height() / 2, f"{v:+.1f}",
                va="center", ha="left" if v >= 0 else "right", fontsize=9.5, color=IVORY)
    ax.axvline(0, color=MUTED, lw=1)
    ax.set_xlim(d.np_goals_minus_npxg.min() - 2.5, d.np_goals_minus_npxg.max() + 2.5)
    ax.grid(axis="y", visible=False)
    ax.tick_params(axis="y", length=0, labelsize=10.5, labelcolor=IVORY)
    ax.set_xlabel("Non-penalty goals − non-penalty xG")
    ax.set_title("Finishing above expectation")
    lo, hi = d.xg_coverage_pct.min(), d.xg_coverage_pct.max()
    style.subtitle(ax, f"Matches with xG only ({lo:.0f}–{hi:.0f}% of each player's minutes) · above 0 = scored more than expected")
    style.source(fig)
    return fig


def banner(winner: str, tiles: list[tuple[str, str]]) -> plt.Figure:
    """README header: title and four headline numbers."""
    fig = plt.figure(figsize=(16, 4.6))
    fig.patch.set_facecolor(style.BLACK)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 4.6)
    ax.text(0.6, 3.95, "BALLON D'OR 2026  ·  DATA ANALYTICS CASE STUDY", color=GOLD, fontsize=12.5,
            fontweight="semibold")
    ax.text(0.6, 3.05, f"{winner}'s Ballon d'Or, explained with data", color="#FFFFFF", fontsize=34, fontweight="bold")
    ax.text(0.6, 2.5, "Web scraping → Python ETL → star schema → SQL (DuckDB) → Power BI, on every match of the top-10 nominees",
            color=MUTED, fontsize=13.5)
    ax.plot([0.6, 15.4], [2.15, 2.15], color=GOLD, lw=1, alpha=0.6)
    w, gap = 3.55, 0.2
    for i, (value, label) in enumerate(tiles):
        x = 0.6 + i * (w + gap)
        ax.add_patch(plt.Rectangle((x, 0.45), w, 1.4, color=SURFACE, ec=BORDER, lw=1))
        ax.add_patch(plt.Rectangle((x, 0.45), 0.06, 1.4, color=GOLD, lw=0))
        ax.text(x + 0.3, 1.32, value, color="#FFFFFF", fontsize=26, fontweight="semibold", va="center")
        ax.text(x + 0.3, 0.75, label, color=CHAMPAGNE, fontsize=10.8, va="center")
    return fig


def spearman_2_to_10(df: pd.DataFrame) -> float:
    rest = df[df.vote_rank > 1]
    return float(np.corrcoef(rest.vote_rank.rank(), rest.index_rank.rank())[0, 1])


def build_all() -> list[Path]:
    style.apply()
    OUT.mkdir(parents=True, exist_ok=True)
    con = connect()
    q1, q2, q4, q7 = (run(con, k) for k in ("01", "02", "04", "07"))
    nominees = con.execute("SELECT player, vote_rank, minutes FROM v_nominee").df()
    q1 = q1.merge(nominees[["player", "minutes"]], on="player")
    winner = nominees.loc[nominees.vote_rank == 1, "player"].item()
    figures = {
        "01_volume_vs_efficiency": volume_vs_efficiency(q1),
        "02_big_games": big_games(q2),
        "04_index_vs_vote": index_vs_vote(q4, spearman_2_to_10(q4)),
        "07_vote_margin": vote_margin(q7),
    }
    w1 = q1[q1.vote_rank == 1].iloc[0]
    w2 = q2[q2.vote_rank == 1].iloc[0]
    margin = q7[q7.vote_rank == 1].iloc[0]
    figures["banner"] = banner(winner, [
        (f"{w1.goals}", f"goals, {w1.penalty_goals} of them penalties"),
        (f"{w1.per90_rank}th", f"of 10 in non-penalty G+A per 90 ({w1.np_ga_per90:.2f})"),
        (f"{w2.big_stage_ko_ga}", "G+A in UCL + World Cup knockouts, most"),
        (f"+{margin.lead_over_next}", f"points over the runner-up, a {margin.lead_over_next_pct:.1f}% margin"),
    ])
    paths = []
    for name, fig in figures.items():
        path = OUT / f"{name}.png"
        fig.savefig(path)
        plt.close(fig)
        paths.append(path)
    return paths


if __name__ == "__main__":
    for p in build_all():
        print("->", p.relative_to(ROOT))
