import os
import pytest
from pathlib import Path
from scripts.make_fixture import create
from app.tools import delivery_kpis, compare_periods, breakdown, execute_tool, ToolInputError

@pytest.fixture(autouse=True)
def fixture_db(tmp_path,monkeypatch):
    p=tmp_path/'demo.db';create(p);monkeypatch.setenv('FG_DB_PATH',str(p))

def test_july_cohort():
    d=delivery_kpis('2018-07-01','2018-07-31')
    assert d['result']['delivered_orders']==3
    assert d['result']['late_orders']==1
    assert d['result']['late_rate_pct']==33.33

def test_sp_cohorts():
    d=compare_periods('2018-08-01','2018-08-31','2018-07-01','2018-07-31','SP')
    assert d['current']['result']['late_rate_pct']==100.0
    assert d['previous']['result']['late_rate_pct']==50.0
    assert d['late_rate_delta_pp']==50.0

def test_breakdown():
    d=breakdown('2018-07-01','2018-08-31','customer_state')
    assert d['rows'][0]['segment']=='SP'
    assert d['rows'][0]['late_count']==2

def test_read_only_protections():
    with pytest.raises(ToolInputError):
        execute_tool('execute_sql', {'sql':'DROP TABLE orders'})
    with pytest.raises(ToolInputError):
        breakdown('2018-07-01','2018-08-31',"customer_state; DROP TABLE orders")
    with pytest.raises(ToolInputError):
        delivery_kpis('2018-07-01\' OR 1=1 --','2018-08-31')

def test_missing_data_handling():
    assert delivery_kpis('2017-01-01','2017-01-31')['result']['late_rate_pct'] is None


def test_invalid_brazilian_state():
    from app.tools import _state, ToolInputError

    assert _state("SP") == "SP"
    assert _state("RJ") == "RJ"
    assert _state(None) is None

    with pytest.raises(ToolInputError, match="Unknown Brazilian state"):
        _state("XX")
