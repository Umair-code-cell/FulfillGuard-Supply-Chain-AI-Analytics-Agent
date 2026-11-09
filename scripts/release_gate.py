"""Strict local live-model quality gate; separate from publishing source code."""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

def assess():
    issues=[]
    manifest=Path('data/olist.manifest.json')
    if not manifest.exists():issues.append('Official Olist CSVs have not been imported and audited.')
    else:
        data=json.loads(manifest.read_text())
        if data['rows']['orders']<90000:issues.append('Real-data order count below expected Olist scale; confirm source.')
        if data['duplicate_order_ids'] or data['orders_missing_customer']:
            issues.append('Ingestion integrity checks failed.')
        if not data.get('source_sha256'):issues.append('No data-source hashes recorded.')
    eval_file=Path('eval/live_report.json')
    if not eval_file.exists():issues.append('No provider-backed LLM evaluation report found.')
    else:
        ev=json.loads(eval_file.read_text())
        if ev.get('case_count',0)<28:issues.append('Fewer than 28 live cases evaluated.')
        if ev.get('completed_without_exception',0)!=ev.get('case_count',0):
            issues.append('At least one LLM evaluation errored; inspect failure.')
        if ev.get('dataset_type')!='large_dataset_source_must_be_verified':
            issues.append('LLM evaluation did not run against a large dataset.')
        if ev.get('tool_coverage_rate_all_cases',0)<.8:
            issues.append('LLM tool-route coverage below 80%; fix before publication.')
        if ev.get('evidence_reference_validity_rate',0)<1:
            issues.append('One or more cases have invalid evidence references.')
    return issues

if __name__=='__main__':
    issues=assess()
    if issues:
        print('RELEASE GATE: NOT CLEARED\n'+'\n'.join(f'- {x}' for x in issues))
        sys.exit(1)
    print('Automated gate cleared. Manual report review, deployment validation and truthful resume claims still required.')
