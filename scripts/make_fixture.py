"""Small deterministic sample solely for tests/smoke checks (NOT real Olist data)."""
from __future__ import annotations
import csv
from pathlib import Path
from tempfile import TemporaryDirectory
from .load_olist import SCHEMA,load


def create(dest: str | Path):
    with TemporaryDirectory() as d:
        root=Path(d)
        rows={
        'customers':[
            ['c1','u1','10000','sao paulo','SP'],['c2','u2','10000','sao paulo','SP'],
            ['c3','u3','20000','rio','RJ'],['c4','u4','10000','sao paulo','SP'],
            ['c5','u5','20000','rio','RJ'],['c6','u6','10000','sao paulo','SP']],
        'orders':[
            ['a'*32,'c1','delivered','2018-07-10 12:00:00','','','2018-07-15 14:00:00','2018-07-19 12:00:00'],
            ['b'*32,'c2','delivered','2018-07-12 12:00:00','','','2018-07-20 14:00:00','2018-07-19 12:00:00'],
            ['c'*32,'c3','delivered','2018-07-13 12:00:00','','','2018-07-15 14:00:00','2018-07-19 12:00:00'],
            ['d'*32,'c4','delivered','2018-08-10 12:00:00','','','2018-08-20 14:00:00','2018-08-18 12:00:00'],
            ['e'*32,'c5','delivered','2018-08-11 12:00:00','','','2018-08-13 14:00:00','2018-08-18 12:00:00'],
            ['f'*32,'c6','shipped','2018-08-12 12:00:00','','','','2018-08-18 12:00:00']],
        'order_items':[[ch*32,'1','p1','s1','','10','5'] for ch in 'abcde'],
        'sellers':[['s1','10000','sao paulo','SP']]}
        for name,(filename,cols) in SCHEMA.items():
            with (root/filename).open('w',newline='') as f:
                writer=csv.writer(f);writer.writerow(cols);writer.writerows(rows[name])
        load(root,dest)

if __name__=='__main__':
    create('data/demo.db')
