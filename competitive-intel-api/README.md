# Competitive Intelligence — API Only

Sistema de inteligencia competitiva para **Rappi**, **Uber Eats** y **DiDi Food** en México.  
Recolecta precios, delivery fees, ETAs y promociones de McDonald's usando exclusivamente **HTTP/APIs** — sin Selenium, sin Playwright, sin HTML parsing.

---

## Setup

```bash
cd competitive-intel-api
python -m venv .venv
.venv\Scripts\activate      # Windows
# source .venv/bin/activate # macOS/Linux

pip install -r requirements.txt
```

---

## Uso

```bash
# Todas las plataformas, 25 direcciones CDMX
python main.py

# Solo Rappi (más rápido para probar)
python main.py --platform rappi

# Solo Rappi, primeras 3 direcciones, logs verbose
python main.py --platform rappi --limit 3 --log-level DEBUG

# Solo Uber Eats
python main.py --platform ubereats --limit 5
```

**Output:**
- `data/raw/raw_<platform>_<timestamp>.csv` — todos los registros
- `data/processed/intel_<platform>_<timestamp>.csv` — con `total_cost` calculado

---

## API Documentation

### Rappi

| Campo | Valor |
|-------|-------|
| Base URL | `https://services.rappi.com.mx` |
| Auth | No requerida |
| Rate limit | ~60-80 req/min |

**Endpoints:**

```
GET /api/restaurants/prime/
  Params: lat, lng, limit, offset
  → Lista de restaurantes con deliveryTime, deliveryFee, promotions

GET /api/restaurants/{store_id}/
  → Menú completo (corridors > products con name, price)
```

**Headers obligatorios:**
```
User-Agent:       Rappi/9.1.0 (Android; SDK 31; arm64-v8a; samsung SM-S908B; es-MX)
x-rappi-version:  9.1.0
x-rappi-platform: android
x-rappi-country:  mex
```

---

### Uber Eats

| Campo | Valor |
|-------|-------|
| Base URL | `https://www.ubereats.com` |
| Auth | CSRF token (de cookie/HTML en homepage) |
| Rate limit | ~50-60 req/min |

**Flujo de autenticación:**
1. `GET https://www.ubereats.com/mx` → leer cookie `csrf_token` o variable JS `csrfToken`
2. Usar el token en el header `x-csrf-token` de todos los POSTs

**Endpoints:**
```
POST /api/getFeedV1
  Body: {targetLocation: {latitude, longitude, reference, type},
         pageInfo: {offset, pageSize}, query: "McDonald's"}
  → feedItems[].store con uuid, etaRange, fareInfo, promotions

POST /api/getStoreV1
  Body: {storeUuid: "..."}
  → sections[].items con title y price.amount (centavos)
     fareInfo.deliveryFee.price.amount (centavos)
     fareInfo.serviceFee.price.amount (centavos)
```

**Nota:** Los precios vienen en centavos. `amount / 100 = MXN`.

---

### DiDi Food

| Campo | Valor |
|-------|-------|
| Base URL | `https://food.didiglobal.com` |
| Auth | No requerida |
| Rate limit | ~40-50 req/min |

**Endpoints:**
```
GET /api/v1/restaurant/nearby
  Params: lat, lng, keyword, limit
  → data.shops[] con shopId, name, deliveryTime, deliveryFee

GET /api/v1/restaurant/{shop_id}/menu
  → data.productList[] con name, price (puede ser centavos si >500)
```

**Headers obligatorios:**
```
User-Agent:    DiDiFood/5.0.32 (Android; SDK 31; arm64-v8a; es-MX)
x-didi-client: food_android
x-didi-country: MX
```

**Limitaciones:**
- Cobertura menor fuera del centro de CDMX
- No expone `service_fee` públicamente
- Promociones a veces solo tienen porcentaje, sin descripción

---

## Estructura del proyecto

```
competitive-intel-api/
├── api_clients/
│   ├── base_client.py       # aiohttp + retry + circuit breaker + rate limit
│   ├── rappi_client.py      # endpoints Rappi MX
│   ├── ubereats_client.py   # endpoints Uber Eats MX (con CSRF)
│   └── didi_client.py       # endpoints DiDi Food MX
├── config/
│   ├── addresses.json       # 25 direcciones CDMX con lat/lng
│   └── products.json        # productos con keywords de matching
├── data/
│   ├── raw/                 # CSVs sin procesar
│   └── processed/           # CSVs con total_cost calculado
├── utils/
│   ├── logger.py            # loguru (consola + archivo rotativo)
│   └── geocoding.py         # geopy con lru_cache
├── main.py
├── requirements.txt
└── README.md
```

---

## Resiliencia

| Mecanismo | Configuración |
|-----------|--------------|
| Retry | 3 intentos con backoff exponencial (1.5s × 2^n) |
| Rate limit | Delay mínimo por dominio (Rappi: 1.2s, UberEats: 1.5s, DiDi: 1.5s) |
| Circuit breaker | Se abre tras 4 fallos consecutivos por plataforma |
| Timeout | 20s total, 8s connect |
| CSRF refresh | Uber Eats renueva automáticamente si recibe 403 |

---

## Output esperado

```
14:32:01 | INFO    | ✓ rappi      | polanco_masaryk           | Big Mac              | $109.0
14:32:03 | INFO    | ✓ rappi      | polanco_masaryk           | Coca-Cola 500ml      | $39.0
14:32:05 | INFO    | ✗ rappi      | tepito                    | Combo Mediano        | —
...
Raw guardado: data/raw/raw_rappi_20240115_143201.csv (75 filas)
```

---

## Limitaciones conocidas

- **Uber Eats** requiere CSRF token válido; expira en la sesión (se renueva automáticamente)
- **DiDi Food** no cubre todas las zonas populares de CDMX
- Los endpoints son reverse-engineered y pueden cambiar con actualizaciones de la app
- Todas las plataformas requieren que McDonald's tenga cobertura activa en la dirección
