"""DS 3500 MP3: persistent movie storage, SQL search, and caching."""

import io
import logging
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from data_pipeline import create_cleaning_report, process_data, validate_dataframe
from src import (
    HealthResponse,
    MovieCache,
    MovieDataResponse,
    MovieProcessingReport,
    MovieStorage,
    MovieUploadInfo,
    ProcessConfig,
    log_requests,
    setup_logging,
)
from src.storage import MOVIE_COLUMNS

setup_logging(verbose=True)
logger = logging.getLogger(__name__)

app = FastAPI(title="Movie Processing API", version="1.0.0")
app.middleware("http")(log_requests)
storage = MovieStorage()
cache = MovieCache()
PROJECT_ROOT = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=PROJECT_ROOT / "web"), name="static")


@app.get("/", include_in_schema=False)
def movie_workspace():
    """Serve the simple check-off interface alongside the existing API."""
    return FileResponse(PROJECT_ROOT / "web" / "index.html")


@app.get("/sample_movies.csv", include_in_schema=False)
def sample_movies():
    """Let the interface upload the official fixture through POST /upload."""
    return FileResponse(
        PROJECT_ROOT / "fixtures" / "sample_movies.csv",
        media_type="text/csv",
        filename="sample_movies.csv",
    )


@app.get("/health", response_model=HealthResponse)
def health_check():
    """Return the application status and version."""
    return HealthResponse(status="ok", version=app.version)


@app.post("/upload", response_model=MovieUploadInfo)
async def upload_movies(file: UploadFile = File(...)):
    """Validate a CSV upload and replace the stored movie collection."""
    extension = Path(file.filename or "").suffix.lower()
    if extension != ".csv":
        logger.warning("Unsupported file format: %s", extension or "(none)")
        raise HTTPException(status_code=400, detail="Only .csv files are supported.")

    contents = await file.read()
    try:
        df = pd.read_csv(io.BytesIO(contents))
    except (pd.errors.EmptyDataError, pd.errors.ParserError, UnicodeDecodeError) as error:
        logger.warning("Unable to read CSV upload %s: %s", file.filename, error)
        raise HTTPException(
            status_code=400,
            detail=(
                "Unable to read CSV. Provide a non-empty, UTF-8 encoded CSV "
                "with a header and consistent columns."
            ),
        ) from error

    if len(df.columns) != len(MOVIE_COLUMNS) or set(df.columns) != set(MOVIE_COLUMNS):
        raise HTTPException(
            status_code=400,
            detail=f"CSV must contain exactly these columns: {', '.join(MOVIE_COLUMNS)}",
        )
    if df.empty:
        raise HTTPException(status_code=400, detail="CSV must contain at least one data row.")
    df = df[MOVIE_COLUMNS]

    storage.save(df)
    cache.invalidate()
    logger.info(
        "Uploaded movies: filename=%s, rows=%s",
        file.filename,
        len(df),
    )
    return {
        "filename": file.filename,
        "rows": len(df),
        "columns": len(df.columns),
        "column_names": df.columns.tolist(),
    }


@app.get("/movies", response_model=MovieDataResponse)
def get_movies(response: Response, limit: int = Query(default=100, ge=1)):
    """Return a cached response or retrieve movies using SQL."""
    response.headers["Cache-Control"] = "no-store"
    cached = cache.get(limit)
    if cached is not None:
        response.headers["X-Movie-Cache"] = "HIT"
        logger.info("Movie cache hit: limit=%s", limit)
        return cached

    records = storage.select_columns(MOVIE_COLUMNS, limit)
    payload = {"data": records, "total_rows": storage.count_movies()}
    cache.set(limit, payload)
    response.headers["X-Movie-Cache"] = "MISS"
    logger.info("Retrieved movies: returned_rows=%s", len(records))
    return payload


@app.get("/movies/search", response_model=list[dict])
def query_movies(
    columns: list[str] = Query(default=["title"]),
    min_rating: float = Query(default=0, ge=0, le=10),
    limit: int = Query(default=100, ge=1),
):
    """Search with SQL; searches are not cached."""
    try:
        records = storage.query_movies(columns, min_rating, limit)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    logger.info(
        "Queried movies: columns=%s, min_rating=%s, returned_rows=%s",
        columns,
        min_rating,
        len(records),
    )
    return records


@app.post("/movies/process", response_model=MovieProcessingReport)
def process_movies(config: ProcessConfig):
    """Validate and process stored movies using the reusable MP1 modules."""
    df = storage.get()
    if df.empty:
        raise HTTPException(status_code=400, detail="No movies available to process.")

    settings = config.model_dump()
    validation = settings["validation"]
    try:
        for column in validation["numeric_columns"]:
            if column not in df.columns:
                raise ValueError(f"Numeric column missing: {column}")

        validated = validate_dataframe(
            df, validation["required_columns"], validation["numeric_columns"]
        )
        validation_rows_removed = len(df) - len(validated)
        logger.info(
            "Validated movies: rows_before=%s, rows_after=%s",
            len(df),
            len(validated),
        )
        before_processing = validated.copy()
        processed = process_data(validated, settings)
        cleaning_report = create_cleaning_report(before_processing, processed)
    except ValueError as error:
        logger.warning("Unable to process movies: %s", error)
        raise HTTPException(status_code=400, detail=str(error)) from error

    storage.save(processed)
    cache.invalidate()
    logger.info(
        "Processed movies: validation_removed=%s, rows_before=%s, rows_after=%s",
        validation_rows_removed,
        cleaning_report["rows_before"],
        cleaning_report["rows_after"],
    )
    return {
        "validation_rows_removed": validation_rows_removed,
        "cleaning_report": cleaning_report,
    }
