import uuid

from fastapi import status
from fastapi.testclient import TestClient


def test_trigger_is_rejected_for_non_existing_id(client: TestClient) -> None:
    non_existing_id = str(uuid.uuid4())

    response = client.post(
        "/resumes/upload/complete",
        json={
            "resume_id": non_existing_id
        }
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
