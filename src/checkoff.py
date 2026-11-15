"""Read-only code references and practice prompts for the local workspace."""

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Only these explicitly listed symbols can be read through the GUI.
TOPICS = {
    "health": {
        "title": "Health check",
        "explanation": "The endpoint returns the application's status and version. It can still answer after a rejected upload or invalid processing request.",
        "references": [("main.py", "health_check"), ("src/models.py", "HealthResponse")],
    },
    "upload": {
        "title": "CSV upload and validation",
        "explanation": "The endpoint checks the extension, parses CSV bytes, requires the four movie columns and at least one row, then saves and invalidates the cache only after success.",
        "references": [("main.py", "upload_movies"), ("src/models.py", "MovieUploadInfo")],
    },
    "storage": {
        "title": "SQLite persistence and atomic replacement",
        "explanation": "MovieStorage replaces rows in one SQLite transaction. Failed inserts roll back the deletion. Missing values become SQL NULL; connections close in finally. The database file survives server restarts.",
        "references": [("src/database.py", "get_connection"), ("src/database.py", "initialize_database"), ("src/storage.py", "MovieStorage.save"), ("src/storage.py", "MovieStorage.get")],
    },
    "retrieve": {
        "title": "Limited retrieval and total count",
        "explanation": "SQL LIMIT controls the returned records; SQL COUNT(*) independently counts the complete collection. Row IDs are included and ordered ascending.",
        "references": [("main.py", "get_movies"), ("src/storage.py", "MovieStorage.select_columns"), ("src/storage.py", "MovieStorage.count_movies")],
    },
    "search": {
        "title": "SQL filtering, selected columns and ordering",
        "explanation": "Only allowlisted column names enter SQL. The minimum rating and limit use placeholders. SQL sorts by rating DESC, then id ASC. Search bypasses the movie retrieval cache.",
        "references": [("main.py", "query_movies"), ("src/storage.py", "_selected_columns"), ("src/storage.py", "MovieStorage.query_movies")],
    },
    "cache": {
        "title": "Cache hits, expiry and invalidation",
        "explanation": "The limit is part of the cache key. A HIT returns before either database read. Responses expire after 90 seconds. Successful uploads and processing clear all limits; failures preserve existing entries.",
        "references": [("src/cache.py", "MovieCache"), ("main.py", "get_movies"), ("main.py", "upload_movies"), ("main.py", "process_movies")],
    },
    "processing": {
        "title": "Validation, cleaning and processing report",
        "explanation": "Pydantic settings become a dictionary. Numeric validation happens first; the cleaning report starts after that validation. Only successful processing is saved, followed by cache invalidation.",
        "references": [("main.py", "process_movies"), ("src/models.py", "ProcessConfig"), ("data_pipeline/data_processor.py", "process_data"), ("data_pipeline/data_processor.py", "create_cleaning_report")],
    },
    "validation": {
        "title": "Required columns and numeric validation",
        "explanation": "Missing configured columns raise ValueError. Non-missing values that cannot be numeric are removed; missing values remain for the later missing-value step.",
        "references": [("data_pipeline/data_validator.py", "validate_dataframe"), ("src/models.py", "ValidationSettings"), ("main.py", "process_movies")],
    },
    "outliers": {
        "title": "IQR and Z-score processing",
        "explanation": "IQR removes values below Q1 minus threshold times IQR or above Q3 plus threshold times IQR. Z-score uses population standard deviation. Unsupported methods and negative or non-finite thresholds raise ValueError when enabled.",
        "references": [("data_pipeline/data_processor.py", "remove_outliers"), ("src/models.py", "OutlierSettings")],
    },
    "missing": {
        "title": "Duplicate and missing-value handling",
        "explanation": "Cleaning runs duplicates, missing values, then outliers. Missing handling drops rows or columns. The fixed movie table stores dropped fields as NULL when the processed data is saved.",
        "references": [("data_pipeline/data_processor.py", "remove_duplicates"), ("data_pipeline/data_processor.py", "handle_missing"), ("src/storage.py", "MovieStorage.save")],
    },
    "errors": {
        "title": "HTTP errors and actual request logs",
        "explanation": "FastAPI rejects invalid query/body types with 422. Expected application ValueErrors become 400. The middleware attaches a request ID and logs status and duration; unexpected exceptions produce a generic 500 response with a server traceback.",
        "references": [("main.py", "log_http_error"), ("main.py", "log_validation_error"), ("src/middleware.py", "log_requests"), ("src/models.py", "ProcessConfig")],
    },
    "tests": {
        "title": "Three required tests",
        "explanation": "The persistence test opens a second storage object. The processing/cache test checks 20 to 16 rows and both invalidated limits. The HIT test patches both database reads to fail if called. Fixtures use isolated temporary databases.",
        "references": [("tests/test_api.py", "test_movies_persist"), ("tests/test_api.py", "test_cache_and_processing"), ("tests/test_api.py", "test_cache_hit_skips_database"), ("tests/conftest.py", "client")],
    },
}


def read_symbol(relative_path, qualified_name):
    """Return current line numbers and text for an allowlisted Python symbol."""
    path = PROJECT_ROOT / relative_path
    text = path.read_text(encoding="utf-8-sig")
    nodes = ast.parse(text).body
    node = None
    for part in qualified_name.split("."):
        node = next((candidate for candidate in nodes if getattr(candidate, "name", None) == part), None)
        if node is None:
            raise ValueError(f"Source symbol unavailable: {relative_path}:{qualified_name}")
        nodes = getattr(node, "body", [])
    start = min([node.lineno] + [decorator.lineno for decorator in getattr(node, "decorator_list", [])])
    return {
        "file": relative_path, "symbol": qualified_name,
        "start_line": start, "end_line": node.end_lineno,
        "lines": [{"number": number, "text": line} for number, line in enumerate(text.splitlines()[start - 1:node.end_lineno], start)],
    }


def get_source_topic(topic_id):
    if topic_id not in TOPICS:
        return None
    topic = TOPICS[topic_id]
    return {
        "id": topic_id, "title": topic["title"], "explanation": topic["explanation"],
        "sources": [read_symbol(*reference) for reference in topic["references"]],
    }


GUIDE = [
    {"id": "upload", "title": "Upload and replace", "steps": "Load the sample: 20 rows. Retrieve it. Upload it again and retrieve: still 20, not 40.", "expected": "The collection is replaced, and old retrieval caches are cleared.", "topics": ["upload", "storage", "cache"]},
    {"id": "limit", "title": "Limit and total count", "steps": "After a fresh sample upload, retrieve with limit 2. Try another positive limit, such as 5.", "expected": "Returned rows follow the limit; total_rows stays 20.", "topics": ["retrieve"], "preset": "limit-2"},
    {"id": "search", "title": "SQL search and selected columns", "steps": "Use a fresh sample. Search at 8.5 with limit 2. Leave Columns blank for the API default title, then try title,rating.", "expected": "Movie C (ID 4, 9.0), then Movie B (ID 2, 8.5). Search is not cached.", "topics": ["search"], "preset": "search"},
    {"id": "cache", "title": "Cache hits and invalidation", "steps": "After upload, retrieve limit 100 twice: MISS, HIT. Retrieve limit 1: MISS. Clean the collection, then retrieve each limit again.", "expected": "Cleaning invalidates both limits. Updated retrievals show 16 total rows with the default settings.", "topics": ["cache", "tests"]},
    {"id": "processing", "title": "Processing and IQR", "steps": "Upload a fresh sample, restore MP3 defaults and clean. To compare a different setting, upload the sample again before changing it.", "expected": "Default: 20 to 16; zero validation removals. Two duplicates and two rating outliers are removed.", "topics": ["processing", "outliers", "missing"], "preset": "defaults"},
    {"id": "numeric-missing", "title": "Numeric validation and missing values", "steps": "The 3-row example has one invalid year and one missing rating. Upload it, use MP3 defaults and clean.", "expected": "3 to 1 row: validation removes 1, then missing-row handling removes 1. This upload replaces the collection.", "topics": ["validation", "missing", "processing"], "preset": "numeric-missing"},
    {"id": "bad-extension", "title": "Error: unsupported file extension", "steps": "Send the .txt upload example, then use Check health.", "expected": "Upload: 400. Health: 200. Existing movies and caches remain unchanged.", "topics": ["upload", "errors"], "preset": "bad-extension"},
    {"id": "empty-csv", "title": "Error: empty CSV", "steps": "Send the empty CSV example.", "expected": "400 with a parsing error. Existing movies and caches remain unchanged.", "topics": ["upload", "errors"], "preset": "empty-csv"},
    {"id": "wrong-columns", "title": "Error: incorrect CSV columns", "steps": "Send the CSV containing only title and rating.", "expected": "400: the upload requires exactly the four movie columns.", "topics": ["upload", "errors"], "preset": "wrong-columns"},
    {"id": "invalid-limit", "title": "Error: invalid retrieval limit", "steps": "Prepare limit 0, then click Retrieve. Try abc to test a type error too.", "expected": "422 from FastAPI. The GUI does not block or replace the input.", "topics": ["retrieve", "errors"], "preset": "invalid-limit"},
    {"id": "invalid-column", "title": "Error: unsupported search column", "steps": "Prepare columns=unknown, then click Search.", "expected": "400 from the SQL column allowlist; the movie table remains intact.", "topics": ["search", "errors"], "preset": "invalid-column"},
    {"id": "invalid-method", "title": "Error: unsupported outlier method", "steps": "Prepare an unsupported method, then click Clean collection. The collection must contain rows.", "expected": "400 from processing. Database and existing caches are preserved.", "topics": ["outliers", "processing", "errors"], "preset": "invalid-method"},
    {"id": "negative-threshold", "title": "Error: negative outlier threshold", "steps": "Prepare threshold -1 with outliers enabled, then click Clean collection.", "expected": "400 from processing. Use abc instead to obtain a 422 model-validation error.", "topics": ["outliers", "errors"], "preset": "negative-threshold"},
    {"id": "missing-column", "title": "Error: required column is absent", "steps": "Prepare an additional required column named unknown, then click Clean collection.", "expected": "400 from validation. Unchecking a required column does not delete an actual data column.", "topics": ["validation", "processing"], "preset": "missing-column"},
    {"id": "malformed-json", "title": "Error: malformed processing JSON", "steps": "Prepare the incomplete JSON body, then click Clean collection. Raw text is sent unchanged.", "expected": "422 JSON decoding error, visible with the complete response and logs.", "topics": ["errors", "processing"], "preset": "malformed-json"},
    {"id": "persistence", "title": "Persistence across a real server restart", "steps": "Store or clean movies, stop the server with Ctrl+C, start it again, then Retrieve. Refreshing the browser does not restart the server.", "expected": "SQLite rows persist. FakeRedis starts empty, so the first retrieval is a MISS.", "topics": ["storage", "cache", "tests"], "command": ".\\venv\\Scripts\\python.exe -m uvicorn main:app --reload"},
    {"id": "tests", "title": "Required automated tests", "steps": "Run pytest in the project terminal. Use the code links to explain the three required tests and their isolated fixtures.", "expected": "Persistence, processing/cache invalidation, and a cache HIT that skips both database reads.", "topics": ["tests"], "command": ".\\venv\\Scripts\\python.exe -m pytest tests -v"},
]
