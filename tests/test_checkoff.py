"""Verify real request diagnostics and current, allowlisted code references."""

from concurrent.futures import ThreadPoolExecutor
import logging
from pathlib import Path

import pytest

from src.checkoff import TOPICS


def get_logs(client, response):
    logs = client.get(f"/ui/requests/{response.headers['X-Request-ID']}")
    assert logs.status_code == 200
    return logs.json()


def test_request_logs_include_actual_cache_and_sql_records(client, uploaded_movies, caplog):
    with caplog.at_level(logging.DEBUG):
        first = client.get("/movies?limit=2")
        second = client.get("/movies?limit=2")
    first_logs = get_logs(client, first)
    second_logs = get_logs(client, second)
    assert first_logs["request_id"] != second_logs["request_id"]
    first_messages = "\n".join(entry["message"] for entry in first_logs["logs"])
    second_messages = "\n".join(entry["message"] for entry in second_logs["logs"])
    assert "Cache MISS: movies:limit:2" in first_messages
    assert "Selected movies:" in first_messages
    assert "Cache HIT: movies:limit:2" in second_messages
    assert "Selected movies:" not in second_messages
    assert any(entry["file"] == "src/storage.py" and entry["line"] > 0 for entry in first_logs["logs"])


def test_validation_errors_preserve_full_response_and_emit_related_logs(client, caplog):
    with caplog.at_level(logging.WARNING):
        response = client.get("/movies?limit=abc")
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["query", "limit"]
    messages = "\n".join(entry["message"] for entry in get_logs(client, response)["logs"])
    assert "Request validation failed:" in messages
    assert "abc" in messages
    assert "status=422" in messages


def test_concurrent_errors_keep_logs_separate(client, caplog):
    with caplog.at_level(logging.WARNING):
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda name: client.get(f"/movies/search?columns={name}"), ["invalid_a", "invalid_b"]))
    for response, own, other in zip(responses, ["invalid_a", "invalid_b"], ["invalid_b", "invalid_a"]):
        assert response.status_code == 400
        messages = "\n".join(entry["message"] for entry in get_logs(client, response)["logs"])
        assert own in messages
        assert other not in messages


@pytest.mark.parametrize("topic_id", list(TOPICS))
def test_code_references_match_current_files_and_line_numbers(client, topic_id):
    response = client.get(f"/ui/source/{topic_id}")
    assert response.status_code == 200
    for source in response.json()["sources"]:
        path = Path(__file__).resolve().parents[1] / source["file"]
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        assert source["lines"][0]["text"] == lines[source["start_line"] - 1]
        assert source["lines"][-1]["text"] == lines[source["end_line"] - 1]
        assert [line["number"] for line in source["lines"]] == list(range(source["start_line"], source["end_line"] + 1))


def test_unknown_code_paths_and_requests_are_not_exposed(client):
    assert client.get("/ui/source/.env").status_code == 404
    assert client.get("/ui/requests/unknown").status_code == 404
    guide = client.get("/ui/guide")
    assert guide.status_code == 200
    assert {"invalid-limit", "invalid-method", "malformed-json", "persistence", "tests"} <= {scenario["id"] for scenario in guide.json()["scenarios"]}
