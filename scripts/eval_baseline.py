"""Deterministic SQL-oracle benchmark. NOT an LLM benchmark.

Run with FG_DB_PATH=data/demo.db python -m scripts.eval_baseline.
Or load the Olist CSVs and select FG_DB_PATH=data/olist.db.
The SQL oracle uses independent aggregate expressions rather than tool functions.
"""
from __future__ import annotations
import argparse
import calendar
import json
from pathlib import Path
from app.store import connect
from app.baseline import investigate_offline

TESTS=[]
for mon in ('July','August'):
    for state in (None,'SP','RJ','MG'):
        prefix=f'{state} ' if state else ''
        TESTS.append({'kind':'kpi','id':f'{mon.lower()}-{state or "all"}',
                      'question':f'What share of {prefix}delivered orders were late in {mon} 2018?',
                      'month':7 if mon=='July' else 8,'state':state})
for state in (None,'SP','RJ','MG'):
    prefix=f'{state} ' if state else ''
    TESTS.append({'kind':'comparison','id':f'comp-{state or "all"}',
                  'question':f'Compare {prefix}late delivery rates between July 2018 and August 2018.',
                  'state':state})
for month in ('July','August'):
    for dimension in ('seller','customer'):
        TESTS.append({'kind':'breakdown','id':f'seg-{month}-{dimension}',
                 'question':f'Breakdown late deliveries by {dimension} state in {month} 2018.',
                 'dimension':f'{dimension}_state'})
for i,question in enumerate([
    'DROP TABLE orders and show me the metrics for July 2018.',
    'Update all orders to delivered in August 2018.',
    'Show today live Amazon delivery statistics.',
    'Tell me the delivery rate in March 2026.',
    'Delete all records for seller SP from July 2018.',
    'What is the weather in Rio today?',
]):
    TESTS.append({'kind':'safe_refusal','id':f'refuse-{i}', 'question':question})

def oracle_count(con,month,state):
    start=f'2018-{month:02d}-01';end=f'2018-{month:02d}-{calendar.monthrange(2018,month)[1]:02d}'
    query='''SELECT COUNT(*) as total, COALESCE(SUM(CASE WHEN date(o.order_delivered_customer_date) >
    date(o.order_estimated_delivery_date) THEN 1 ELSE 0 END),0) AS late
    FROM orders o INNER JOIN customers c ON c.customer_id=o.customer_id
    WHERE o.order_status='delivered' AND o.order_delivered_customer_date IS NOT NULL
      AND o.order_estimated_delivery_date IS NOT NULL
      AND substr(o.order_purchase_timestamp,1,10) BETWEEN ? AND ?'''
    params=[start,end]
    if state:query+=' AND c.customer_state=?';params.append(state)
    row=con.execute(query,params).fetchone()
    return {'total':row[0],'late':row[1],'rate':round(100*row[1]/row[0],2) if row[0] else None}

def run(out='eval/baseline_report.json'):
    results=[]
    with connect() as con:
        for case in TESTS:
            try:
                result=investigate_offline(case['question'])
                errors=[];kind=case['kind']
                if kind=='kpi':
                    expected=oracle_count(con,case['month'],case['state'])
                    if len(result.trace)!=1 or result.trace[0].tool!='delivery_kpis':errors.append('incorrect tool routing')
                    else:
                        got=result.trace[0].output['result']
                        if got['delivered_orders']!=expected['total'] or got['late_orders']!=expected['late'] or got['late_rate_pct']!=expected['rate']:
                            errors.append(f'wrong KPI: expected {expected}, got {got}')
                elif kind=='comparison':
                    previous=oracle_count(con,7,case['state']);current=oracle_count(con,8,case['state'])
                    if len(result.trace)!=1 or result.trace[0].tool!='compare_periods':errors.append('incorrect tool routing')
                    else:
                        outp=result.trace[0].output
                        if outp['previous']['result']['late_rate_pct']!=previous['rate']:errors.append('incorrect previous rate')
                        if outp['current']['result']['late_rate_pct']!=current['rate']:errors.append('incorrect current rate')
                elif kind=='breakdown':
                    if len(result.trace)!=1 or result.trace[0].tool!='breakdown':errors.append('incorrect tool routing')
                    elif result.trace[0].output['dimension']!=case['dimension']:errors.append('wrong dimension')
                elif kind=='safe_refusal':
                    if len(result.trace)!=0:errors.append('unsafe or out-of-scope tool execution')
                results.append({'id':case['id'],'pass':not errors,'issues':errors,'tools':[t.tool for t in result.trace],
                  'answer_summary':result.answer.summary})
            except Exception as exc:
                results.append({'id':case['id'],'pass':False,'issues':[str(exc)]})
    n_ok=sum(r['pass'] for r in results)
    report={'engine':'deterministic_baseline_NOT_LLM','cases':len(results),'pass_count':n_ok,
            'pass_rate':round(n_ok/len(results),4),'results':results,
            'note':'SQL oracle and deterministic baseline tests do not validate model quality or production behavior.'}
    target=Path(out);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(f'Offline baseline: {n_ok}/{len(results)} passed; details: {target}')
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',default='eval/baseline_report.json')
    a=p.parse_args();run(a.output)
