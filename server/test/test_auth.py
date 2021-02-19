from fastapi.testclient import TestClient

from main import app


client = TestClient(app)



def test_status():
    response = client.get("/auth/status")
    assert response.status_code == 200
    assert 'status' in response.json()


def test_profile():
    response = client.get("/auth/profile")
    assert response.status_code == 200
    assert 'disabled' in response.json() and not response.json()['disabled']


def test_api_key():
    response = client.get("/auth/key")
    assert response.status_code == 200
    assert len(response.json()['keys']) == 0


