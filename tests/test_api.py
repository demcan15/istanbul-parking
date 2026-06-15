from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from app.main import app

client = TestClient(app)

def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"

@patch("app.main.get_db")
@patch("app.main.r")
def test_get_spots(mock_redis, mock_db):
    # Redis cache boş dönsün
    mock_redis.get.return_value = None
    mock_redis.setex.return_value = True

    # DB mock
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = [
        (1, 41.042, 29.008, "Beşiktaş", True, 0.75)
    ]
    mock_conn.cursor.return_value = mock_cur
    mock_db.return_value = mock_conn

    response = client.get("/api/spots?lat=41.042&lng=29.008")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["district"] == "Beşiktaş"

@patch("app.main.get_db")
def test_submit_report(mock_db):
    mock_conn = MagicMock()
    mock_db.return_value = mock_conn

    response = client.post("/api/reports", json={
        "spot_id": 1,
        "user_id": "test_user",
        "is_available": True,
        "lat": 41.042,
        "lng": 29.008
    })
    assert response.status_code == 200
    assert response.json()["status"] == "ok"