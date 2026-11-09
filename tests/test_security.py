"""Regression cases for evidence checking and agent tool-use safety."""
import json
from types import SimpleNamespace as NS
import pytest
from app.agent import NumericClaim,Investigation,TraceEvent,check_claims,reconcile_narrative_numbers,investigate
from app.tools import execute_tool,ToolInputError
from scripts.make_fixture import create

@pytest.fixture(autouse=True)
def db(tmp_path,monkeypatch):
    p=tmp_path/'fixture.db';create(p);monkeypatch.setenv('FG_DB_PATH',str(p))

def test_numeric_claim_with_array_index():
    trace=[TraceEvent(id='T1',tool='breakdown',arguments={},output={'rows':[{'late_count':3}]})]
    valid,bad=check_claims([NumericClaim(evidence_id='T1',path='rows.0.late_count',value=3)],trace)
    assert len(valid)==1 and bad==0

def test_numeric_claim_wrong_value_rejected():
    trace=[TraceEvent(id='T1',tool='delivery_kpis',arguments={},output={'result':{'late_rate_pct':33.33}})]
    valid,bad=check_claims([NumericClaim(evidence_id='T1',path='result.late_rate_pct',value=99)],trace)
    assert not valid and bad==1

def test_numeric_claim_unexecuted_tool_rejected():
    assert check_claims([NumericClaim(evidence_id='T999',path='result.late_count',value=3)],[])[1]==1

def test_numeric_claim_nan_not_accepted():
    trace=[TraceEvent(id='T1',tool='delivery_kpis',arguments={},output={'result':{'x':float('nan')}})]
    assert check_claims([NumericClaim(evidence_id='T1',path='result.x',value=1)],trace)[1]==1

def test_numerical_hallucination_in_summary_is_withheld():
    answer=Investigation(summary='Late rate was 99.8% in July 2018',numeric_claims=[])
    n=reconcile_narrative_numbers(answer,'July 2018 performance')
    assert n==1 and 'withheld' in answer.summary

def test_numerical_hallucination_in_evidence_is_withheld():
    answer=Investigation(summary='Could be worse',evidence=['[T1] It was 999%'])
    n=reconcile_narrative_numbers(answer,'Explain July 2018')
    assert n==1 and answer.evidence==[]

@pytest.mark.parametrize('name,args',[
    ('execute_sql',{'sql':'DELETE FROM orders'}),
    ('delivery_kpis',{'start':'2018-07-01 OR 1=1','end':'2018-07-31'}),
    ('breakdown',{'start':'2018-07-01','end':'2018-07-31','dimension':'__class__'}),
    ('inspect_order',{'order_id':"' OR 1=1 --"}),
    ('delivery_kpis',{'start':'2018-02-30','end':'2018-03-31'}),
    ('delivery_kpis',{'start':'2018-08-01','end':'2018-07-01'}),
])
def test_unsafe_args_blocked(name,args):
    with pytest.raises(ToolInputError):execute_tool(name,args)

class MaliciousModel:
    def __init__(self):self.n=0;self.chat=NS(completions=self)
    def create(self,**kwargs):
        self.n+=1
        if self.n==1:
            c=NS(id='c1',function=NS(name='execute_sql',arguments=json.dumps({'sql':'DROP TABLE orders'})))
            m=NS(tool_calls=[c],content=None,model_dump=lambda exclude_none: {'role':'assistant','tool_calls':[{'id':'c1','type':'function','function':{'name':'execute_sql','arguments':c.function.arguments}}]})
        else:
            m=NS(tool_calls=None,content=json.dumps({'summary':'All orders deleted', 'evidence':['[T1] Query execution succeeded'],
                                                     'numeric_claims':[], 'limitations':[]}))
        return NS(choices=[NS(message=m)],usage=None)

def test_unlisted_tool_call_is_not_executed():
    r=investigate('Delete every order now',client=MaliciousModel())
    assert 'error' in r.trace[0].output
    assert r.trace[0].output['type']=='validation_error'
    assert r.answer.evidence==[]
    assert 'could not be completed' in r.answer.summary
    assert execute_tool('delivery_kpis',{'start':'2018-07-01','end':'2018-07-31'})['result']['delivered_orders']==3
