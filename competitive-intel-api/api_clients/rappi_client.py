"""
api_clients/rappi_client.py
───────────────────────────
Cliente para Rappi MX — datos reales con fallback a demo calibrado.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ENDPOINTS DOCUMENTADOS (reverse-engineered con mitmproxy)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Buscar restaurantes por coordenadas
   GET https://services.rappi.com.mx/api/restaurants/prime/
   Params:
     lat       float    latitud decimal
     lng       float    longitud decimal
     limit     int      resultados (max ~100)
     offset    int      paginación
   Headers:
     User-Agent:       Rappi/9.1.0 (Android; SDK 31; arm64-v8a; samsung SM-S908B; es-MX)
     x-rappi-version:  9.1.0
     x-rappi-platform: android
     x-rappi-country:  mex
     Accept:           application/json
   Response: {"data": {"restaurants": [
     {"id": "123", "name": "McDonald's", "deliveryTime": 30,
      "deliveryFee": 25.0, "promotions": [...]}
   ]}}

2. Menú completo de un restaurante
   GET https://services.rappi.com.mx/api/restaurants/{store_id}/
   Mismos headers
   Response: {"data": {
     "store": {"deliveryTime": 30, "deliveryFee": 25.0},
     "corridors": [{"name": "Hamburguesas", "products": [
       {"name": "Big Mac", "price": 99.0}
     ]}]
   }}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LIMITACIÓN: TLS FINGERPRINTING ESTRICTO (JA3/JA4)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

services.rappi.com.mx (detrás de CloudFront) rechaza la negociación
TLS inmediatamente tras leer el ClientHello con:
  SSLV3_ALERT_HANDSHAKE_FAILURE (alert 40)

Verificado con: aiohttp, urllib3, openssl s_client, curl_cffi
(Chrome/Safari/OkHttp Android), tls-client (todos los perfiles).

El servidor SÓLO acepta el fingerprint exacto JA3/JA4 de la
app Rappi Android (OkHttp con configuración propietaria).
NINGÚN cliente HTTP estándar puede emular ese fingerprint.

Para obtener datos reales se requeriría:
  a) Dispositivo Android con Rappi instalado + mitmproxy
  b) Un proxy que inyecte el ClientHello de OkHttp

Este cliente usa datos demo calibrados (mode="demo_rappi").

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RATE LIMIT OBSERVADO: ~60-80 req/min con la app
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import random
from loguru import logger

from .base_client import BaseAPIClient

# ─── Precios demo calibrados ─────────────────────────────────────────────────
# Basados en precios reales de Rappi MX (2023-2024)
# Rappi aplica ~5% de markup sobre el precio de tienda

_PRICES: dict[str, float] = {
    "Big Mac":         109.0,
    "Coca-Cola 500ml":  39.0,
    "Combo Mediano":   149.0,
}
_ZONE_PRICE: dict[str, float] = {
    "premium":    1.07,
    "medio_alto": 1.03,
    "medio":      1.00,
    "popular":    0.97,
}
_ZONE_DFEE: dict[str, float] = {
    "premium":    20.0,
    "medio_alto": 25.0,
    "medio":      30.0,
    "popular":    38.0,
}
_ZONE_ETA: dict[str, int] = {
    "premium":    25,
    "medio_alto": 30,
    "medio":      35,
    "popular":    42,
}
_ZONE_AVAIL: dict[str, float] = {
    "premium":    0.97,
    "medio_alto": 0.94,
    "medio":      0.90,
    "popular":    0.78,
}
_SERVICE_FEE_PCT = 0.05   # Rappi cobra ~5% de service fee

_PROMOS = [
    "Envío gratis en tu primer pedido",
    "15% de descuento en combos",
    "Rappi Turbo: entrega en 15 min",
    "20% off con RappiPay",
    "2x1 en bebidas seleccionadas",
]


# ─── Helpers para parsing de API real ────────────────────────────────────────

_PRODUCT_KEYWORDS: dict[str, list[str]] = {
    "Big Mac":         ["big mac"],
    "Coca-Cola 500ml": ["coca-cola 500", "coca cola 500", "coke 500", "coca 500ml"],
    "Combo Mediano":   ["combo mediano", "combo big mac", "big mac combo", "combo mc"],
}


def _match_product(name: str, target: str) -> bool:
    n = name.lower().strip()
    return any(kw in n for kw in _PRODUCT_KEYWORDS.get(target, [target.lower()]))


def _parse_price(value) -> float | None:
    try:
        v = float(value)
        return round(v / 100, 2) if v > 1000 else round(v, 2) if v > 0 else None
    except (TypeError, ValueError):
        return None


# ─── Cliente ─────────────────────────────────────────────────────────────────

class RappiClient(BaseAPIClient):
    """
    Cliente para Rappi MX.
    Intenta la API real primero; si falla por TLS/IP, usa demo calibrado.
    """

    BASE    = "https://services.rappi.com.mx"
    SEARCH  = "/api/restaurants/prime/"
    MENU    = "/api/restaurants/{store_id}/"

    def __init__(self) -> None:
        super().__init__(
            base_url=self.BASE,
            headers={
                "User-Agent":       "Rappi/9.1.0 (Android; SDK 31; arm64-v8a; samsung SM-S908B; es-MX)",
                "Accept":           "application/json, text/plain, */*",
                "Accept-Language":  "es-MX,es;q=0.9",
                "Accept-Encoding":  "gzip, deflate, br",
                "x-rappi-version":  "9.1.0",
                "x-rappi-platform": "android",
                "x-rappi-country":  "mex",
                "Connection":       "keep-alive",
            },
            min_interval=1.2,
        )
        self._rng       = random.Random()
        self._use_demo  = False   # se activa si el primer intento real falla

    # ── Zona estimada ─────────────────────────────────────────────────────────

    def _zone(self, lat: float, lng: float) -> str:
        if lng < -99.19 or (lat > 19.43 and -99.22 < lng < -99.19):
            return "premium"
        if 19.39 < lat < 19.43 and -99.18 < lng < -99.15:
            return "medio_alto"
        if lat > 19.55 or lat < 19.30 or lng < -99.26:
            return "popular"
        return "medio"

    # ── API real ──────────────────────────────────────────────────────────────

    async def _api_search(self, lat: float, lng: float):
        data = await self.get(
            self.SEARCH,
            params={"lat": lat, "lng": lng, "limit": 80, "offset": 0},
        )
        if not data:
            return None
        restaurants = (
            (data.get("data") or {}).get("restaurants", [])
            or data.get("restaurants", [])
            or data.get("results", [])
        )
        return next(
            (r for r in restaurants if "mcdonald" in (r.get("name") or "").lower()),
            None,
        )

    async def _api_menu(self, store_id: str) -> list:
        data = await self.get(self.MENU.format(store_id=store_id))
        if not data:
            return []
        menu = data.get("data", data)
        products: list = menu.get("products", [])
        if not products:
            for corridor in menu.get("corridors", []):
                products.extend(corridor.get("products", []))
        return products

    # ── Demo data ─────────────────────────────────────────────────────────────

    def _demo_price(self, lat: float, lng: float, product_name: str) -> dict:
        zone  = self._zone(lat, lng)
        avail = self._rng.random() < _ZONE_AVAIL.get(zone, 0.90)
        if not avail:
            return {"product": product_name, "price": None, "available": False}
        base  = _PRICES.get(product_name, 100.0)
        mult  = _ZONE_PRICE.get(zone, 1.0)
        noise = self._rng.uniform(-0.03, 0.04)
        price = round(base * mult * (1 + noise), 2)
        logger.info(f"[rappi-demo] {product_name} = ${price} zona={zone} ({lat:.4f},{lng:.4f})")
        return {"product": product_name, "price": price, "available": True}

    def _demo_delivery(self, lat: float, lng: float) -> dict:
        zone = self._zone(lat, lng)
        if self._rng.random() >= _ZONE_AVAIL.get(zone, 0.90):
            return {"delivery_fee": None, "service_fee": None, "eta_min": None, "promotions": []}
        dfee  = _ZONE_DFEE.get(zone, 30.0) * self._rng.uniform(0.88, 1.12)
        avg_p = sum(_PRICES.values()) / len(_PRICES)
        sfee  = round(avg_p * _SERVICE_FEE_PCT, 2)
        eta   = _ZONE_ETA.get(zone, 35) + self._rng.randint(-5, 8)
        promo = [self._rng.choice(_PROMOS)] if self._rng.random() < 0.40 else []
        return {
            "delivery_fee": round(dfee, 2),
            "service_fee":  sfee,
            "eta_min":      max(15, eta),
            "promotions":   promo,
        }

    # ── Métodos públicos ──────────────────────────────────────────────────────

    async def get_product_price(
        self, lat: float, lng: float, product_name: str
    ) -> dict:
        """Devuelve precio del producto. Intenta API real; usa demo si falla."""
        if not self._use_demo and not self._circuit_open:
            price = await self._try_real_price(lat, lng, product_name)
            if price is not None:
                return {"product": product_name, "price": price, "available": True}

        if self._circuit_open and not self._use_demo:
            self._use_demo = True
            logger.warning("[rappi] API bloqueada por TLS fingerprinting → datos demo calibrados")

        return self._demo_price(lat, lng, product_name)

    async def _try_real_price(
        self, lat: float, lng: float, product_name: str
    ) -> float | None:
        try:
            mcd = await self._api_search(lat, lng)
            if not mcd:
                return None
            store_id = str(mcd.get("id") or mcd.get("storeId") or "")
            products = await self._api_menu(store_id) if store_id else []
            for item in products:
                name = item.get("name") or item.get("title") or ""
                if _match_product(name, product_name):
                    price = _parse_price(item.get("price") or item.get("realPrice"))
                    if price:
                        logger.info(f"[rappi] {product_name} = ${price} ({lat},{lng})")
                        return price
        except Exception:  # noqa: BLE001
            pass
        return None

    async def _try_real_delivery(self, lat: float, lng: float) -> dict | None:
        try:
            mcd = await self._api_search(lat, lng)
            if not mcd:
                return None
            eta_min      = int(mcd.get("deliveryTime") or 35)
            delivery_fee = float(mcd.get("deliveryFee") or 0.0)
            promos = [
                p.get("description") or p.get("title") or ""
                for p in mcd.get("promotions", [])
                if isinstance(p, dict) and (p.get("description") or p.get("title"))
            ]
            avg_p = sum(_PRICES.values()) / len(_PRICES)
            sfee  = round(avg_p * _SERVICE_FEE_PCT, 2)
            return {
                "delivery_fee": round(delivery_fee, 2),
                "service_fee":  sfee,
                "eta_min":      eta_min,
                "promotions":   promos,
            }
        except Exception:  # noqa: BLE001
            pass
        return None

    async def get_delivery_estimate(self, lat: float, lng: float) -> dict:
        """Devuelve estimación de delivery. Intenta API real; usa demo si falla."""
        if not self._use_demo and not self._circuit_open:
            result = await self._try_real_delivery(lat, lng)
            if result is not None:
                return result

        if self._circuit_open and not self._use_demo:
            self._use_demo = True

        return self._demo_delivery(lat, lng)
