"""Check cache lifetime and independent per-instance state."""

from src import MovieCache


def test_cache_round_trip_ttl_and_invalidation():
    cache = MovieCache()
    response = {"data": [{"id": 1, "title": None}], "total_rows": 1}
    try:
        assert cache.get(100) is None
        cache.set(100, response)
        assert cache.get(100) == response
        assert 0 < cache.client.ttl(cache.make_key(100)) <= 90
        assert cache.get(1) is None
        cache.set(1, response)
        cache.invalidate()
        assert cache.get(100) is None
        assert cache.get(1) is None
    finally:
        cache.client.close()


def test_new_cache_is_empty_without_affecting_existing_cache():
    first, restarted = MovieCache(), MovieCache()
    try:
        first.set(100, {"data": [], "total_rows": 0})
        assert restarted.get(100) is None
        assert first.get(100) == {"data": [], "total_rows": 0}
    finally:
        first.client.close()
        restarted.client.close()
