import csv
import sqlite3
from pathlib import Path
import pytest
from scripts.make_fixture import create
from scripts.load_olist import SCHEMA,load,profile

@pytest.fixture
def raw(tmp_path):
    source=tmp_path/'raw';source.mkdir()
    rows={
       'customers':[['a','u','1000','city','SP']],
       'orders':[['f'*32,'a','delivered','2018-07-01','','','2018-07-09','2018-07-08']],
       'order_items':[['f'*32,'1','p','s','','20','5']],
       'sellers':[['s','2000','city','SP']],
    }
    for t,(filename,fields) in SCHEMA.items():
        with (source/filename).open('w',newline='') as f:
            w=csv.writer(f);w.writerow(fields);w.writerows(rows[t])
    return source

def test_import_writes_manifest(raw,tmp_path):
    db=tmp_path/'loaded.db'
    stats=load(raw,db)
    assert stats['rows']['orders']==1
    assert len(stats['source_sha256'])==4
    assert db.exists() and (tmp_path/'loaded.manifest.json').exists()
    with sqlite3.connect(db) as conn:
        assert profile(conn)['eligible_delivered_orders']==1

def test_atomicity_preserves_existing_database_on_failure(raw,tmp_path):
    db=tmp_path/'existing.db';create(db)
    original=db.read_bytes()
    with (raw/'olist_orders_dataset.csv').open('a') as f:
        f.write('f'*32+',a,delivered,2018-07-01,,,,2018-07-09,2018-07-08\n')
    with pytest.raises(ValueError,match='unique'):
        load(raw,db)
    assert db.read_bytes()==original
    assert not (tmp_path/'existing.db.importing').exists()

def test_missing_csv_fails_before_mutating_database(raw,tmp_path):
    db=tmp_path/'existing.db';create(db)
    original=db.read_bytes()
    (raw/'olist_sellers_dataset.csv').unlink()
    with pytest.raises(FileNotFoundError):load(raw,db)
    assert db.read_bytes()==original

def test_missing_required_col_detected(raw,tmp_path):
    with (raw/'olist_customers_dataset.csv').open('w') as f:
        f.write('not_customer_id\ninvalid\n')
    with pytest.raises(ValueError,match='Missing required columns'):
        load(raw,tmp_path/'bad.db')
    assert not (tmp_path/'bad.db').exists()
