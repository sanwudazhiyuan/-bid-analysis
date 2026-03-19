import logging
from pathlib import Path
from rich.logging import RichHandler


def setup_logging(doc_name: str, log_dir: str = "output") -> logging.Logger:
    logger = logging.getLogger(f"bid_analyzer.{doc_name}")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    # Console: INFO via rich
    console = RichHandler(level=logging.INFO, show_path=False)
    logger.addHandler(console)

    # File: DEBUG
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(
        Path(log_dir) / f"{doc_name}.log", encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(file_handler)

    return logger
