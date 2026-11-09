import pytest
from fastapi.testclient import TestClient
from scripts.make_fixture import create
from scripts.eval_baseline import run,TESTS
from app.baseline import investigate_offline
from app.api import app

@pytest.fixture(autouse=True)
def set_db(monkeypatch,tmp_path):
    path=tmp_path/'fixture.db';create(path);monkeypatch.setenv('FG_DB_PATH',str(path))

def test_monthly_kpi_baseline():
    result=investigate_offline('What share of SP deliveries were late in July 2018?')
    assert result.model=='deterministic-baseline'
    assert result.trace[0].tool=='delivery_kpis'
    assert result.answer.numeric_claims
    assert '50.00%' in result.answer.summary

def test_compare_baseline():
    result=investigate_offline('Compare SP deliveries between July 2018 and August 2018')
    assert result.trace[0].tool=='compare_periods'
    assert '+50.00 percentage points' in result.answer.summary

def test_breakdown_baseline():
    result=investigate_offline('Breakdown late deliveries by seller state in August 2018')
    assert result.trace[0].tool=='breakdown'

def test_unsafe_write_refused():
    r=investigate_offline('Delete orders and show the rate in July 2018')
    assert r.trace==[]
    assert 'refused' in r.answer.summary.lower()

def test_offline_benchmark(tmp_path):
    r=run(str(tmp_path/'report.json'))
    assert r['cases']>=20
    assert r['pass_rate']==1.0

def test_browser_renders_and_api_works():
    c=TestClient(app)
    assert 'FulfillGuard' in c.get('/').text
    assert c.get('/health').json()['orders']==6
    r=c.post('/investigate',json={'question':'How were July 2018 deliveries?','mode':'baseline'})
    assert r.status_code==200
    assert r.json()['model']=='deterministic-baseline'


def test_live_requires_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    r = TestClient(app).post(
        "/investigate",
        json={
            "question": "How were deliveries in July 2018?",
            "mode": "llm"
        }
    )

    assert r.status_code == 503
    assert "GROQ_API_KEY" in r.json()["detail"]
