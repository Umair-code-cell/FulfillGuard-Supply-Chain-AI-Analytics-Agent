.PHONY: setup test demo baseline audit ingest live-eval
setup:
	python -m pip install -r requirements.txt
test:
	python -m pytest -q
demo:
	python -m scripts.make_fixture
	FG_DB_PATH=data/demo.db uvicorn app.api:app --host 127.0.0.1 --port 8000
audit:
	FG_DB_PATH=data/olist.db python -m scripts.audit_data
baseline:
	FG_DB_PATH=data/demo.db python -m scripts.eval_baseline
ingest:
	python -m scripts.load_olist --source data/raw --dest data/olist.db
live-eval:
	FG_DB_PATH=data/olist.db python -m scripts.run_evals
