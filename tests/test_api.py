from fastapi.testclient import TestClient
from app.api import app

def test_health(monkeypatch,tmp_path):
    monkeypatch.setenv('FG_DB_PATH',str(tmp_path/'absent.db'))
    resp=TestClient(app).get('/health')
    assert resp.status_code==200
    assert resp.json()['dataset_ready'] is False

def test_validation():
    assert TestClient(app).post('/investigate',json={'question':'x'}).status_code==422
