import logging
import pytest
from mcp_openapi_proxy.logging_setup import setup_logging

def test_setup_logging_debug_level():
    logger = setup_logging(debug=True)
    assert logger.level == logging.DEBUG
    logger = setup_logging(debug=False)
    assert logger.level == logging.INFO

def test_logger_single_handler():
    logger = setup_logging(debug=False)
    handler_count = len(logger.handlers)
    # Calling setup_logging again should not add duplicate handlers
    logger = setup_logging(debug=False)
    assert len(logger.handlers) == handler_count

@pytest.mark.parametrize("level", [logging.INFO, logging.DEBUG])
def test_logger_emits_messages(level, caplog):
    logger = setup_logging(debug=(level == logging.DEBUG))
    with caplog.at_level(level):
        logger.log(level, "Test message")
    assert any("Test message" in r.message for r in caplog.records)
