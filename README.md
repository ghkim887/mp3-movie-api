# MP3 Movie API

This FastAPI application extends MP2 with persistent storage for one movie collection and SQL-based movie searches.
The upload endpoint accepts a nonempty CSV with exactly `title`, `release_year`, `rating`, and `genre`, then replaces the collection in a single SQLite transaction.
`src/database.py` creates the database and table, while `src/storage.py` uses SQL to insert, retrieve, count, filter, and sort movies.
The processing endpoint reuses the MP1 modules in `data_pipeline/` to validate numeric values, remove duplicates, handle missing values, and remove outliers before saving the results.
`src/cache.py` uses a dedicated FakeRedis instance to cache complete `GET /movies` responses by limit for 90 seconds, and successful uploads and processing clear every cached limit.
Movie searches remain uncached, SQLite data survives server restarts, and the in-process cache starts empty after each restart.
The models, logging utilities, and middleware in `src/` provide request validation, response schemas, request IDs, and request timing logs.
The browser interface in `web/` presents editable processing settings with an MP3 default preset, simple retrieval controls, and visible cache results for check-off demonstrations.

## Setup and run

Run these commands from the project root in Windows PowerShell:

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -X utf8 start_gui.py
```

After the initial setup, double-click **`Start Movie GUI.cmd`** to start the server and open the interface automatically.
The launcher normally uses [the movie workspace](http://127.0.0.1:8000/), reuses an existing movie server, or selects the next free port if another app occupies port 8000.
Keep its console window open during the demo; press `Ctrl+C` to stop the server.
For development, run `.\venv\Scripts\python.exe -m uvicorn main:app --reload` instead.
The original [Swagger UI](http://127.0.0.1:8000/docs) is also available for direct API requests.
The default database is `data/movies.db`, relative to the project root, and its directory is created automatically.
`data/`, virtual environments, logs, and generated caches are excluded by `.gitignore`.
`requirements.txt` records the installed dependency versions using `pip freeze`.

| Method | Endpoint | Behavior |
| --- | --- | --- |
| GET | `/health` | Return application status and version. |
| POST | `/upload` | Replace the collection with an uploaded movie CSV. |
| GET | `/movies?limit=100` | Return up to the limit with IDs and the complete collection's row count. |
| GET | `/movies/search?columns=title&columns=rating&min_rating=8.5&limit=2` | Use SQL to filter by minimum rating, sort by rating descending then ID ascending, and select fields. |
| POST | `/movies/process` | Validate and clean the current collection, then replace its rows. |

## Simple GUI demo

1. Click **Load sample CSV**. The interface uploads the official fixture and retrieves 20 movies; the result badge shows **Database · MISS**.
2. Click **Retrieve** again to see **Cache · HIT**. Select **First 1 row** and retrieve to demonstrate a separate cache entry.
3. Click **Find top 2** with the default minimum rating of 8.5. The results show Movie C and Movie B; SQL search is explicitly marked **Not cached**.
4. Click **Clean collection**. The default assignment settings produce **20 → 16** movies, clear prior cached limits, and retrieve the updated collection from SQLite. Another retrieval shows **HIT**.
5. Stop and restart the server with the launcher, then retrieve the collection to show that the 16 movies persisted. Load the sample again to demonstrate replacement with 20 rows.

Open **Processing settings** to change duplicate removal, missing-value handling and axis, outlier detection and columns, IQR/Z-score method and threshold, and required/numeric validation columns.
Click **Use MP3 defaults** to restore the assignment settings; changes apply only when **Clean collection** is clicked.
The panel starts collapsed, and no JSON editing is needed.
**Choose CSV** uploads another file, and **Back to collection** exits the search view.
The optional **Request activity** section shows real API requests, cache events, request IDs, and timings.
`X-Movie-Cache` response headers report actual cache lookups; the movie JSON response format is unchanged.

## Sample workflow

1. Upload the official Canvas fixture `fixtures/sample_movies.csv`: the response reports 20 rows and four columns.
2. Retrieve `/movies?limit=100` twice to observe a cache MISS followed by a HIT; `/movies?limit=1` uses a separate cache entry.
3. Search with `min_rating=8.5` and `limit=2`: the first results are Movie C (ID 4, rating 9.0) and Movie B (ID 2, rating 8.5).
4. Send the following JSON body to `POST /movies/process`:

```json
{
  "validation": {
    "required_columns": ["title", "release_year", "rating", "genre"],
    "numeric_columns": ["release_year", "rating"]
  },
  "processing": {
    "remove_duplicates": true,
    "missing": {"enabled": true, "axis": "rows"},
    "outliers": {
      "enabled": true,
      "columns": ["rating"],
      "method": "iqr",
      "threshold": 1.5
    }
  }
}
```

Expected response:

```json
{
  "validation_rows_removed": 0,
  "cleaning_report": {
    "rows_before": 20,
    "rows_after": 16,
    "rows_removed": 4,
    "columns_before": 4,
    "columns_after": 4,
    "columns_removed": 0
  }
}
```

Two duplicate rows and two rating outliers are removed.
The next retrieval misses the invalidated cache and returns Movie A through Movie P with IDs 1 through 16; repeating it hits the new cache.
Restarting the server preserves these 16 movies, and uploading the fixture again replaces them with 20 rows.
Missing CSV values are stored as SQL `NULL` and returned as JSON `null`.
If processing is configured to remove columns, those fields remain in the fixed movie table as `NULL`.
Failed validation, processing, or SQL writes preserve both the previous database contents and the cached responses.

## Tests

```powershell
.\venv\Scripts\python.exe -m pytest tests -v
```

The 57 tests include the three required tests: `test_movies_persist`, `test_cache_and_processing`, and `test_cache_hit_skips_database`.
Each API test uses a temporary SQLite database and a fresh cache.
Additional checks cover SQL ordering, column validation, NULL conversion, upload replacement, cache lifetime and invalidation, transaction rollback, failed processing, and request logging.
The copied Starlette/httpx TestClient combination emits one deprecation warning; the tests pass with the pinned dependencies.
