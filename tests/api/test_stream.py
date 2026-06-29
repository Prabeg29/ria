import json
import uuid

import pytest
from fastapi.testclient import TestClient
from redis import Redis

from src.settings import settings


@pytest.fixture
def redis_client() -> Redis:
    return Redis(host=settings.redis_host, port=settings.redis_port, decode_responses=True)


def test_stream_response_content_type(client: TestClient, redis_client: Redis) -> None:
    # Arrange
    job_id = str(uuid.uuid4())
    stream_key = f"analysis:stream:{job_id}"
    redis_client.xadd(stream_key, {"type": "done", "payload": json.dumps({})})

    try:
        # Act
        response = client.get(f"/analysis/{job_id}/stream")

        # Assert
        assert response.headers["content-type"].startswith("text/event-stream")
    finally:
        redis_client.delete(stream_key)


def test_stream_forwards_chunk_events_in_order(client: TestClient, redis_client: Redis) -> None:
    # Arrange
    job_id = str(uuid.uuid4())
    stream_key = f"analysis:stream:{job_id}"
    redis_client.xadd(stream_key, {"type": "chunk", "payload": json.dumps({"text": "Hello"})})
    redis_client.xadd(stream_key, {"type": "chunk", "payload": json.dumps({"text": " world"})})
    redis_client.xadd(stream_key, {"type": "done", "payload": json.dumps({})})

    try:
        # Act
        response = client.get(f"/analysis/{job_id}/stream")
        body = response.text

        # Assert
        assert 'event: chunk\ndata: {"text": "Hello"}' in body
        assert 'event: chunk\ndata: {"text": " world"}' in body
        assert body.index('"Hello"') < body.index('" world"')
    finally:
        redis_client.delete(stream_key)


def test_stream_terminates_after_done_event(client: TestClient, redis_client: Redis) -> None:
    # Arrange — pre-seed includes done event so the generator returns without blocking
    job_id = str(uuid.uuid4())
    stream_key = f"analysis:stream:{job_id}"
    redis_client.xadd(stream_key, {"type": "chunk", "payload": json.dumps({"text": "partial"})})
    redis_client.xadd(stream_key, {"type": "done", "payload": json.dumps({})})

    try:
        # Act
        response = client.get(f"/analysis/{job_id}/stream")
        body = response.text

        # Assert — body ends with the done event; nothing published after it
        assert body.endswith("event: done\ndata: {}\n\n")
    finally:
        redis_client.delete(stream_key)
