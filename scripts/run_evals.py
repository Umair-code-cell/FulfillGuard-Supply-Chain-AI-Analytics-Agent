"""Live LLM evaluation of tool use, evidence integrity, safety, and operational behavior.

This is NOT a claim of semantic/factual answer correctness. Independent human/SQL
review remains necessary for complex explanations and all causal conclusions.
"""
from __future__ import annotations
import argparse
import json
import os
from datetime import datetime,timezone
from pathlib import Path
from app.agent import investigate
from app.store import connect
import time
import re

def run(cases_path='eval/cases.json',out='eval/live_report.json'):
    if not os.getenv("GROQ_API_KEY"):
        raise RuntimeError("GROQ_API_KEY required. Live evaluation was NOT performed.")
    cases=json.loads(Path(cases_path).read_text(encoding='utf-8'))
    with connect() as con:
        row_count=con.execute('SELECT COUNT(*) FROM orders').fetchone()[0]
    results=[]
    for index, case in enumerate(cases):
        print(f"Running {index + 1}/{len(cases)}: {case['id']}", flush=True)
        try:
            response=investigate(case['question'])
            used=[t.tool for t in response.trace]
            expected=case['expected_tools']
            valid_ids = {
                t.id for t in response.trace
                if "error" not in t.output
            }

            # Check whether the correct tools were selected.

            acceptable_routes = case.get("acceptable_routes")

            if acceptable_routes is not None:
                route_hit = any(
                    sorted(used) == sorted(route)
                    for route in acceptable_routes
                )
            else:
                route_hit = (
                    all(name in used for name in expected)
                    if expected else not used
                )

            # Extract evidence IDs from each evidence line.
            cited_ids = [
                set(re.findall(r"\[(T\d+)\]", line))
                for line in response.answer.evidence
            ]

            if not response.trace:
                # Refusals must not invent evidence.
                evidence_valid = (
                    not response.answer.evidence
                    and not response.answer.numeric_claims
                )
            else:
                # Every evidence reference must match a successful tool.
                evidence_valid = (
                    bool(valid_ids)
                    and bool(cited_ids)
                    and all(
                        ids and ids.issubset(valid_ids)
                        for ids in cited_ids
                    )
                    and all(
                        claim.evidence_id in valid_ids
                        for claim in response.answer.numeric_claims
                    )
                )

            unsafe_attempts=sum(1 for t in response.trace if t.tool not in
                                {'delivery_kpis','compare_periods','breakdown','inspect_order','schema_info'})
            result={'id':case['id'],'category':case['category'],'expected_tools':expected,
               'used_tools':used,'expected_tool_coverage':route_hit,
               'evidence_links_valid':evidence_valid,'unlisted_tool_attempts':unsafe_attempts,
               'numerical_claims_verified':response.numeric_claims_verified,
               'numerical_claims_rejected':response.numeric_claims_rejected,
               'narrative_numeric_fields_withheld':response.narrative_numeric_issues,
               'elapsed_ms':response.elapsed_ms,'tokens_in':response.tokens_in,'tokens_out':response.tokens_out,
               'model':response.model,'summary':response.answer.summary,'error':None}
        except Exception as exc:
            result={'id':case['id'],'category':case['category'],'expected_tools':case['expected_tools'],
              'error':str(exc),'expected_tool_coverage':False,'evidence_links_valid':False}
        results.append(result)
        print(f"Completed: {case['id']}", flush=True)
        if index < len(cases) - 1:
            time.sleep(30)
    good=[r for r in results if not r.get('error')]
    report={'run_utc':datetime.now(timezone.utc).isoformat(),'data_rows':row_count,
      'dataset_type':'fixture_or_small_sample' if row_count<10000 else 'large_dataset_source_must_be_verified',
      'case_count':len(results),'completed_without_exception':len(good),
      'tool_coverage_rate_all_cases':round(sum(r.get('expected_tool_coverage',False) for r in results)/len(results),3) if results else None,
      'evidence_reference_validity_rate':round(sum(r.get('evidence_links_valid',False) for r in results)/len(results),3) if results else None,
      'total_reported_input_tokens':sum(r.get('tokens_in',0) or 0 for r in results),
      'total_reported_output_tokens':sum(r.get('tokens_out',0) or 0 for r in results),
      'notes':'Tool coverage is NOT answer accuracy; model explanations and causal statements still need independent review.',
      'cases':results}
    path=Path(out);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='cases'},indent=2))
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--cases',default='eval/cases.json')
    p.add_argument('--output',default='eval/live_report.json');args=p.parse_args()
    run(args.cases,args.output)
