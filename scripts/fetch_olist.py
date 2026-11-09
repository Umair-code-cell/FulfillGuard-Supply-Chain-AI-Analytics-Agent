"""Optional Kaggle public dataset download and import helper.

Requires optional dependency: pip install kagglehub
If Kaggle's current authentication rules require login, download ZIP manually.
"""
import argparse
from pathlib import Path
from scripts.load_olist import load

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dest',default='data/olist.db');a=parser.parse_args()
    try:import kagglehub
    except ImportError as exc:raise SystemExit('Install optional dependency: pip install kagglehub') from exc
    location=Path(kagglehub.dataset_download('olistbr/brazilian-ecommerce'))
    print(f'Kaggle download location: {location}')
    stats=load(location,a.dest)
    print(f'Imported {stats["rows"]["orders"]} records; audit saved beside the DB')

if __name__=='__main__':main()
