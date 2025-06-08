# backend/logging_config.py
import logging
import json
from datetime import datetime

class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": datetime.utcfromtimestamp(record.created).isoformat() + 'Z',
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "funcName": record.funcName,
            "lineno": record.lineno,
        }
        if hasattr(record, 'props') and record.props:
            log_record.update(record.props)

        # Include exception info if present
        if record.exc_info:
            log_record['exc_info'] = self.formatException(record.exc_info)
        if record.stack_info:
            log_record['stack_info'] = self.formatStack(record.stack_info)

        return json.dumps(log_record)

def setup_logging():
    logger = logging.getLogger() # Get root logger

    # Remove any existing handlers to avoid duplicate logs if setup_logging is called multiple times
    # or if other libraries (like uvicorn) configure the root logger.
    if logger.hasHandlers():
        logger.handlers.clear()

    handler = logging.StreamHandler() # Output to stdout/stderr
    formatter = JsonFormatter()
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO) # Set default level

    # Optionally, silence overly verbose loggers from libraries
    # logging.getLogger("uvicorn.access").setLevel(logging.WARNING) # Example
    # logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.WARNING)

# Example of how to get a configured logger instance (not strictly needed if root logger is used)
# def get_logger(name: str):
#     logger = logging.getLogger(name)
#     return logger
