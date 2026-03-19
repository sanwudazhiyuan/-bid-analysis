import logging
from src.logger import setup_logging


def test_setup_logging_returns_logger():
    logger = setup_logging("test_doc")
    assert isinstance(logger, logging.Logger)
    assert logger.level == logging.DEBUG


def test_log_file_created(tmp_path):
    logger = setup_logging("test_doc", log_dir=str(tmp_path))
    logger.info("test message")
    log_files = list(tmp_path.glob("*.log"))
    assert len(log_files) == 1
