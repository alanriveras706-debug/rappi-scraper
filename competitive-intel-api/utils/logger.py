"""
utils/logger.py
───────────────
Configuración centralizada de loguru.
Crea un log en consola (nivel INFO) y un archivo rotativo en logs/.
"""

import sys
from pathlib import Path

from loguru import logger


def setup_logger(log_dir: str | Path = "logs", level: str = "INFO") -> None:
    """
    Configura loguru con:
      - Salida a consola con color (nivel configurable, default INFO)
      - Archivo rotativo en {log_dir}/scraper_{fecha}.log (nivel DEBUG)

    Llamar una sola vez al inicio de main.py.
    """
    logger.remove()  # quitar handler por defecto

    # Consola: nivel configurable, formato compacto
    logger.add(
        sys.stderr,
        level=level,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | {message}",
        colorize=True,
    )

    # Archivo: siempre DEBUG, rotación diaria, retención 7 días
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    logger.add(
        log_path / "scraper_{time:YYYYMMDD}.log",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <7} | {name}:{line} | {message}",
        rotation="00:00",
        retention="7 days",
        encoding="utf-8",
    )
