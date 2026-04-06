# Competitive Intelligence — API Only

Scraper de precios y condiciones de entrega para **Rappi**, **Uber Eats** y **DiDi Food** en México.  
Recolecta precios, delivery fees, ETAs y promociones de McDonald's usando exclusivamente **HTTP/APIs** — sin Selenium, sin Playwright, sin HTML parsing.

## ¿Qué hace?

Dado un conjunto de direcciones en CDMX, consulta las tres plataformas en paralelo y genera CSVs listos para análisis. Compara precios del mismo producto en distintas zonas y plataformas sin intervención manual.

**Ejemplo:**
- `python main.py --platform rappi --limit 3` — primeras 3 direcciones en Rappi
- `python main.py --platform ubereats --limit 5` — 5 direcciones en Uber Eats
- `python main.py` — todas las plataformas, 25 direcciones CDMX

El sistema maneja reintentos, rate limiting y circuit breakers automáticamente.

## Stack

- **HTTP:** aiohttp (requests asíncronos con retry y circuit breaker)
- **Logging:** loguru (consola + archivo rotativo)
- **Geocoding:** geopy con lru_cache
- **Data:** Pandas para procesamiento y exportación CSV

## Instalación

1. Clonar el repo
```bash
git clone [tu-repo-url]
cd competitive-intel-api
```

2. Crear entorno virtual e instalar dependencias
```bash
python -m venv .venv
.venv\Scripts\activate      # Windows
# source .venv/bin/activate # macOS/Linux

pip install -r requirements.txt
```

3. Correr la app
```bash
python main.py
```

Los CSVs se generan automáticamente en `data/raw/` y `data/processed/`.

## Estructura del Proyecto

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

## Cómo Funciona

1. `main.py` carga las 25 direcciones de `config/addresses.json`
2. Para cada dirección, llama al cliente de la plataforma seleccionada
3. El cliente hace GET/POST al endpoint de búsqueda y obtiene la lista de restaurantes
4. Por cada McDonald's encontrado, consulta el menú y extrae productos + precios
5. Los resultados se guardan en `data/raw/` (registros crudos) y `data/processed/` (con `total_cost` calculado)

## Plataformas Disponibles

- `rappi` — consulta `/api/restaurants/prime/` y menús individuales; no requiere auth
- `ubereats` — obtiene CSRF token automáticamente y consulta `getFeedV1` + `getStoreV1`
- `didi` — consulta `/api/v1/restaurant/nearby` y menús; cobertura menor fuera del centro

## Resiliencia

El sistema implementa cuatro mecanismos para manejar inestabilidad de las APIs:

- **Retry:** 3 intentos con backoff exponencial (1.5s × 2ⁿ) ante errores 5xx o timeout
- **Rate limit:** delay mínimo por dominio (Rappi: 1.2s, UberEats: 1.5s, DiDi: 1.5s)
- **Circuit breaker:** se abre tras 4 fallos consecutivos por plataforma para evitar bloqueos
- **CSRF refresh:** Uber Eats renueva el token automáticamente si recibe un 403

## Limitaciones

- Los endpoints son reverse-engineered y pueden cambiar con actualizaciones de la app
- DiDi Food no cubre todas las zonas de CDMX; cobertura reducida fuera del centro
- Uber Eats requiere CSRF token válido por sesión (se renueva automáticamente, pero depende del HTML de la homepage)
- Todas las plataformas requieren que McDonald's tenga cobertura activa en la dirección consultada

## Output Esperado

```
14:32:01 | INFO | ✓ rappi     | polanco_masaryk  | Big Mac         | $109.0
14:32:03 | INFO | ✓ rappi     | polanco_masaryk  | Coca-Cola 500ml | $39.0
14:32:05 | INFO | ✗ rappi     | tepito           | Combo Mediano   | —
...
Raw guardado:       data/raw/raw_rappi_20240115_143201.csv       (75 filas)
Processed guardado: data/processed/intel_rappi_20240115_143201.csv (75 filas)
```

## Next Steps

Si tuviera más tiempo:
- Deployment en Railway/Render con scheduler para correr diario
- Conexión a DB real (Postgres) en vez de CSVs
- Dashboard de comparación de precios entre plataformas
- Alertas automáticas cuando una plataforma baja precios >5%
- Soporte para más ciudades y más cadenas de comida rápida

## Autor

Fernando Rivera
