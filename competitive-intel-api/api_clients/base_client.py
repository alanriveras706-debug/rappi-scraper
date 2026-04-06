"""
api_clients/base_client.py
─────────────────────────
Cliente HTTP asíncrono base para todos los scrapers de plataformas.

Características:
  • Rate limiting por dominio (asyncio-safe, no bloquea el event loop)
  • Retry con exponential backoff para 429, 5xx y timeouts
  • Circuit breaker: tras N fallos consecutivos deja de intentar
  • Session reutilizable (connection pooling automático de aiohttp)
  • Logging estructurado con loguru
"""

import asyncio
import time
from typing import Any

import aiohttp
from loguru import logger


class CircuitOpenError(Exception):
    """Se lanza cuando el circuit breaker está abierto para una plataforma."""


class BaseAPIClient:
    # ── Tunables ──────────────────────────────────────────────────────────────
    CIRCUIT_BREAKER_THRESHOLD = 4   # fallos consecutivos antes de abrir el circuito
    DEFAULT_RETRIES           = 3
    BACKOFF_BASE              = 1.5  # segundos base para backoff (×2^intento)

    # Códigos que disparan retry
    RETRY_STATUSES  = {429, 500, 502, 503, 504}
    # Códigos que no tiene sentido reintentar (auth, not-found, etc.)
    FATAL_STATUSES  = {401, 403, 404, 422}

    def __init__(
        self,
        base_url: str,
        headers: dict[str, str],
        min_interval: float = 1.0,
    ) -> None:
        self.base_url     = base_url.rstrip("/")
        self._headers     = headers
        self.min_interval = min_interval          # segundos mínimos entre requests

        self._session: aiohttp.ClientSession | None = None
        self._last_request_ts: float = 0.0
        self._consecutive_failures: int = 0
        self._circuit_open: bool = False

    # ── Session lifecycle ─────────────────────────────────────────────────────

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(limit_per_host=4)
            timeout   = aiohttp.ClientTimeout(total=20, connect=8)
            self._session = aiohttp.ClientSession(
                headers=self._headers,
                connector=connector,
                timeout=timeout,
                max_field_size=65536,  # Uber Eats CSP header supera el default de 8190
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.close()

    # ── Rate limiting ─────────────────────────────────────────────────────────

    async def _rate_limit(self) -> None:
        now  = time.monotonic()
        wait = self.min_interval - (now - self._last_request_ts)
        if wait > 0:
            logger.debug(f"[rate-limit] {self.base_url} — esperando {wait:.2f}s")
            await asyncio.sleep(wait)
        self._last_request_ts = time.monotonic()

    # ── Circuit breaker ───────────────────────────────────────────────────────

    def _record_success(self) -> None:
        self._consecutive_failures = 0
        self._circuit_open = False

    def _record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.CIRCUIT_BREAKER_THRESHOLD:
            if not self._circuit_open:
                logger.error(
                    f"[circuit-breaker] ABIERTO para {self.base_url} "
                    f"tras {self._consecutive_failures} fallos consecutivos"
                )
            self._circuit_open = True

    # ── Core request ──────────────────────────────────────────────────────────

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict | None = None,
        json: Any = None,
        data: Any = None,
        extra_headers: dict | None = None,
        max_retries: int | None = None,
    ) -> Any:
        """
        Realiza una solicitud HTTP con retry/backoff.

        Returns:
            dict | list del JSON parseado, o None si falla definitivamente.

        Raises:
            CircuitOpenError: si el circuit breaker está abierto.
        """
        if self._circuit_open:
            raise CircuitOpenError(f"Circuit abierto — {self.base_url}")

        retries = max_retries if max_retries is not None else self.DEFAULT_RETRIES
        url     = endpoint if endpoint.startswith("http") else f"{self.base_url}{endpoint}"

        for attempt in range(retries):
            await self._rate_limit()
            session = await self._get_session()

            req_headers = {}
            if extra_headers:
                req_headers.update(extra_headers)

            try:
                async with session.request(
                    method,
                    url,
                    params=params,
                    json=json,
                    data=data,
                    headers=req_headers or None,
                    allow_redirects=True,
                ) as resp:
                    status = resp.status
                    logger.debug(f"[{method}] {url} → HTTP {status} (intento {attempt + 1})")

                    if status == 200:
                        content_type = resp.headers.get("content-type", "")
                        if "json" in content_type:
                            self._record_success()
                            return await resp.json(content_type=None)
                        else:
                            # Retorna texto para endpoints que devuelven HTML (e.g. CSRF)
                            self._record_success()
                            return await resp.text()

                    if status in self.FATAL_STATUSES:
                        logger.warning(f"[{method}] {url} → HTTP {status} (fatal, no se reintenta)")
                        self._record_failure()
                        return None

                    if status in self.RETRY_STATUSES:
                        backoff = self.BACKOFF_BASE * (2 ** attempt)
                        # Respetar Retry-After si lo provee el servidor
                        retry_after = resp.headers.get("Retry-After")
                        if retry_after:
                            backoff = max(backoff, float(retry_after))
                        logger.warning(f"[{method}] {url} → HTTP {status}, esperando {backoff:.1f}s")
                        await asyncio.sleep(backoff)
                        continue

                    logger.warning(f"[{method}] {url} → HTTP {status} inesperado")
                    await asyncio.sleep(self.BACKOFF_BASE * (2 ** attempt))

            except asyncio.TimeoutError:
                backoff = self.BACKOFF_BASE * (2 ** attempt)
                logger.warning(f"[timeout] {url} (intento {attempt + 1}) — esperando {backoff:.1f}s")
                await asyncio.sleep(backoff)

            except aiohttp.ClientConnectorError as exc:
                logger.warning(f"[conn-error] {url}: {exc}")
                await asyncio.sleep(self.BACKOFF_BASE * (2 ** attempt))

            except Exception as exc:
                logger.error(f"[error] {url}: {type(exc).__name__}: {exc}")
                await asyncio.sleep(self.BACKOFF_BASE * (2 ** attempt))

        logger.error(f"[{method}] {url} — agotados {retries} intentos")
        self._record_failure()
        return None

    # ── Convenience wrappers ──────────────────────────────────────────────────

    async def get(self, endpoint: str, **kw) -> Any:
        return await self._make_request("GET", endpoint, **kw)

    async def post(self, endpoint: str, **kw) -> Any:
        return await self._make_request("POST", endpoint, **kw)
