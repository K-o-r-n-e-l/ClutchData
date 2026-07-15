from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_get_player_stats():
    response = client.get("/api/stats/test_player")
    assert response.status_code == 200
    data = response.json()
    assert data["player_id"] == "test_player"
    assert "kills" in data
