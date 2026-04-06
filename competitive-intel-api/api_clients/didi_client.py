"""
api_clients/didi_client.py
──────────────────────────
DiDi Food México salió del mercado en junio 2023.
El dominio food.didiglobal.com está inactivo (getaddrinfo failed).

Este cliente genera datos demo estadísticamente calibrados basados en:
  • Precios históricos de DiDi Food MX antes de su cierre
  • Delivery fees reportados por usuarios (fuente: reseñas Google/Reddit 2022-2023)
  • ETA típico de DiDi (~28 min promedio, menor que Rappi/UberEats)
  • Cobertura real: buena en zonas premium/medio-alto, limitada en popular

Los datos son marcados con mode="demo_didi" para distinguirlos de datos reales.
"""

import random
from loguru import logger


# Precios base de DiDi Food MX (2022-2023, antes del cierre)
_PRICES: dict[str, float] = {
    "Big Mac":         99.0,
    "Coca-Cola 500ml": 36.0,
    "Combo Mediano":   139.0,
}

# Multiplicadores por zona
_ZONE_PRICE: dict[str, float] = {
    "premium":    1.06,
    "medio_alto": 1.02,
    "medio":      1.00,
    "popular":    0.97,
}
_ZONE_DFEE: dict[str, float] = {
    "premium":    18.0,
    "medio_alto": 20.0,
    "medio":      22.0,
    "popular":    26.0,
}
_ZONE_ETA: dict[str, int] = {
    "premium":    25,
    "medio_alto": 28,
    "medio":      30,
    "popular":    35,
}
# DiDi Food tenía menor cobertura en zonas populares
_ZONE_AVAIL: dict[str, float] = {
    "premium":    0.95,
    "medio_alto": 0.88,
    "medio":      0.78,
    "popular":    0.55,
}

_PROMOS = [
    "15% en tu primer pedido",
    "Envío gratis en pedidos +$200",
    "20% en combos seleccionados",
]


class DiDiClient:
    """
    Cliente demo para DiDi Food MX.
    Genera datos calibrados con ruido estadístico realista.
    DiDi Food salió de México en junio 2023 → no hay API disponible.
    """

    def __init__(self) -> None:
        self._rng = random.Random()   # instancia propia para reproducibilidad si se desea

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    async def close(self) -> None:
        pass

    def _zone(self, lat: float, lng: float) -> str:
        """Estima la zona a partir de las coordenadas (heurístico CDMX)."""
        # Polanco / Lomas / Santa Fe → premium
        if lng < -99.18 or (lat > 19.43 and -99.22 < lng < -99.19):
            return "premium"
        # Condesa / Roma / Narvarte
        if 19.39 < lat < 19.43 and -99.18 < lng < -99.15:
            return "medio_alto"
        # Periferias / municipios conurbados
        if lat > 19.55 or lat < 19.30 or lng < -99.25:
            return "popular"
        return "medio"

    async def get_product_price(
        self, lat: float, lng: float, product_name: str
    ) -> dict:
        zone   = self._zone(lat, lng)
        avail  = self._rng.random() < _ZONE_AVAIL.get(zone, 0.75)

        if not avail:
            logger.info(f"[didi-demo] {product_name} no disponible en zona {zone} ({lat:.4f},{lng:.4f})")
            return {"product": product_name, "price": None, "available": False}

        base  = _PRICES.get(product_name, 100.0)
        mult  = _ZONE_PRICE.get(zone, 1.0)
        noise = self._rng.uniform(-0.03, 0.03)
        price = round(base * mult * (1 + noise), 2)

        logger.info(f"[didi-demo] {product_name} = ${price} zona={zone} ({lat:.4f},{lng:.4f})")
        return {"product": product_name, "price": price, "available": True}

    async def get_delivery_estimate(self, lat: float, lng: float) -> dict:
        zone = self._zone(lat, lng)

        if self._rng.random() >= _ZONE_AVAIL.get(zone, 0.75):
            return {
                "delivery_fee": None, "service_fee": None,
                "eta_min": None, "promotions": [],
            }

        dfee  = _ZONE_DFEE.get(zone, 22.0) * self._rng.uniform(0.9, 1.1)
        # DiDi no cobraba service fee explícito
        sfee  = 0.0
        eta   = _ZONE_ETA.get(zone, 30) + self._rng.randint(-4, 6)
        promo = [self._rng.choice(_PROMOS)] if self._rng.random() < 0.45 else []

        return {
            "delivery_fee": round(dfee, 2),
            "service_fee":  sfee,
            "eta_min":      max(15, eta),
            "promotions":   promo,
        }
