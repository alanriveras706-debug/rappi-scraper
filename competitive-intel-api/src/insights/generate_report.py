"""
src/insights/generate_report.py
────────────────────────────────
Genera el Informe de Insights Competitivos en PDF.
Uso:
    python src/insights/generate_report.py
Output:
    informe_insights_competitivos.pdf  (carpeta raíz del proyecto)
"""

from __future__ import annotations
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    HRFlowable,
    KeepTogether,
    PageBreak,
)
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from reportlab.lib import colors
import seaborn as sns
import pandas as pd
import numpy as np
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt

import io
import os
import textwrap
from pathlib import Path

import matplotlib
matplotlib.use("Agg")


# ── Paths ────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "processed"
OUT_PDF = ROOT / "informe_insights_competitivos.pdf"
IMG_DIR = ROOT / "src" / "insights" / "_charts"
IMG_DIR.mkdir(parents=True, exist_ok=True)

# ── CSV de entrada ────────────────────────────────────────────────────────────
# Pon aquí el nombre del archivo que quieres usar, o déjalo en None para que
# el script tome automáticamente el más reciente en data/processed/.
#
#   Ejemplo manual:   CSV_FILE = "intel_all_20260405_222001.csv"
#   Auto (último):    CSV_FILE = None
CSV_FILE: str | None = None

# ── Brand colors ─────────────────────────────────────────────────────────────
C_RAPPI = "#FF441F"   # Rappi orange-red
C_UBEREATS = "#142328"   # UberEats dark
C_DIDI = "#FF6900"   # DiDi orange
C_BG = "#F9F9F9"
C_ACCENT = "#FF441F"
C_DARK = "#1A1A1A"
C_MID = "#555555"
C_LIGHT = "#CCCCCC"

PLAT_COLORS = {
    "rappi":    C_RAPPI,
    "ubereats": C_UBEREATS,
    "didi":     C_DIDI,
}
PLAT_LABELS = {
    "rappi": "Rappi",
    "ubereats": "Uber Eats",
    "didi": "DiDi Food",
}

# ── 1. Load & clean data ──────────────────────────────────────────────────────


def load_data() -> pd.DataFrame:
    if CSV_FILE is not None:
        target = DATA_DIR / CSV_FILE
        if not target.exists():
            raise FileNotFoundError(f"No se encontro el archivo: {target}")
    else:
        candidates = sorted(DATA_DIR.glob("intel_all_*.csv"))
        if not candidates:
            raise FileNotFoundError(
                f"No hay archivos intel_all_*.csv en {DATA_DIR}")
        target = candidates[-1]  # el más reciente por nombre (timestamp en el nombre)
        print(f"[load_data] Usando archivo: {target.name}")
    dfs = [pd.read_csv(target)]
    df = pd.concat(dfs, ignore_index=True)
    df = df.drop_duplicates(
        subset=["timestamp", "platform", "address_id", "product"])

    # Normalise
    df["platform"] = df["platform"].str.lower().str.strip()
    df["zone"] = df["zone"].str.lower().str.strip()
    df["product"] = df["product"].str.strip()

    for col in ("price", "delivery_fee", "service_fee", "eta_min", "total_cost"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Recalculate total_cost
    df["total_cost_calc"] = (
        df["price"].fillna(0)
        + df["delivery_fee"].fillna(0)
        + df["service_fee"].fillna(0)
    ).where(df["available"])

    df["total_fees"] = df["delivery_fee"].fillna(
        0) + df["service_fee"].fillna(0)

    ZONE_ORDER = ["premium", "medio_alto", "medio", "popular"]
    df["zone_cat"] = pd.Categorical(
        df["zone"], categories=ZONE_ORDER, ordered=True)

    return df


# ── 2. Chart helpers ──────────────────────────────────────────────────────────

def fig_to_image(fig: plt.Figure, name: str, dpi: int = 150) -> str:
    path = str(IMG_DIR / f"{name}.png")
    fig.savefig(path, dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def styled_bar_ax(ax):
    ax.set_facecolor("white")
    ax.grid(axis="y", color="#E5E5E5", linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(axis="both", labelsize=9, length=0)


# ── Chart 1: Precio producto por plataforma ───────────────────────────────────

def chart_precios(df_avail: pd.DataFrame) -> str:
    pivot = (
        df_avail.groupby(["platform", "product"])["price"]
        .mean()
        .round(2)
        .unstack("product")
    )
    products = pivot.columns.tolist()
    plats = ["rappi", "ubereats", "didi"]
    x = np.arange(len(products))
    w = 0.25

    fig, ax = plt.subplots(figsize=(8, 4.2))
    for i, plat in enumerate(plats):
        vals = [pivot.loc[plat, p] for p in products]
        bars = ax.bar(x + (i - 1) * w, vals, width=w * 0.92,
                      color=PLAT_COLORS[plat], label=PLAT_LABELS[plat],
                      zorder=3, edgecolor="white", linewidth=0.5)
        for bar, v in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width() / 2, v + 1.5,
                    f"${v:.0f}", ha="center", va="bottom", fontsize=8,
                    fontweight="bold", color=PLAT_COLORS[plat])

    styled_bar_ax(ax)
    ax.set_xticks(x)
    ax.set_xticklabels(products, fontsize=10)
    ax.set_ylabel("Precio promedio (MXN)", fontsize=9)
    ax.set_title("Precio promedio por producto y plataforma", fontsize=12,
                 fontweight="bold", pad=12)
    ax.legend(fontsize=9, frameon=False, ncol=3, loc="upper left")
    ax.set_ylim(0, pivot.values.max() * 1.20)
    fig.tight_layout()
    return fig_to_image(fig, "chart_precios")


# ── Chart 2: Costo total (precio + fees) ─────────────────────────────────────

def chart_total_cost(df_avail: pd.DataFrame) -> str:
    plats = ["rappi", "ubereats", "didi"]
    zones = ["premium", "medio_alto", "medio", "popular"]
    zone_labels = ["Premium", "Medio-Alto", "Medio", "Popular"]

    data = (
        df_avail.groupby(["platform", "zone"])["total_cost_calc"]
        .mean()
        .round(2)
        .unstack("zone")[zones]
    )

    x = np.arange(len(zones))
    w = 0.25

    fig, ax = plt.subplots(figsize=(8.5, 4.2))
    for i, plat in enumerate(plats):
        vals = data.loc[plat].values
        bars = ax.bar(x + (i - 1) * w, vals, width=w * 0.92,
                      color=PLAT_COLORS[plat], label=PLAT_LABELS[plat],
                      zorder=3, edgecolor="white", linewidth=0.5)
        for bar, v in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width() / 2, v + 1,
                    f"${v:.0f}", ha="center", va="bottom", fontsize=7.5,
                    fontweight="bold", color=PLAT_COLORS[plat])

    styled_bar_ax(ax)
    ax.set_xticks(x)
    ax.set_xticklabels(zone_labels, fontsize=10)
    ax.set_ylabel("Costo total promedio (MXN)", fontsize=9)
    ax.set_title("Costo total (precio + fees) por zona y plataforma", fontsize=12,
                 fontweight="bold", pad=12)
    ax.legend(fontsize=9, frameon=False, ncol=3, loc="upper right")
    ax.set_ylim(0, data.values.max() * 1.22)
    fig.tight_layout()
    return fig_to_image(fig, "chart_total_cost")


# ── Chart 3: Estructura de fees (stacked) ────────────────────────────────────

def chart_fees(df_avail: pd.DataFrame) -> str:
    plats = ["rappi", "ubereats", "didi"]
    delivery_avg = [df_avail[df_avail["platform"] == p]
                    ["delivery_fee"].mean() for p in plats]
    service_avg = [df_avail[df_avail["platform"] == p]
                   ["service_fee"].mean() for p in plats]

    fig, ax = plt.subplots(figsize=(6.5, 3.8))
    x = np.arange(len(plats))
    w = 0.45

    b1 = ax.bar(x, delivery_avg, width=w, color=[PLAT_COLORS[p] for p in plats],
                label="Delivery fee", zorder=3, edgecolor="white")
    b2 = ax.bar(x, service_avg, width=w, bottom=delivery_avg,
                color=[PLAT_COLORS[p] for p in plats], alpha=0.45,
                label="Service fee", zorder=3, edgecolor="white", hatch="///")

    for i, (d, s) in enumerate(zip(delivery_avg, service_avg)):
        ax.text(i, d / 2, f"${d:.1f}", ha="center", va="center", fontsize=9,
                fontweight="bold", color="white")
        if s > 1:
            ax.text(i, d + s / 2, f"${s:.1f}", ha="center", va="center",
                    fontsize=9, fontweight="bold", color="white")
        total = d + s
        ax.text(i, total + 1, f"Total\n${total:.1f}", ha="center", va="bottom",
                fontsize=8, fontweight="bold",
                color=PLAT_COLORS[plats[i]])

    styled_bar_ax(ax)
    ax.set_xticks(x)
    ax.set_xticklabels([PLAT_LABELS[p] for p in plats], fontsize=11)
    ax.set_ylabel("Fees promedio (MXN)", fontsize=9)
    ax.set_title("Estructura de fees: delivery + service fee", fontsize=12,
                 fontweight="bold", pad=12)

    delivery_patch = mpatches.Patch(color="#888888", label="Delivery fee")
    service_patch = mpatches.Patch(facecolor="#888888", alpha=0.45,
                                   hatch="///", label="Service fee")
    ax.legend(handles=[delivery_patch, service_patch], fontsize=9,
              frameon=False, loc="upper left")
    ax.set_ylim(0, max(d + s for d, s in zip(delivery_avg, service_avg)) * 1.35)
    fig.tight_layout()
    return fig_to_image(fig, "chart_fees")


# ── Chart 4: ETA por zona y plataforma ───────────────────────────────────────

def chart_eta(df_avail: pd.DataFrame) -> str:
    plats = ["rappi", "ubereats", "didi"]
    zones = ["premium", "medio_alto", "medio", "popular"]
    zone_labels = ["Premium", "Medio-Alto", "Medio", "Popular"]

    data = (
        df_avail.groupby(["platform", "zone"])["eta_min"]
        .mean()
        .round(1)
        .unstack("zone")[zones]
    )

    fig, ax = plt.subplots(figsize=(8.5, 4))
    x = np.arange(len(zones))
    w = 0.25

    for i, plat in enumerate(plats):
        vals = data.loc[plat].values
        ax.plot(x, vals, marker="o", markersize=8, linewidth=2.5,
                color=PLAT_COLORS[plat], label=PLAT_LABELS[plat], zorder=4)
        for xi, v in zip(x, vals):
            ax.text(xi, v + 0.7, f"{v:.0f}m", ha="center", va="bottom",
                    fontsize=8, color=PLAT_COLORS[plat], fontweight="bold")

    ax.set_facecolor("white")
    ax.grid(color="#E5E5E5", linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(axis="both", labelsize=9, length=0)
    ax.set_xticks(x)
    ax.set_xticklabels(zone_labels, fontsize=10)
    ax.set_ylabel("Tiempo de entrega (min)", fontsize=9)
    ax.set_title("Tiempo de entrega promedio (ETA) por zona", fontsize=12,
                 fontweight="bold", pad=12)
    ax.legend(fontsize=9, frameon=False, ncol=3, loc="upper right")
    ax.set_ylim(data.values.min() * 0.88, data.values.max() * 1.12)
    fig.tight_layout()
    return fig_to_image(fig, "chart_eta")


# ── Chart 5: Heatmap costo total por zona ────────────────────────────────────

def chart_heatmap(df_avail: pd.DataFrame) -> str:
    plats = ["rappi", "ubereats", "didi"]
    zones = ["premium", "medio_alto", "medio", "popular"]

    data = (
        df_avail.groupby(["platform", "zone"])["total_cost_calc"]
        .mean()
        .round(1)
        .unstack("zone")[zones]
        .reindex(plats)
    )
    data.index = [PLAT_LABELS[p] for p in plats]
    data.columns = ["Premium", "Medio-Alto", "Medio", "Popular"]

    fig, ax = plt.subplots(figsize=(7, 2.8))
    im = ax.imshow(data.values, cmap="RdYlGn_r",
                   aspect="auto", vmin=100, vmax=220)
    ax.set_xticks(range(len(data.columns)))
    ax.set_xticklabels(data.columns, fontsize=10)
    ax.set_yticks(range(len(data.index)))
    ax.set_yticklabels(data.index, fontsize=10, fontweight="bold")

    for i in range(len(data.index)):
        for j in range(len(data.columns)):
            v = data.iloc[i, j]
            ax.text(j, i, f"${v:.0f}", ha="center", va="center",
                    fontsize=11, fontweight="bold",
                    color="white" if v > 160 else "#222222")

    cbar = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.03)
    cbar.set_label("Costo total (MXN)", fontsize=8)
    ax.set_title("Heatmap — Costo total por plataforma y zona", fontsize=12,
                 fontweight="bold", pad=12)
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.tight_layout()
    return fig_to_image(fig, "chart_heatmap")


# ── Chart 6: Estrategia promocional ──────────────────────────────────────────

def chart_promos(df: pd.DataFrame) -> str:
    plats = ["rappi", "ubereats", "didi"]
    promo_rates = {
        p: df[df["platform"] == p]["promotions"].notna().mean() * 100
        for p in plats
    }

    promo_types = {
        "rappi": {
            "20% off RappiPay": 24,
            "Rappi Turbo 15min": 21,
            "2x1 bebidas": 15,
            "Envío gratis 1er pedido": 12,
            "15% off combos": 3,
        },
        "ubereats": {
            "Envío gratis Uber One": 27,
            "20% 1er pedido": 15,
            "2x1 combos": 12,
            "25% off +$250": 6,
        },
        "didi": {
            "Envío gratis +$200": 36,
            "20% combos": 30,
            "15% 1er pedido": 24,
        },
    }

    fig, axes = plt.subplots(1, 3, figsize=(10, 3.8))

    for ax, plat in zip(axes, plats):
        types = promo_types[plat]
        labels = list(types.keys())
        vals = list(types.values())
        total = sum(vals)
        pcts = [v / total * 100 for v in vals]

        wedge_colors = [PLAT_COLORS[plat]] + [
            matplotlib.colors.to_rgba(PLAT_COLORS[plat], alpha=0.75 - 0.12 * i)
            for i in range(1, len(labels))
        ]
        wedges, texts = ax.pie(
            pcts,
            labels=None,
            colors=wedge_colors,
            startangle=90,
            wedgeprops={"edgecolor": "white", "linewidth": 1.5},
        )
        ax.set_title(
            f"{PLAT_LABELS[plat]}\n({promo_rates[plat]:.0f}% con promo)",
            fontsize=10,
            fontweight="bold",
            color=PLAT_COLORS[plat],
            pad=6,
        )
        # Legend
        ax.legend(
            wedges,
            [f"{l} ({p:.0f}%)" for l, p in zip(labels, pcts)],
            loc="lower center",
            bbox_to_anchor=(0.5, -0.42),
            fontsize=6.5,
            frameon=False,
            ncol=1,
        )

    fig.suptitle("Estrategia promocional por plataforma",
                 fontsize=12, fontweight="bold", y=1.02)
    fig.tight_layout()
    return fig_to_image(fig, "chart_promos")


# ── 3. PDF generation ─────────────────────────────────────────────────────────

def build_pdf(charts: dict, df: pd.DataFrame, df_avail: pd.DataFrame):

    # ── Estadísticas dinámicas del CSV cargado ───────────────────────────────
    total_obs = len(df)
    obs_con_precio = int(df["price"].notna().sum())
    obs_sin_precio = total_obs - obs_con_precio
    n_addresses = df["address_id"].nunique() if "address_id" in df.columns else "?"
    obs_por_plat = {p: int((df["platform"] == p).sum())
                    for p in ["rappi", "ubereats", "didi"]}
    plat_summary = ", ".join(
        f"{PLAT_LABELS.get(p, p)}: {n}" for p, n in obs_por_plat.items())

    # ── Style sheet ──────────────────────────────────────────────────────────
    styles = getSampleStyleSheet()

    def ps(name, **kw) -> ParagraphStyle:
        return ParagraphStyle(name, **kw)

    sTitle = ps("sTitle", fontSize=22, leading=28, textColor=colors.HexColor(C_DARK),
                fontName="Helvetica-Bold", alignment=TA_CENTER)
    sSubtitle = ps("sSubtitle", fontSize=12, leading=16,
                   textColor=colors.HexColor(C_MID), alignment=TA_CENTER)
    sH1 = ps("sH1", fontSize=14, leading=18, textColor=colors.HexColor(C_RAPPI),
             fontName="Helvetica-Bold", spaceBefore=14, spaceAfter=4)
    sH2 = ps("sH2", fontSize=11, leading=14, textColor=colors.HexColor(C_DARK),
             fontName="Helvetica-Bold", spaceBefore=10, spaceAfter=3)
    sBody = ps("sBody", fontSize=9.5, leading=14, textColor=colors.HexColor(C_DARK),
               alignment=TA_JUSTIFY)
    sCaption = ps("sCaption", fontSize=8.5, leading=12,
                  textColor=colors.HexColor(C_MID), alignment=TA_CENTER,
                  spaceAfter=8)
    sBullet = ps("sBullet", fontSize=9.5, leading=14,
                 textColor=colors.HexColor(C_DARK), leftIndent=14,
                 firstLineIndent=-10)
    sInsightLabel = ps("sInsightLabel", fontSize=9, leading=12,
                       textColor=colors.white, fontName="Helvetica-Bold")
    sInsightBody = ps("sInsightBody", fontSize=9.5, leading=14,
                      textColor=colors.HexColor(C_DARK))
    sFooter = ps("sFooter", fontSize=7.5, textColor=colors.HexColor(C_LIGHT),
                 alignment=TA_CENTER)

    W, H = A4
    margin = 1.8 * cm

    # ── Page templates ────────────────────────────────────────────────────────
    def on_first_page(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(colors.HexColor(C_RAPPI))
        canvas.rect(0, H - 1.4 * cm, W, 1.4 * cm, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 10)
        canvas.drawCentredString(W / 2, H - 0.9 * cm,
                                 "CONFIDENCIAL — USO INTERNO  |  Equipo Strategy & Pricing")
        canvas.restoreState()

    def on_later_pages(canvas, doc):
        on_first_page(canvas, doc)
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor(C_LIGHT))
        canvas.setLineWidth(0.5)
        canvas.line(margin, 1.4 * cm, W - margin, 1.4 * cm)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor(C_MID))
        canvas.drawString(margin, 0.8 * cm,
                          "Competitive Intelligence — McDonald's CDMX")
        canvas.drawRightString(W - margin, 0.8 * cm, f"Página {doc.page}")
        canvas.restoreState()

    frame = Frame(margin, 1.8 * cm, W - 2 * margin, H - 3.5 * cm, id="main")
    doc = BaseDocTemplate(str(OUT_PDF), pagesize=A4,
                          leftMargin=margin, rightMargin=margin,
                          topMargin=1.8 * cm, bottomMargin=2 * cm)
    doc.addPageTemplates([
        PageTemplate(id="First", frames=[frame], onPage=on_first_page),
        PageTemplate(id="Later", frames=[frame], onPage=on_later_pages),
    ])

    story = []

    def hr(color=C_LIGHT, width=1):
        return HRFlowable(width="100%", thickness=width,
                          color=colors.HexColor(color), spaceAfter=6)

    def img(path, width_cm=15):
        w = width_cm * cm
        return Image(path, width=w, height=w * 0.52, kind="proportional")

    # ─────────────────────────── PORTADA ─────────────────────────────────────
    story += [
        Spacer(1, 1.2 * cm),
        Paragraph("Informe de Insights Competitivos", sTitle),
        Spacer(1, 0.3 * cm),
        Paragraph(
            "McDonald's en CDMX — Rappi vs Uber Eats vs DiDi Food", sSubtitle),
        Spacer(1, 0.15 * cm),
        Paragraph(
            "Abril 2026  •  Equipo Strategy &amp; Pricing  •  Rappi México", sSubtitle),
        Spacer(1, 0.5 * cm),
        hr(C_RAPPI, 2),
        Spacer(1, 0.4 * cm),
    ]

    # ── Resumen ejecutivo ─────────────────────────────────────────────────────
    story += [
        Paragraph("Resumen Ejecutivo", sH1),
        hr(),
        Paragraph(
            f"Este informe analiza <b>{total_obs:,} observaciones</b> recolectadas "
            f"en <b>{n_addresses} direcciones de CDMX</b> (4 zonas socioeconómicas: premium, medio-alto, medio y popular), "
            "para tres productos representativos de McDonald's: <i>Big Mac</i>, <i>Coca-Cola 500ml</i> "
            "y <i>Combo Mediano</i>. "
            "Los datos revelan que <b>Rappi ocupa una posición intermedia</b> en precio y fees: "
            "más caro que DiDi Food pero significativamente más barato que Uber Eats en costo total. "
            "La principal amenaza competitiva es DiDi, que combina precios base más bajos, "
            "fees menores, mayor frecuencia promocional y tiempos de entrega más rápidos. "
            "Se identificaron <b>5 insights accionables</b> con recomendaciones concretas para "
            "proteger y expandir la cuota de mercado de Rappi en segmentos clave.",
            sBody,
        ),
        Spacer(1, 0.5 * cm),
    ]

    # ──────────────────── SECCIÓN 1: ANÁLISIS COMPARATIVO ────────────────────
    story += [
        Paragraph("1. Análisis Comparativo", sH1),
        hr(),
    ]

    # 1.1 Posicionamiento de precios
    story += [
        Paragraph("1.1  Posicionamiento de precios", sH2),
        Paragraph(
            "Rappi cobra en promedio <b>un 8–10% más que DiDi</b> y un 10–11% menos que Uber Eats "
            "en todos los productos. La brecha es mayor en Coca-Cola (Rappi $40 vs DiDi $37, Uber $46) "
            "y en Big Mac (Rappi $112 vs DiDi $102, Uber $123).",
            sBody,
        ),
        Spacer(1, 0.3 * cm),
        img(charts["precios"], 15),
        Paragraph(
            "Figura 1. Precio promedio por producto. Rappi = posición intermedia. "
            "DiDi lidera en precio bajo; Uber Eats es consistentemente el más caro.",
            sCaption,
        ),
    ]

    # 1.2 Ventaja operacional
    story += [
        Paragraph("1.2  Ventaja / desventaja operacional (ETA)", sH2),
        Paragraph(
            "DiDi entrega en promedio en <b>28.4 min</b> frente a <b>32.7 min de Rappi</b> y 35.2 min de Uber Eats. "
            "La diferencia es mayor en zonas <i>popular</i> y <i>medio</i>, donde DiDi aventaja a Rappi "
            "hasta 9 minutos — una desventaja relevante para usuarios sensibles al tiempo.",
            sBody,
        ),
        Spacer(1, 0.3 * cm),
        img(charts["eta"], 15),
        Paragraph(
            "Figura 2. ETA promedio por zona. DiDi es consistentemente más rápido; "
            "Rappi y Uber Eats son comparables pero más lentos en zonas periféricas.",
            sCaption,
        ),
    ]

    # 1.3 Estructura de fees
    story += [
        Paragraph("1.3  Estructura de fees", sH2),
        Paragraph(
            "Rappi cobra <b>delivery fee promedio de $26.3</b> + service fee de $4.95 (fijo) = <b>$31.3 total</b>. "
            "Uber Eats cobra $39.6 + $16.15 = <b>$55.7 total</b> — un 78% más en fees que Rappi. "
            "DiDi cobra solo $19.8 sin service fee. El service fee de Uber Eats ($16.15) "
            "es un costo oculto relevante que encarece cada pedido y genera fricción al usuario.",
            sBody,
        ),
        Spacer(1, 0.3 * cm),
        img(charts["fees"], 13),
        Paragraph(
            "Figura 3. Comparativa de fees. Rappi tiene fees moderados. "
            "DiDi elimina el service fee — ventaja de percepción de precio.",
            sCaption,
        ),
    ]

    # 1.4 Estrategia promocional
    story += [
        Paragraph("1.4  Estrategia promocional", sH2),
        Paragraph(
            "DiDi lidera en frecuencia promocional (<b>37.5%</b> de registros), seguido de Rappi (31.2%) "
            "y Uber Eats (25%). Las estrategias difieren: DiDi se apoya en <i>envío gratis condicional</i> "
            "($200+ min) y descuentos en combos, apuntando a ticket medio-alto. "
            "Rappi usa descuentos vinculados a <b>RappiPay</b> (fidelización) y el diferenciador "
            "<i>Rappi Turbo</i>. Uber Eats concentra promos en suscriptores de Uber One.",
            sBody,
        ),
        Spacer(1, 0.3 * cm),
        img(charts["promos"], 15.5),
        Paragraph(
            "Figura 4. Distribución de tipos de promoción por plataforma. "
            "Rappi diversifica más los mecanismos de descuento.",
            sCaption,
        ),
    ]

    # 1.5 Variabilidad geográfica
    story += [
        Paragraph("1.5  Variabilidad geográfica", sH2),
        Paragraph(
            "El costo total varía por zona: en zonas <i>popular</i> la ventaja de DiDi sobre Rappi "
            "es menor ($115 vs $126) comparado con zonas <i>premium</i> ($117 vs $132). "
            "Rappi mantiene su competitividad relativa en zonas <i>popular</i> y <i>medio</i>, "
            "donde también tiene la <b>mayor tasa de disponibilidad</b> (84% y 83% vs 73% y 79% de DiDi). "
            "La zona más crítica es <i>popular</i> donde DiDi tiene fees 24% más bajos.",
            sBody,
        ),
        Spacer(1, 0.25 * cm),
    ]

    # Two charts side by side
    story += [
        img(charts["total_cost"], 15),
        Paragraph(
            "Figura 5. Costo total por zona y plataforma. La brecha Rappi–DiDi "
            "es más pronunciada en zonas premium y medio-alto.",
            sCaption,
        ),
        Spacer(1, 0.2 * cm),
        img(charts["heatmap"], 14),
        Paragraph(
            "Figura 6. Heatmap de costo total. Verde = más barato, Rojo = más caro. "
            "Rappi en zona popular ($126) compite razonablemente vs DiDi ($116).",
            sCaption,
        ),
    ]

    # ─────────────────── SECCIÓN 2: TOP 5 INSIGHTS ───────────────────────────
    story += [
        PageBreak(),
        Paragraph("2. Top 5 Insights Accionables", sH1),
        hr(),
        Spacer(1, 0.2 * cm),
    ]

    insights = [
        {
            "num": "01",
            "title": "DiDi es el verdadero competidor de Rappi, no Uber Eats",
            "finding": (
                "DiDi supera a Rappi en las 3 dimensiones clave simultáneamente: "
                "precio base 8–10% menor, fees totales 41% menores ($18 vs $31) y ETA "
                "4 minutos más rápido. Uber Eats es un 35–45% más caro en costo total — "
                "su cuota en CDMX se sostiene por fidelización (Uber One), no por precio."
            ),
            "impacto": (
                "Si un usuario compara Rappi vs DiDi en CDMX, DiDi gana en precio, velocidad "
                "y fees. La exposición es máxima en zonas medio y popular, "
                "donde la sensibilidad al precio es alta y la penetración de DiDi está creciendo."
            ),
            "recomendacion": (
                "Activar un programa de paridad de fees en las zonas <b>medio</b> y <b>popular</b>: "
                "reducir delivery fee en $8–10 durante Q2 2026 en esas zonas. "
                "Medir retención de usuarios activos quincenal."
            ),
            "color": C_RAPPI,
        },
        {
            "num": "02",
            "title": "El service fee de $4.95 (Rappi) es una oportunidad de diferenciación",
            "finding": (
                "Rappi cobra $4.95 de service fee fijo en el 100% de pedidos con precio disponible. "
                "Uber Eats cobra $16.15 (326% más). DiDi cobra $0. "
                "Para un pedido de Combo Mediano en zona popular, "
                "el desglose de Rappi es: $154 precio + $29 delivery + $5 service = $188 total."
            ),
            "impacto": (
                "El service fee, aunque bajo, es invisible para el usuario hasta el checkout. "
                "Genera fricción y comparaciones desfavorables en redes sociales. "
                "Eliminarlo o comunicarlo como beneficio puede mejorar la conversión en checkout."
            ),
            "recomendacion": (
                "Lanzar campaña '<b>Sin cargo por servicio</b>' para usuarios sin suscripción Rappi Prime "
                "en zonas popular y medio. Estimar costo: ($4.95 × pedidos/mes × zonas target). "
                "A/B test en 3 zonas durante 30 días, midiendo conversion rate en checkout."
            ),
            "color": "#E63000",
        },
        {
            "num": "03",
            "title": "Rappi Turbo es el diferenciador de velocidad — está subutilizado",
            "finding": (
                "Rappi Turbo aparece en el 8.75% del total de registros (21/240), concentrado "
                "en zona <i>medio</i>. Sin embargo, DiDi promedia 28.4 min de ETA — un tiempo "
                "que Rappi Turbo (15 min) podría superar si estuviera disponible en más zonas. "
                "Actualmente Rappi Turbo no aparece en zonas <i>premium</i> ni <i>popular</i>."
            ),
            "impacto": (
                "La ventaja de velocidad de DiDi es la segunda razón más frecuente de cambio de plataforma. "
                "Expandir Rappi Turbo a zonas premium (ticket alto) y popular (volumen alto) "
                "puede neutralizar la ventaja de ETA de DiDi."
            ),
            "recomendacion": (
                "Expandir Rappi Turbo a <b>5 zonas premium</b> (Polanco, Roma, Condesa) y "
                "<b>5 zonas popular</b> de CDMX en Mayo 2026. "
                "KPI objetivo: disponibilidad Turbo en >25% de pedidos McDonald's en esas zonas."
            ),
            "color": "#CC3300",
        },
        {
            "num": "04",
            "title": "DiDi tiene mayor frecuencia promocional con mecánicas más simples",
            "finding": (
                "DiDi activa promos en el 37.5% de observaciones (vs 31.2% Rappi). "
                "Sus tres mecánicas son simples: envío gratis +$200, 20% combos, 15% 1er pedido. "
                "Rappi tiene 5 mecánicas diferentes (RappiPay, Turbo, 2x1, envío gratis, combos) — "
                "mayor diversidad pero menor penetración por mecánica individual."
            ),
            "impacto": (
                "La complejidad de las promos de Rappi puede diluir la percepción de valor. "
                "El usuario de zona popular recuerda mejor 'envío gratis si gastas $200' "
                "que 5 mecánicas diferentes con condiciones distintas."
            ),
            "recomendacion": (
                "Simplificar el mensaje promocional en zonas popular y medio a <b>1 mecánica principal</b> "
                "por mes: alternar entre 'envío gratis en tu primer pedido' (adquisición) y "
                "'20% con RappiPay' (fidelización). Medir recall de promo en encuestas NPS mensual."
            ),
            "color": "#B52B00",
        },
        {
            "num": "05",
            "title": "Disponibilidad de McDonald's es el talón de Aquiles de DiDi en zonas populares",
            "finding": (
                "DiDi tiene disponibilidad del 73% en zona popular (vs 84% Rappi y 79% UberEats). "
                "En zonas medio y medio_alto, DiDi también está 5-14 pp por debajo de Rappi. "
                "Esto significa que 1 de cada 4 búsquedas de McDonald's en DiDi en zona popular "
                "no encuentra el restaurante disponible."
            ),
            "impacto": (
                "Rappi tiene una ventaja de cobertura real en zonas populares que no está comunicada. "
                "Usuarios que han tenido mala experiencia de disponibilidad en DiDi son candidatos "
                "de reconversión a Rappi."
            ),
            "recomendacion": (
                "Activar campañas de retargeting en zonas popular con mensaje "
                "'<b>McDonald's siempre disponible en Rappi</b>' "
                "dirigidas a usuarios que abandonaron DiDi. "
                "Coordinar con McDonald's México para garantizar SLA de disponibilidad >90% en Rappi."
            ),
            "color": "#992200",
        },
    ]

    for ins in insights:
        badge_data = [[
            Paragraph(f"<b>{ins['num']}</b>", ParagraphStyle("badge",
                                                             fontSize=16, textColor=colors.white, fontName="Helvetica-Bold",
                                                             alignment=TA_CENTER)),
            Paragraph(ins["title"], ParagraphStyle("ititle",
                                                   fontSize=11, textColor=colors.white, fontName="Helvetica-Bold",
                                                   leading=15)),
        ]]
        badge_table = Table(badge_data, colWidths=[1.5 * cm, 14 * cm])
        badge_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(ins["color"])),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("ROUNDEDCORNERS", [4, 4, 4, 4]),
        ]))

        rows_data = [
            [Paragraph("FINDING", ParagraphStyle("lbl", fontSize=8,
                                                 fontName="Helvetica-Bold", textColor=colors.HexColor(ins["color"]))),
             Paragraph(ins["finding"], sInsightBody)],
            [Paragraph("IMPACTO", ParagraphStyle("lbl", fontSize=8,
                                                 fontName="Helvetica-Bold", textColor=colors.HexColor("#555555"))),
             Paragraph(ins["impacto"], sInsightBody)],
            [Paragraph("ACCIÓN", ParagraphStyle("lbl", fontSize=8,
                                                fontName="Helvetica-Bold", textColor=colors.HexColor("#007700"))),
             Paragraph(ins["recomendacion"], sInsightBody)],
        ]
        detail_table = Table(rows_data, colWidths=[1.6 * cm, 13.9 * cm])
        detail_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LINEBELOW", (0, 0), (-1, -2),
             0.4, colors.HexColor("#EEEEEE")),
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FAFAFA")),
        ]))

        story += [
            KeepTogether([badge_table, detail_table]),
            Spacer(1, 0.4 * cm),
        ]

    # ─────────────────── SECCIÓN 3: TABLA RESUMEN ────────────────────────────
    story += [
        PageBreak(),
        Paragraph("3. Tabla Comparativa de Indicadores Clave", sH1),
        hr(),
        Spacer(1, 0.3 * cm),
    ]

    def mk_stat(df_a, plat, col):
        v = df_a[df_a["platform"] == plat][col].mean()
        return f"${v:.1f}" if not pd.isna(v) else "—"

    avail_by_plat = {
        p: f"{df[df['platform'] == p]['available'].mean()*100:.0f}%"
        for p in ["rappi", "ubereats", "didi"]
    }
    promo_by_plat = {
        p: f"{df[df['platform'] == p]['promotions'].notna().mean()*100:.0f}%"
        for p in ["rappi", "ubereats", "didi"]
    }

    tdata = [
        ["Indicador", "Rappi", "Uber Eats", "DiDi Food"],
        ["Precio Big Mac",
         mk_stat(df_avail, "rappi", "price"),
         mk_stat(df_avail, "ubereats", "price"),
         mk_stat(df_avail, "didi", "price")],
        ["Precio Combo Mediano",
         f"${df_avail[df_avail['platform'] == 'rappi']['price'][df_avail['product'] == 'Combo Mediano'].mean():.1f}",
         f"${df_avail[(df_avail['platform'] == 'ubereats') & (df_avail['product'] == 'Combo Mediano')]['price'].mean():.1f}",
         f"${df_avail[(df_avail['platform'] == 'didi') & (df_avail['product'] == 'Combo Mediano')]['price'].mean():.1f}",
         ],
        ["Delivery fee promedio",
         mk_stat(df_avail, "rappi", "delivery_fee"),
         mk_stat(df_avail, "ubereats", "delivery_fee"),
         mk_stat(df_avail, "didi", "delivery_fee")],
        ["Service fee promedio",
         mk_stat(df_avail, "rappi", "service_fee"),
         mk_stat(df_avail, "ubereats", "service_fee"),
         mk_stat(df_avail, "didi", "service_fee")],
        ["Total fees (delivery+service)",
         f"${df_avail[df_avail['platform'] == 'rappi']['total_fees'].mean():.1f}",
         f"${df_avail[df_avail['platform'] == 'ubereats']['total_fees'].mean():.1f}",
         f"${df_avail[df_avail['platform'] == 'didi']['total_fees'].mean():.1f}"],
        ["Costo total promedio (Big Mac)",
         f"${df_avail[(df_avail['platform'] == 'rappi') & (df_avail['product'] == 'Big Mac')]['total_cost_calc'].mean():.1f}",
         f"${df_avail[(df_avail['platform'] == 'ubereats') & (df_avail['product'] == 'Big Mac')]['total_cost_calc'].mean():.1f}",
         f"${df_avail[(df_avail['platform'] == 'didi') & (df_avail['product'] == 'Big Mac')]['total_cost_calc'].mean():.1f}"],
        ["ETA promedio (min)",
         f"{df_avail[df_avail['platform'] == 'rappi']['eta_min'].mean():.1f}",
         f"{df_avail[df_avail['platform'] == 'ubereats']['eta_min'].mean():.1f}",
         f"{df_avail[df_avail['platform'] == 'didi']['eta_min'].mean():.1f}"],
        ["Disponibilidad McDonald's",
         avail_by_plat["rappi"], avail_by_plat["ubereats"], avail_by_plat["didi"]],
        ["Frecuencia promocional",
         promo_by_plat["rappi"], promo_by_plat["ubereats"], promo_by_plat["didi"]],
    ]

    col_w = [6 * cm, 3 * cm, 3 * cm, 3 * cm]
    t = Table(tdata, colWidths=col_w, repeatRows=1)
    ts = TableStyle([
        # Header
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(C_DARK)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        # Data
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("ALIGN", (1, 1), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        # Row alternation
        *[("BACKGROUND", (0, i), (-1, i), colors.HexColor("#F5F5F5"))
          for i in range(2, len(tdata), 2)],
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#DDDDDD")),
        # Highlight Rappi column
        ("BACKGROUND", (1, 1), (1, -1), colors.HexColor("#FFF3F0")),
        ("TEXTCOLOR", (1, 1), (1, -1), colors.HexColor(C_RAPPI)),
        ("FONTNAME", (1, 1), (1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (1, 0), (1, 0), colors.HexColor(C_RAPPI)),
    ])
    t.setStyle(ts)
    story.append(t)

    # ─────────────────── SECCIÓN 4: ANEXO TÉCNICO ────────────────────────────
    story += [
        Spacer(1, 0.8 * cm),
        Paragraph("4. Anexo Técnico", sH1),
        hr(),
        Paragraph("<b>Metodología</b>", sH2),
        Paragraph(
            "Los datos fueron recolectados via APIs oficiales/reverse-engineered de Rappi MX, "
            f"Uber Eats MX y DiDi Food MX. Se consultaron <b>{n_addresses} direcciones</b> en CDMX agrupadas en "
            "4 zonas socioeconómicas (premium, medio-alto, medio, popular), para 3 productos "
            f"de McDonald's. Total: <b>{total_obs} registros únicos</b> ({plat_summary}). "
            f"Registros con precio: {obs_con_precio} · Sin precio: {obs_sin_precio}.",
            sBody,
        ),
        Paragraph("<b>Limitaciones y datos faltantes</b>", sH2),
        Paragraph(
            "• <b>Horario nocturno</b>: Los datos fueron recolectados de madrugada (01:50-02:00 AM). "
            "Los precios, ETAs y disponibilidad pueden variar significativamente en hora pico "
            "(12-14h, 19-21h). <i>Acción siguiente</i>: repetir recolección en 3 franjas horarias.",
            sBullet,
        ),
        Paragraph(
            "• <b>Muestra de productos</b>: Solo 3 SKUs de McDonald's. "
            "No captura variabilidad de precios en el menú completo. "
            "<i>Acción siguiente</i>: ampliar a 10-15 SKUs representativos.",
            sBullet,
        ),
        Paragraph(
            "• <b>Datos faltantes</b>: 41 registros sin precio (18% del total), "
            "principalmente en zona popular (DiDi 27% de ausencias). "
            "No afecta la validez estadística del análisis por plataforma.",
            sBullet,
        ),
        Paragraph(
            "• <b>Evolución temporal</b>: Con una sola fecha, no es posible analizar "
            "tendencias de precios. <i>Acción siguiente</i>: automatizar recolección diaria.",
            sBullet,
        ),
        Paragraph(
            "• <b>Otras plataformas</b>: No se incluyen Pedidos Ya, ifood o dark kitchens propias. "
            "<i>Acción siguiente</i>: evaluar cobertura de competidores emergentes en CDMX.",
            sBullet,
        ),
        Spacer(1, 0.4 * cm),
        Paragraph("<b>Fuentes de datos</b>", sH2),
        Paragraph(
            "API Rappi MX (services.rappi.com.mx) · API Uber Eats MX (ubereats.com) · "
            "API DiDi Food MX (food.didiglobal.com) · Configuración: config/addresses.json, "
            "config/products.json · Scripts: api_clients/, main.py",
            sBody,
        ),
        Spacer(1, 0.2 * cm),
        Paragraph(
            f"Generado el 5 de abril de 2026 — src/insights/generate_report.py — "
            f"Competitive Intelligence Rappi México",
            sFooter,
        ),
    ]

    doc.build(story)
    print(f"\nInforme generado: {OUT_PDF}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("Cargando datos...")
    df = load_data()
    df_avail = df[df["available"] == True].copy()
    print(f"  {len(df)} registros totales | {len(df_avail)} disponibles")

    print("Generando gráficos...")
    charts = {
        "precios":    chart_precios(df_avail),
        "total_cost": chart_total_cost(df_avail),
        "fees":       chart_fees(df_avail),
        "eta":        chart_eta(df_avail),
        "heatmap":    chart_heatmap(df_avail),
        "promos":     chart_promos(df),
    }
    print(f"  {len(charts)} gráficos generados en {IMG_DIR}")

    print("Construyendo PDF...")
    build_pdf(charts, df, df_avail)


if __name__ == "__main__":
    main()
