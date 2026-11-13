"""Keep MP2 request IDs and request severity logging in the MP3 API."""

import logging
import re

import pytest


@pytest.mark.parametrize("path,status,level", [
    ("/health", 200, logging.INFO),
    ("/movies/search?columns=unknown", 400, logging.WARNING),
    ("/unknown", 404, logging.WARNING),
    ("/movies?limit=0", 422, logging.WARNING),
])
def test_request_ids_status_and_duration(client, caplog, path, status, level):
    with caplog.at_level(logging.INFO, logger="src.middleware"):
        response = client.get(path)
    assert response.status_code == status
    request_id = response.headers["X-Request-ID"]
    assert re.fullmatch(r"[0-9a-f]{8}", request_id)
    records = [record for record in caplog.records if record.name == "src.middleware"]
    assert len(records) == 1
    assert records[0].levelno == level
    message = records[0].getMessage()
    assert f"request_id={request_id} GET {path.split('?')[0]} status={status}" in message
    assert re.search(r"duration=\d+\.\dms", message)
    assert client.get("/health").headers["X-Request-ID"] != request_id
