"""
main.py
───────
Orquestador principal del sistema de inteligencia competitiva.

Uso:
  python main.py                        # todas las plataformas, todas las dirs
  python main.py --platform rappi       # solo Rappi
  python main.py --limit 5              # primeras 5 direcciones
  python main.py --platform rappi --limit 3 --log-level DEBUG
"""

import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from loguru import logger

from api_clients import RappiClient, UberEatsClient, DiDiClient
from api_clients.base_client import CircuitOpenError, BaseAPIClient
from utils import setup_logger

# ─── Constantes ──────────────────────────────────────────────────────────────

ROOT        = Path(__file__).parent
CONFIG_DIR  = ROOT / "config"
DATA_RAW    = ROOT / "data" / "raw"
DATA_PROC   = ROOT / "data" / "processed"

DATA_RAW.mkdir(parents=True, exist_ok=True)
DATA_PROC.mkdir(parents=True, exist_ok=True)

PLATFORM_CLIENTS: dict[str, type[BaseAPIClient]] = {
    "rappi":    RappiClient,
    "ubereats": UberEatsClient,
    "didi":     DiDiClient,
}

# ─── Loaders ─────────────────────────────────────────────────────────────────

def load_addresses(limit: int | None = None) -> list[dict]:
    with open(CONFIG_DIR / "addresses.json", encoding="utf-8") as f:
        addrs = json.load(f)
    return addrs[:limit] if limit else addrs


def load_products() -> list[dict]:
    with open(CONFIG_DIR / "products.json", encoding="utf-8") as f:
        return json.load(f)


# ─── Recolección por dirección / plataforma ───────────────────────────────────

async def collect_for_address(
    address: dict,
    platform_name: str,
    client: BaseAPIClient,
    products: list[dict],
) -> list[dict]:
    """
    Para una dirección y una plataforma, obtiene precio y delivery de cada producto.
    Devuelve lista de filas listos para el DataFrame.
    """
    lat, lng = address["lat"], address["lng"]
    rows: list[dict] = []

    try:
        # delivery_estimate se llama una vez por dirección/plataforma
        delivery = await client.get_delivery_estimate(lat, lng)  # type: ignore[attr-defined]
    except CircuitOpenError:
        logger.warning(f"[{platform_name}] Circuit abierto — omitiendo {address['id']}")
        return []
    except Exception as exc:
        logger.error(f"[{platform_name}] Error en delivery_estimate({address['id']}): {exc}")
        delivery = {"delivery_fee": None, "service_fee": None, "eta_min": None, "promotions": []}

    for prod in products:
        product_name = prod["name"]
        try:
            price_data = await client.get_product_price(lat, lng, product_name)  # type: ignore[attr-defined]
        except CircuitOpenError:
            logger.warning(f"[{platform_name}] Circuit abierto — omitiendo {product_name}")
            break
        except Exception as exc:
            logger.error(f"[{platform_name}] Error en get_product_price({product_name}): {exc}")
            price_data = {"product": product_name, "price": None, "available": False}

        promos_str = " | ".join(delivery.get("promotions", [])) or None

        rows.append({
            "timestamp":        datetime.now().isoformat(),
            "platform":         platform_name,
            "address_id":       address["id"],
            "address":          address["address"],
            "zone":             address["zone"],
            "lat":              lat,
            "lng":              lng,
            "product":          product_name,
            "price":            price_data.get("price"),
            "available":        price_data.get("available", False),
            "delivery_fee":     delivery.get("delivery_fee"),
            "service_fee":      delivery.get("service_fee"),
            "eta_min":          delivery.get("eta_min"),
            "promotions":       promos_str,
        })

        status = "✓" if price_data.get("available") else "✗"
        logger.info(
            f"{status} {platform_name:10} | {address['id']:25} | "
            f"{product_name:20} | "
            f"${price_data.get('price') or '—'}"
        )

    return rows


# ─── Orquestador principal ────────────────────────────────────────────────────

async def run(platforms: list[str], addresses: list[dict], products: list[dict]) -> list[dict]:
    """Ejecuta la recolección en paralelo por plataforma, secuencial por dirección."""

    all_rows: list[dict] = []

    for platform_name in platforms:
        client_cls = PLATFORM_CLIENTS[platform_name]
        logger.info(f"\n{'─'*55}")
        logger.info(f"  Plataforma: {platform_name.upper()}")
        logger.info(f"  Direcciones: {len(addresses)} | Productos: {len(products)}")
        logger.info(f"{'─'*55}")

        async with client_cls() as client:  # type: ignore[abstract]
            for address in addresses:
                rows = await collect_for_address(address, platform_name, client, products)
                all_rows.extend(rows)

    return all_rows


# ─── Guardado de datos ────────────────────────────────────────────────────────

def save_results(rows: list[dict], platforms: list[str]) -> tuple[Path, Path]:
    """
    Guarda raw (todos los registros) y processed (solo disponibles, con totales).
    Retorna (raw_path, processed_path).
    """
    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    tag = "_".join(platforms) if len(platforms) <= 2 else "all"

    # Raw
    raw_path = DATA_RAW / f"raw_{tag}_{ts}.csv"
    df_raw   = pd.DataFrame(rows)
    df_raw.to_csv(raw_path, index=False, encoding="utf-8")
    logger.info(f"Raw guardado: {raw_path} ({len(df_raw)} filas)")

    # Processed: calcular precio total
    df = df_raw.copy()
    for col in ("price", "delivery_fee", "service_fee"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["eta_min"] = pd.to_numeric(df["eta_min"], errors="coerce")

    df["total_cost"] = (
        df["price"].fillna(0)
        + df["delivery_fee"].fillna(0)
        + df["service_fee"].fillna(0)
    ).where(df["available"])

    proc_path = DATA_PROC / f"intel_{tag}_{ts}.csv"
    df.to_csv(proc_path, index=False, encoding="utf-8")
    logger.info(f"Processed guardado: {proc_path}")

    # Resumen en consola
    logger.info("\n" + "═" * 55)
    logger.info("  RESUMEN")
    logger.info("═" * 55)
    avail = df.loc[df["available"] == True]
    if not avail.empty:
        summary = (
            avail.groupby(["platform", "product"])["price"]
            .mean()
            .round(2)
            .unstack(fill_value=float("nan"))
        )
        logger.info(f"\nPrecios promedio (MXN):\n{summary.to_string()}")

        delivery_summary = (
            avail.drop_duplicates(["platform", "address_id"])
            .groupby("platform")[["delivery_fee", "service_fee", "eta_min"]]
            .mean()
            .round(2)
        )
        logger.info(f"\nDelivery / ETA promedio:\n{delivery_summary.to_string()}")

    total_dp = len(df)
    ok_dp    = len(avail)
    logger.info(f"\nTotal registros: {total_dp} | Con precio: {ok_dp} | Sin precio: {total_dp - ok_dp}")
    logger.info("═" * 55)

    return raw_path, proc_path


# ─── CLI ─────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Competitive Intelligence — Rappi / Uber Eats / DiDi Food (API only)"
    )
    parser.add_argument(
        "--platform",
        choices=["rappi", "ubereats", "didi", "all"],
        default="all",
        help="Plataforma a consultar (default: all)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Límite de direcciones (default: todas)",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING"],
        default="INFO",
        dest="log_level",
        help="Nivel de logging (default: INFO)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    setup_logger(level=args.log_level)

    platforms = (
        list(PLATFORM_CLIENTS.keys()) if args.platform == "all" else [args.platform]
    )
    addresses = load_addresses(limit=args.limit)
    products  = load_products()

    logger.info("=" * 55)
    logger.info("  Competitive Intelligence — México (API Only)")
    logger.info(f"  Plataformas : {', '.join(platforms)}")
    logger.info(f"  Direcciones : {len(addresses)}")
    logger.info(f"  Productos   : {', '.join(p['name'] for p in products)}")
    logger.info("=" * 55)

    rows = asyncio.run(run(platforms, addresses, products))

    if not rows:
        logger.error("Sin datos recolectados. Verifica conectividad y credenciales.")
        return

    save_results(rows, platforms)


if __name__ == "__main__":
    main()
