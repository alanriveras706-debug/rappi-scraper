"""
utils/geocoding.py
──────────────────
Geocodificación de direcciones usando Nominatim (OpenStreetMap).

Uso principal: convertir addresses.json (que ya tiene lat/lng) es suficiente
para la mayoría de los casos. Esta utilidad sirve para agregar nuevas
direcciones dinámicamente sin tener que buscar coordenadas a mano.
"""

from functools import lru_cache

from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
from loguru import logger


_geocoder = Nominatim(user_agent="competitive_intel_rappi/1.0")


@lru_cache(maxsize=200)
def get_coordinates(address: str, city: str = "CDMX", country: str = "Mexico") -> tuple[float, float] | None:
    """
    Geocodifica una dirección y devuelve (lat, lng).
    Usa LRU cache para no repetir la misma dirección.

    Args:
        address: Dirección en texto libre, e.g. "Av. Masaryk 111, Polanco"
        city:    Ciudad (se agrega al query para mejorar precisión)
        country: País

    Returns:
        (lat, lng) o None si no se encontró.
    """
    query = f"{address}, {city}, {country}"
    try:
        location = _geocoder.geocode(query, timeout=10)
        if location:
            logger.debug(f"[geocoding] '{query}' → ({location.latitude}, {location.longitude})")
            return (location.latitude, location.longitude)
        logger.warning(f"[geocoding] No encontrado: '{query}'")
        return None
    except GeocoderTimedOut:
        logger.warning(f"[geocoding] Timeout para '{query}'")
        return None
    except GeocoderServiceError as exc:
        logger.error(f"[geocoding] Error de servicio: {exc}")
        return None


def enrich_address(addr: dict) -> dict:
    """
    Si el dict de dirección no tiene lat/lng, los obtiene via geocodificación.
    Modifica el dict in-place y lo devuelve.
    """
    if addr.get("lat") and addr.get("lng"):
        return addr  # ya tiene coordenadas

    coords = get_coordinates(addr.get("address", ""), addr.get("city", "CDMX"))
    if coords:
        addr["lat"], addr["lng"] = coords
    else:
        logger.warning(f"[geocoding] Sin coordenadas para: {addr.get('address')}")
    return addr
