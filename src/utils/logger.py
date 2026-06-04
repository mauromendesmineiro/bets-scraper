"""
Logger estruturado — substitui os print() espalhados pelo código original.
Usa o módulo logging padrão com formatação clara e ficheiro de log diário.
"""
import logging
import sys
from datetime import datetime
from pathlib import Path


def get_logger(name: str, log_dir: str = "logs") -> logging.Logger:
    """
    Devolve um logger configurado com:
    - Output no stdout (para cloud/containers)
    - Ficheiro diário em logs/ (para desenvolvimento local)
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger  # já configurado, evita handlers duplicados

    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)-8s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )

    # Handler: stdout (sempre activo — essencial para containers)
    # Força UTF-8 para evitar UnicodeEncodeError no Windows (cp1252 por defeito)
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.INFO)
    stdout_handler.setFormatter(fmt)
    logger.addHandler(stdout_handler)

    # Handler: ficheiro diário (só em desenvolvimento)
    try:
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        file_handler = logging.FileHandler(log_path / f"{today}.log", encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)
    except Exception:
        pass  # em cloud sem disco persistente, ignora silenciosamente

    return logger
