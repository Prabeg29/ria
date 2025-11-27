import atexit
import logging
import logging.config
import queue

from contextvars import ContextVar
from datetime import datetime, timezone
from logging.handlers import QueueListener
from typing import Any, Dict, override

from pythonjsonlogger.json import JsonFormatter

from .settings import settings


REQUEST_ID_CTX: ContextVar[str] = ContextVar("request_id", default="system")


class ContextFilter(logging.Filter):
    @override
    def filter(self, record: logging.LogRecord) -> bool | logging.LogRecord:
        record.request_id = REQUEST_ID_CTX.get()
        return True


class StructuredJsonFormatter(JsonFormatter):   
    def add_fields(
        self,
        log_data: Dict[str, Any],
        record: logging.LogRecord,
        message_dict: Dict[str, Any]
    ) -> None:
        super().add_fields(log_data, record, message_dict)
        log_data["request_id"] = getattr(record, "request_id", None)
        if not log_data.get('timestamp'):
            log_data["timestamp"] = datetime.fromtimestamp(
                record.created,
                tz=timezone.utc
            ).isoformat()


LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "context_filter": {
            "()": ContextFilter,
        }
    },
    "formatters": {
        "standard": {
            "format": "%(asctime)s [%(levelname)s] [%(request_id)s] %(name)s: %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S"
        },
        "json": {
            "()": StructuredJsonFormatter,
            "format": "%(timestamp)s %(levelname)s %(name)s %(request_id)s %(message)s"
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "filters": ["context_filter"],
            "stream": "ext://sys.stdout",
        },
        "queue_handler": {
            "class": "logging.handlers.QueueHandler",
            "queue": None,
        },
    },
    "loggers": {
        "": {
            "level": settings.log_level,
            "handlers": ["queue_handler"],
        },
    },
}


def setup_logging() -> logging.Logger:
    log_queue = queue.Queue(-1)
    LOGGING_CONFIG["handlers"]["queue_handler"]["queue"] = log_queue

    logging.config.dictConfig(LOGGING_CONFIG)
    console_handler = logging.getHandlerByName("console")

    listener = QueueListener(
        log_queue,
        console_handler, # type: ignore
        respect_handler_level=True,
    )

    listener.start()
    atexit.register(listener.stop)

    return logging.getLogger(settings.app_name)

logger = setup_logging()
