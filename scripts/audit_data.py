"""Print row-grain, join integrity, and missingness audit for the configured DB."""
import json
from app.store import connect
from scripts.load_olist import profile

def audit():
    with connect() as con:return profile(con)

if __name__=='__main__':print(json.dumps(audit(),indent=2))
