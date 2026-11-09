"""Atomic import of official Olist CSV exports into an indexed SQLite database.

Source: https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce
Raw CSV is intentionally not redistributed in this repository.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import os
import sqlite3
from pathlib import Path

SCHEMA={
    'customers':('olist_customers_dataset.csv', ['customer_id','customer_unique_id','customer_zip_code_prefix','customer_city','customer_state']),
    'orders':('olist_orders_dataset.csv',['order_id','customer_id','order_status','order_purchase_timestamp','order_approved_at','order_delivered_carrier_date','order_delivered_customer_date','order_estimated_delivery_date']),
    'order_items':('olist_order_items_dataset.csv',['order_id','order_item_id','product_id','seller_id','shipping_limit_date','price','freight_value']),
    'sellers':('olist_sellers_dataset.csv',['seller_id','seller_zip_code_prefix','seller_city','seller_state']),
}

def sha256_file(path:Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(2**20),b''):h.update(chunk)
    return h.hexdigest()

def profile(con:sqlite3.Connection)->dict:
    counts={t:con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in SCHEMA}
    missing_customer=con.execute('''SELECT COUNT(*) FROM orders o LEFT JOIN customers c ON o.customer_id=c.customer_id
          WHERE c.customer_id IS NULL''').fetchone()[0]
    duplicate_orders=con.execute('SELECT COUNT(*)-COUNT(DISTINCT order_id) FROM orders').fetchone()[0]
    eligible=con.execute('''SELECT COUNT(*) FROM orders WHERE order_status='delivered'
       AND order_delivered_customer_date IS NOT NULL AND order_delivered_customer_date!=''
       AND order_estimated_delivery_date IS NOT NULL AND order_estimated_delivery_date!='' ''').fetchone()[0]
    no_purchase=con.execute("SELECT COUNT(*) FROM orders WHERE order_purchase_timestamp IS NULL OR order_purchase_timestamp='' ").fetchone()[0]
    period=con.execute('SELECT MIN(substr(order_purchase_timestamp,1,10)),MAX(substr(order_purchase_timestamp,1,10)) FROM orders').fetchone()
    return {'rows':counts,'eligible_delivered_orders':eligible,'duplicate_order_ids':duplicate_orders,
            'orders_missing_customer':missing_customer,'orders_missing_purchase_timestamp':no_purchase,
            'purchase_date_min':period[0],'purchase_date_max':period[1]}

def load(source:str|Path,dest:str|Path)->dict:
    source,dest=Path(source),Path(dest)
    hashes={}
    for fname,_ in SCHEMA.values():
        path=source/fname
        if not path.is_file():
            raise FileNotFoundError(f'Missing {path}; download official Olist archive from Kaggle')
        hashes[fname]=sha256_file(path)
    dest.parent.mkdir(parents=True,exist_ok=True)
    temp=dest.with_suffix(dest.suffix+'.importing')
    temp.unlink(missing_ok=True)
    con=sqlite3.connect(temp)
    try:
        for table,(fname,cols) in SCHEMA.items():
            con.execute(f'CREATE TABLE {table} ('+', '.join(f'"{col}" TEXT' for col in cols)+')')
            with (source/fname).open(encoding='utf-8-sig',newline='') as f:
                reader=csv.DictReader(f)
                if any(c not in (reader.fieldnames or []) for c in cols):
                    raise ValueError(f'Missing required columns in {fname}')
                sql=f'INSERT INTO {table} VALUES ('+','.join('?' for _ in cols)+')'
                batch=[]
                for row in reader:
                    batch.append(tuple(row[c] or None for c in cols))
                    if len(batch)>=5000:
                        con.executemany(sql,batch);batch=[]
                if batch:con.executemany(sql,batch)
        for table,col in [('orders','order_id'),('orders','customer_id'),('orders','order_purchase_timestamp'),
                          ('customers','customer_id'),('order_items','order_id'),('sellers','seller_id')]:
            con.execute(f'CREATE INDEX idx_{table}_{col} ON {table}({col})')
        con.commit()
        stats=profile(con)
        if stats['duplicate_order_ids']:
            raise ValueError('Orders must be unique at order_id grain')
        if stats['orders_missing_customer']:
            raise ValueError('Orders contain missing customer joins; cannot calculate regional KPI safely')
        if not stats['rows']['orders']:
            raise ValueError('Empty orders table')
        # Distinguishes public dataset from synthetic fixture; does NOT prove original authenticity.
        stats['source_sha256']=hashes
        con.close()
        temp.replace(dest)
        manifest=dest.with_suffix('.manifest.json')
        manifest.write_text(json.dumps(stats,indent=2),encoding='utf-8')
        return stats
    except Exception:
        con.close()
        temp.unlink(missing_ok=True)
        raise

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',default='data/raw');parser.add_argument('--dest',default='data/olist.db')
    a=parser.parse_args();print(json.dumps(load(a.source,a.dest),indent=2))
