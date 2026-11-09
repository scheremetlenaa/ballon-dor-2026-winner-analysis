"""Black-and-gold chart style shared by the notebook and the README charts."""
from __future__ import annotations

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib import font_manager

BLACK = "#000000"
SURFACE = "#0F0D08"
BORDER = "#3D3216"
GRID = "#2B2412"
GOLD = "#D4AF37"
BRIGHT = "#F2C94C"
CHAMPAGNE = "#EAD9A0"
BRONZE = "#8C6D2C"
DEEP_BRONZE = "#5E4A1C"
IVORY = "#F5EBD0"
MUTED = "#B9A57A"
EMERALD = "#3FBF8F"
CORAL = "#E5634D"


def _font() -> str:
    """Inter if installed (close to the dashboard's Segoe UI), else Segoe UI, else matplotlib's default."""
    installed = {f.name for f in font_manager.fontManager.ttflist}
    return next((f for f in ("Inter", "Segoe UI") if f in installed), "DejaVu Sans")


def apply() -> None:
    mpl.rcParams.update({
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
        "axes.edgecolor": BORDER,
        "axes.labelcolor": MUTED,
        "axes.titlecolor": "#FFFFFF",
        "axes.titlesize": 15,
        "axes.titleweight": "semibold",
        "axes.titlelocation": "left",
        "axes.titlepad": 26,
        "axes.labelsize": 10.5,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.color": GRID,
        "grid.linestyle": ":",
        "grid.linewidth": 1,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "text.color": IVORY,
        "font.family": _font(),
        "font.size": 10.5,
        "legend.frameon": False,
        "legend.labelcolor": CHAMPAGNE,
        "figure.dpi": 110,
        "savefig.dpi": 160,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.35,
    })


def subtitle(ax: plt.Axes, text: str) -> None:
    """Muted one-line subtitle under the axes title."""
    ax.annotate(text, xy=(0, 1), xycoords="axes fraction", xytext=(0, 6), textcoords="offset points",
                color=MUTED, fontsize=10, va="bottom", ha="left")


def source(fig: plt.Figure, text: str = "Data: SofaScore, Wikipedia · 2025/26 season, top-10 nominees") -> None:
    fig.text(0.01, -0.02, text, color=DEEP_BRONZE, fontsize=8.5, ha="left", va="top")


def focus_colours(names, focus: str, on: str = GOLD, off: str = BRONZE) -> list[str]:
    return [on if n == focus else off for n in names]
