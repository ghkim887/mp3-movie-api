"""Verify MP3 persistence, SQL search, processing, and cache behavior."""

import io
import logging

import pandas as pd
import pytest

import main
from src import MovieStorage
from src.database import get_connection
from src.storage import MOVIE_COLUMNS


def upload(client, contents, filename="sample_movies.csv"):
    return client.post(
        "/upload", files={"file": (filename, contents, "text/csv")}
    )


def test_movies_persist(client, test_storage, uploaded_movies, sample_csv_bytes):
    reopened = MovieStorage(test_storage.db_path)
    movies = reopened.get()
    assert reopened.count_movies() == len(movies) == 20
    assert movies.columns.tolist() == MOVIE_COLUMNS
    original = pd.read_csv(io.BytesIO(sample_csv_bytes))
    assert movies["title"].tolist() == original["title"].tolist()
    response = client.get("/movies", params={"limit": 100})
    assert response.status_code == 200
    stored_ids = [row["id"] for row in reopened.select_columns(MOVIE_COLUMNS, 100)]
    assert stored_ids == [row["id"] for row in response.json()["data"]]
    assert stored_ids == list(range(1, 21))


def test_cache_and_processing(client, uploaded_movies, processing_body):
    for limit in (100, 1):
        response = client.get("/movies", params={"limit": limit})
        assert response.status_code == 200
        assert response.json()["total_rows"] == 20
        assert len(response.json()["data"]) == min(limit, 20)
        assert main.cache.get(limit) == response.json()
    original = main.cache.get(100)
    assert client.get("/movies?limit=100").json() == original

    response = client.post("/movies/process", json=processing_body)
    assert response.status_code == 200
    assert response.json() == {
        "validation_rows_removed": 0,
        "cleaning_report": {
            "rows_before": 20, "rows_after": 16, "rows_removed": 4,
            "columns_before": 4, "columns_after": 4, "columns_removed": 0,
        },
    }
    assert main.cache.get(100) is None
    assert main.cache.get(1) is None
    retrieved = client.get("/movies?limit=100")
    assert retrieved.status_code == 200
    body = retrieved.json()
    assert body["total_rows"] == len(body["data"]) == 16
    assert [row["title"] for row in body["data"]] == [
        f"Movie {letter}" for letter in "ABCDEFGHIJKLMNOP"
    ]
    assert [row["id"] for row in body["data"]] == list(range(1, 17))
    assert main.cache.get(100) == body


def test_cache_hit_skips_database(client, uploaded_movies, monkeypatch):
    first = client.get("/movies?limit=100")
    assert first.status_code == 200

    def unexpected_read(*args, **kwargs):
        pytest.fail("A cache hit must skip SQL retrieval and counting")

    monkeypatch.setattr(main.storage, "select_columns", unexpected_read)
    monkeypatch.setattr(main.storage, "count_movies", unexpected_read)
    repeated = client.get("/movies?limit=100")
    assert repeated.status_code == 200
    assert repeated.json() == first.json()


def test_cache_headers_report_actual_lookup_and_invalidation(
    client, uploaded_movies, processing_body
):
    first = client.get("/movies?limit=100")
    assert first.headers["X-Movie-Cache"] == "MISS"
    assert first.headers["Cache-Control"] == "no-store"
    repeated = client.get("/movies?limit=100")
    assert repeated.headers["X-Movie-Cache"] == "HIT"
    assert repeated.json() == first.json()
    assert client.get("/movies?limit=1").headers["X-Movie-Cache"] == "MISS"
    assert client.post("/movies/process", json=processing_body).status_code == 200
    updated = client.get("/movies?limit=100")
    assert updated.headers["X-Movie-Cache"] == "MISS"
    assert updated.json()["total_rows"] == 16


def test_gui_and_official_sample_are_served_without_changing_storage(
    client, sample_csv_bytes
):
    page = client.get("/")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert "Load sample CSV" in page.text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200
    sample = client.get("/sample_movies.csv")
    assert sample.status_code == 200
    assert sample.content == sample_csv_bytes
    assert main.storage.count_movies() == 0


def test_health_and_documented_endpoints(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "1.0.0"}
    assert client.get("/docs").status_code == 200
    schema = client.get("/openapi.json").json()
    assert set(schema["paths"]) == {
        "/health", "/upload", "/movies", "/movies/search", "/movies/process"
    }
    for route, method, model in [
        ("/upload", "post", "MovieUploadInfo"),
        ("/movies", "get", "MovieDataResponse"),
        ("/movies/process", "post", "MovieProcessingReport"),
    ]:
        result = schema["paths"][route][method]["responses"]["200"]
        assert result["content"]["application/json"]["schema"]["$ref"].endswith(model)


def test_upload_and_limited_retrieval(client, sample_csv_bytes):
    response = upload(client, sample_csv_bytes, "SAMPLE.CSV")
    assert response.status_code == 200
    assert response.json() == {
        "filename": "SAMPLE.CSV", "rows": 20, "columns": 4,
        "column_names": MOVIE_COLUMNS,
    }
    retrieved = client.get("/movies?limit=2")
    assert retrieved.status_code == 200
    assert retrieved.json() == {
        "data": [
            {"id": 1, "title": "Movie A", "release_year": 2020, "rating": 8.0, "genre": "Drama"},
            {"id": 2, "title": "Movie B", "release_year": 2021, "rating": 8.5, "genre": "Comedy"},
        ],
        "total_rows": 20,
    }


def test_empty_collection(client, processing_body):
    assert client.get("/movies").json() == {"data": [], "total_rows": 0}
    assert client.get("/movies/search").json() == []
    assert client.post("/movies/process", json=processing_body).status_code == 400


def test_reupload_replaces_collection_and_invalidates_all_limits(
    client, uploaded_movies, processing_body, sample_csv_bytes
):
    assert client.post("/movies/process", json=processing_body).status_code == 200
    for limit in (100, 1):
        assert client.get(f"/movies?limit={limit}").json()["total_rows"] == 16
    assert upload(client, sample_csv_bytes).status_code == 200
    assert main.cache.get(100) is None
    assert main.cache.get(1) is None
    retrieved = client.get("/movies").json()
    assert retrieved["total_rows"] == len(retrieved["data"]) == 20
    assert [row["id"] for row in retrieved["data"]] == list(range(1, 21))


@pytest.mark.parametrize(
    "contents,filename",
    [
        (b"ignored", "movies.txt"),
        (b"ignored", "movies.csv.exe"),
        (b"", "movies.csv"),
        (b'title,release_year,rating,genre\n"unterminated', "movies.csv"),
        (b"title,release_year,rating,genre\n\xff,2020,8,Drama\n", "movies.csv"),
        (b"title,release_year,rating,genre\n", "movies.csv"),
        (b"title,rating,genre\nMovie A,8,Drama\n", "movies.csv"),
        (b"title,release_year,rating,genre,extra\nMovie A,2020,8,Drama,x\n", "movies.csv"),
        (b"title,title,rating,genre\nMovie A,2020,8,Drama\n", "movies.csv"),
    ],
    ids=["extension", "double-extension", "empty", "malformed", "encoding",
         "headers-only", "missing-column", "extra-column", "duplicate-column"],
)
def test_bad_upload_preserves_database_and_cache(
    client, uploaded_movies, contents, filename
):
    before = client.get("/movies").json()
    response = upload(client, contents, filename)
    assert response.status_code == 400
    assert main.cache.get(100) == before
    assert main.storage.select_columns(MOVIE_COLUMNS, 100) == before["data"]
    assert main.storage.count_movies() == 20
    assert client.get("/health").status_code == 200


def test_upload_reorders_columns(client):
    response = upload(client, b"genre,rating,title,release_year\nDrama,8,Movie A,2020\n")
    assert response.status_code == 200
    assert response.json()["column_names"] == MOVIE_COLUMNS
    assert client.get("/movies").json()["data"][0] == {
        "id": 1, "title": "Movie A", "release_year": 2020, "rating": 8.0, "genre": "Drama"
    }


def test_search_projection_filter_order_and_no_matches(client, uploaded_movies):
    default = client.get("/movies/search?min_rating=8.5&limit=2")
    assert default.status_code == 200
    assert default.json() == [{"id": 4, "title": "Movie C"}, {"id": 2, "title": "Movie B"}]
    projected = client.get(
        "/movies/search",
        params=[("columns", "title"), ("columns", "rating"), ("min_rating", 8.5), ("limit", 3)],
    )
    assert projected.status_code == 200
    assert projected.json() == [
        {"id": 4, "title": "Movie C", "rating": 9.0},
        {"id": 2, "title": "Movie B", "rating": 8.5},
        {"id": 3, "title": "Movie B", "rating": 8.5},
    ]
    assert client.get("/movies/search?min_rating=10").json() == []
    assert client.get("/movies/search?columns=unknown").status_code == 400


def test_search_bypasses_cache(client, uploaded_movies, monkeypatch):
    def unexpected_cache(*args, **kwargs):
        pytest.fail("Movie searches must remain uncached")

    monkeypatch.setattr(main.cache, "get", unexpected_cache)
    monkeypatch.setattr(main.cache, "set", unexpected_cache)
    for _ in range(2):
        response = client.get("/movies/search?min_rating=9")
        assert response.status_code == 200
        assert response.json() == [{"id": 4, "title": "Movie C"}]


@pytest.mark.parametrize("url", [
    "/movies?limit=0", "/movies?limit=-1", "/movies?limit=abc",
    "/movies/search?limit=0", "/movies/search?min_rating=-1",
    "/movies/search?min_rating=11", "/movies/search?min_rating=abc",
])
def test_invalid_query_parameters(client, url):
    assert client.get(url).status_code == 422


@pytest.mark.parametrize("body", [None, [], {"validation": None}])
def test_invalid_processing_body(client, uploaded_movies, body):
    assert client.post("/movies/process", json=body).status_code == 422
    assert main.storage.count_movies() == 20


@pytest.mark.parametrize("section,changes", [
    ("validation", {"required_columns": ["unknown"]}),
    ("validation", {"numeric_columns": ["unknown"]}),
    ("missing", {"axis": "invalid"}),
    ("outliers", {"method": "invalid"}),
    ("outliers", {"threshold": -1}),
])
def test_failed_processing_preserves_database_and_cache(
    client, uploaded_movies, processing_body, section, changes
):
    before = client.get("/movies").json()
    if section == "validation":
        processing_body[section].update(changes)
    else:
        processing_body["processing"][section].update(changes)
    response = client.post("/movies/process", json=processing_body)
    assert response.status_code == 400
    assert main.cache.get(100) == before
    assert main.storage.select_columns(MOVIE_COLUMNS, 100) == before["data"]


def test_missing_values_are_sql_null_and_removed_by_processing(client, processing_body):
    contents = (
        "title,release_year,rating,genre\n"
        "Movie A,2020,8,Drama\nMovie B,,8.5,Comedy\n"
        "Movie C,2022,,Drama\nMovie D,2023,8.2,\n"
    )
    assert upload(client, contents).status_code == 200
    response = client.get("/movies")
    rows = response.json()["data"]
    assert rows[1]["release_year"] is None
    assert rows[2]["rating"] is None
    assert rows[3]["genre"] is None
    assert "NaN" not in response.text
    connection = get_connection(main.storage.db_path)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM movies WHERE release_year IS NULL "
            "OR rating IS NULL OR genre IS NULL"
        ).fetchone()[0] == 3
    finally:
        connection.close()
    processed = client.post("/movies/process", json=processing_body)
    assert processed.status_code == 200
    assert processed.json()["validation_rows_removed"] == 0
    assert processed.json()["cleaning_report"]["rows_after"] == 1
    assert client.get("/movies").json()["data"][0]["title"] == "Movie A"


def test_validation_can_remove_all_rows(client, processing_body):
    assert upload(client, "title,release_year,rating,genre\nMovie A,unknown,8,Drama\n").status_code == 200
    client.get("/movies")
    processed = client.post("/movies/process", json=processing_body)
    assert processed.status_code == 200
    assert processed.json()["validation_rows_removed"] == 1
    assert main.cache.get(100) is None
    assert client.get("/movies").json() == {"data": [], "total_rows": 0}
    assert main.storage.get().columns.tolist() == MOVIE_COLUMNS


@pytest.mark.parametrize("endpoint", ["/upload", "/movies/process"])
def test_sql_failure_rolls_back_and_preserves_cache(
    client, uploaded_movies, processing_body, sample_csv_bytes, endpoint
):
    before = client.get("/movies").json()
    connection = get_connection(main.storage.db_path)
    try:
        connection.execute(
            "CREATE TRIGGER reject_movie BEFORE INSERT ON movies "
            "WHEN NEW.title = 'Movie B' "
            "BEGIN SELECT RAISE(ABORT, 'test insertion failure'); END"
        )
        connection.commit()
    finally:
        connection.close()
    if endpoint == "/upload":
        response = upload(client, sample_csv_bytes)
    else:
        response = client.post(endpoint, json=processing_body)
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert main.cache.get(100) == before
    assert main.storage.select_columns(MOVIE_COLUMNS, 100) == before["data"]
    assert main.storage.count_movies() == 20


def test_cache_hit_and_invalidation_logs(client, uploaded_movies, caplog):
    with caplog.at_level(logging.DEBUG):
        client.get("/movies")
        client.get("/movies")
        main.cache.invalidate()
    assert "Cache MISS: movies:limit:100" in caplog.text
    assert "Cache HIT: movies:limit:100" in caplog.text
    assert "Invalidated movie cache" in caplog.text
