"""Store and query one persistent movie collection using SQL."""

import logging
import sqlite3

import pandas as pd

from .database import get_connection, initialize_database

logger = logging.getLogger(__name__)
MOVIE_COLUMNS = ["title", "release_year", "rating", "genre"]


def _selected_columns(columns):
    """Allow only known identifiers before including them in SQL."""
    if not columns:
        logger.error("Select at least one column")
        raise ValueError("Select at least one column")
    for column in columns:
        if column not in MOVIE_COLUMNS:
            logger.error("Unsupported column: %s", column)
            raise ValueError(f"Unsupported column: {column}")
    return ", ".join(["id"] + columns)


class MovieStorage:
    def __init__(self, db_path="data/movies.db"):
        self.db_path = db_path
        initialize_database(self.db_path)

    def save(self, df):
        """Replace all movie rows in one transaction, resetting row IDs."""
        # A processing step may drop a column; retain the fixed SQL schema
        # and store that field as NULL. Convert all pandas missing values.
        movies = df.reindex(columns=MOVIE_COLUMNS).astype(object)
        movies = movies.where(pd.notna(movies), None)
        connection = get_connection(self.db_path)
        try:
            connection.execute("DELETE FROM movies")
            connection.executemany(
                "INSERT INTO movies (title, release_year, rating, genre) "
                "VALUES (?, ?, ?, ?)",
                movies.itertuples(index=False, name=None),
            )
            connection.commit()
            logger.debug("Stored movies in SQLite: rows=%s", len(movies))
        except sqlite3.Error:
            connection.rollback()
            logger.error("Unable to save movies; transaction rolled back", exc_info=True)
            raise
        finally:
            connection.close()

    def get(self):
        """Return the four movie columns as a DataFrame, ordered by id."""
        connection = get_connection(self.db_path)
        try:
            rows = connection.execute(
                "SELECT title, release_year, rating, genre FROM movies ORDER BY id"
            ).fetchall()
            return pd.DataFrame([tuple(row) for row in rows], columns=MOVIE_COLUMNS)
        finally:
            connection.close()

    def select_columns(self, columns, limit=5):
        """Return id plus the requested movie columns, ordered by id."""
        selected_columns = _selected_columns(columns)
        connection = get_connection(self.db_path)
        try:
            rows = connection.execute(
                f"SELECT {selected_columns} FROM movies ORDER BY id LIMIT ?",
                (limit,),
            ).fetchall()
            records = [dict(row) for row in rows]
            logger.debug(
                "Selected movies: columns=%s, returned_rows=%s", columns, len(records)
            )
            return records
        finally:
            connection.close()

    def count_movies(self):
        """Return the number of stored movies using SQL COUNT(*)."""
        connection = get_connection(self.db_path)
        try:
            return connection.execute("SELECT COUNT(*) FROM movies").fetchone()[0]
        finally:
            connection.close()

    def query_movies(self, columns, min_rating, limit):
        """Filter and sort movies in SQL, returning id plus selected fields."""
        selected_columns = _selected_columns(columns)
        connection = get_connection(self.db_path)
        try:
            rows = connection.execute(
                f"SELECT {selected_columns} FROM movies WHERE rating >= ? "
                "ORDER BY rating DESC, id ASC LIMIT ?",
                (min_rating, limit),
            ).fetchall()
            records = [dict(row) for row in rows]
            logger.debug(
                "Queried movies: columns=%s, returned_rows=%s", columns, len(records)
            )
            return records
        finally:
            connection.close()
