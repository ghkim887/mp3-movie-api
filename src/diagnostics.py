"""Keep a bounded, request-correlated copy of real application log records."""

from collections import OrderedDict, deque
from contextvars import ContextVar
from copy import deepcopy
import logging
from pathlib import Path
from threading import RLock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
current_request_id = ContextVar("movie_request_id", default=None)


class RequestJournal:
    def __init__(self, capacity=100, logs_per_request=100):
        self.capacity = capacity
        self.logs_per_request = logs_per_request
        self.requests = OrderedDict()
        self.lock = RLock()

    def begin(self, request_id, method, path):
        with self.lock:
            self.requests[request_id] = {
                "request_id": request_id, "method": method, "path": path,
                "logs": deque(maxlen=self.logs_per_request),
            }
            while len(self.requests) > self.capacity:
                self.requests.popitem(last=False)
        return current_request_id.set(request_id)

    def append(self, request_id, entry):
        with self.lock:
            if request_id in self.requests:
                self.requests[request_id]["logs"].append(entry)

    def get(self, request_id):
        with self.lock:
            entry = self.requests.get(request_id)
            if entry is None:
                return None
            return deepcopy({**entry, "logs": list(entry["logs"])})


journal = RequestJournal()


class RequestLogHandler(logging.Handler):
    movie_request_handler = True

    def emit(self, record):
        request_id = current_request_id.get()
        if request_id is None or not record.name.startswith(("main", "src.", "data_pipeline.")):
            return
        try:
            source_file = str(Path(record.pathname).resolve().relative_to(PROJECT_ROOT)).replace("\\", "/")
        except ValueError:
            source_file = None
        entry = {
            "timestamp": record.created,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage()[:8000],
            "file": source_file,
            "line": record.lineno,
        }
        if record.exc_info:
            entry["traceback"] = logging.Formatter().formatException(record.exc_info)[:16000]
        journal.append(request_id, entry)


def install_request_logging():
    root = logging.getLogger()
    if not any(getattr(handler, "movie_request_handler", False) for handler in root.handlers):
        root.addHandler(RequestLogHandler())
