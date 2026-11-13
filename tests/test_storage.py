"""Exercise the SQLite schema and column-name validation."""

import pandas as pd
import pytest

from src import MovieStorage
from src.database import get_connection
from src.storage import MOVIE_COLUMNS


def test_database_creates_parent_directory_and_nullable_schema(tmp_path):
    storage = MovieStorage(tmp_path / "nested" / "movies.db")
    connection = get_connection(storage.db_path)
    try:
        schema = connection.execute("PRAGMA table_info(movies)").fetchall()
        assert [column["name"] for column in schema] == ["id"] + MOVIE_COLUMNS
        assert schema[0]["type"] == "INTEGER"
        assert schema[0]["pk"] == 1
        assert all(column["notnull"] == 0 for column in schema[1:])
        connection.execute("INSERT INTO movies DEFAULT VALUES")
        connection.commit()
    finally:
        connection.close()
    assert storage.select_columns(MOVIE_COLUMNS) == [
        {"id": 1, "title": None, "release_year": None, "rating": None, "genre": None}
    ]


@pytest.mark.parametrize("columns", [[], ["unknown"], ["title; DROP TABLE movies"], ["id"]])
@pytest.mark.parametrize("method", ["select_columns", "query_movies"])
def test_invalid_column_selections_raise_value_error(test_storage, columns, method):
    with pytest.raises(ValueError):
        if method == "select_columns":
            test_storage.select_columns(columns)
        else:
            test_storage.query_movies(columns, 0, 5)
    assert test_storage.count_movies() == 0


def test_save_converts_pandas_missing_values_and_preserves_input(test_storage):
    movies = pd.DataFrame({
        "title": ["Movie A", pd.NA],
        "release_year": pd.Series([2020, pd.NA], dtype="Int64"),
        "rating": [float("nan"), 8.0],
        "genre": [None, "Drama"],
    })
    before = movies.copy(deep=True)
    test_storage.save(movies)
    pd.testing.assert_frame_equal(movies, before)
    assert test_storage.select_columns(MOVIE_COLUMNS) == [
        {"id": 1, "title": "Movie A", "release_year": 2020, "rating": None, "genre": None},
        {"id": 2, "title": None, "release_year": None, "rating": 8.0, "genre": "Drama"},
    ]
