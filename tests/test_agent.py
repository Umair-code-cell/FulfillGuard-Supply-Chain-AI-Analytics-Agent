import json
from types import SimpleNamespace as NS
from scripts.make_fixture import create
from app.agent import investigate

class FakeLLM:
    def __init__(self): self.n=0; self.chat=NS(completions=self)
    def create(self,**kwargs):
        self.n+=1
        if self.n==1:
            tool=NS(id='call_1',function=NS(name='delivery_kpis',arguments=json.dumps({'start':'2018-07-01','end':'2018-07-31'})))
            msg=NS(tool_calls=[tool],content=None,model_dump=lambda exclude_none: {'role':'assistant','tool_calls':[{'id':'call_1','type':'function','function':{'name':'delivery_kpis','arguments':tool.function.arguments}}]})
        else:
            content=json.dumps({'summary':'July late deliveries were 33.33%.','evidence':['[T1] Verified late-delivery KPI returned by the SQL tool'],
                                'possible_explanations':[],'next_checks':['Compare August'], 'limitations':['Cannot infer cause'],
                                'numeric_claims':[{'evidence_id':'T1','path':'result.late_rate_pct','value':33.33},
                                                  {'evidence_id':'T1','path':'result.late_rate_pct','value':99.9}]})
            msg=NS(tool_calls=None,content=content)
        return NS(choices=[NS(message=msg)],usage=NS(prompt_tokens=20,completion_tokens=30))

def test_agent_tool_trace(tmp_path,monkeypatch):
    p=tmp_path/'demo.db';create(p);monkeypatch.setenv('FG_DB_PATH',str(p))
    result=investigate('How were deliveries in July?',client=FakeLLM())
    assert result.trace[0].tool=='delivery_kpis'
    assert result.trace[0].output['result']['late_orders']==1
    assert result.answer.evidence[0].startswith('[T1]')
    assert result.tokens_in==40
    assert result.numeric_claims_verified==1
    assert result.numeric_claims_rejected==1
    assert result.answer.numeric_claims[0].value==33.33

def test_plain_text_refusal_without_tools():
    from types import SimpleNamespace as NS

    class RefusalLLM:
        def __init__(self):
            self.calls = 0
            self.chat = NS(completions=self)

        def create(self, **kwargs):
            self.calls += 1
            return NS(
                choices=[
                    NS(message=NS(
                        tool_calls=None,
                        content="I'm sorry, but I can't help with that."
                    ))
                ],
                usage=None,
            )

    client = RefusalLLM()

    result = investigate(
        "Mark all late orders as delivered today.",
        client=client,
    )

    assert client.calls == 1
    assert result.trace == []
    assert result.answer.numeric_claims == []
    assert "No data were changed" in result.answer.summary

import pytest
from types import SimpleNamespace as NS


@pytest.mark.parametrize(
    "question, expected",
    [
        (
            "Mark all late orders as delivered today.",
            "No data were changed",
        ),
        (
            "Show me customer emails and full street addresses.",
            "cannot provide private",
        ),
        (
            "Did delivery performance improve in Q3?",
            "Which year",
        ),
    ],
)
def test_no_tool_fallback_messages(question, expected):
    from app.agent import investigate

    class PlainTextLLM:
        def __init__(self):
            self.chat = NS(completions=self)

        def create(self, **kwargs):
            return NS(
                choices=[
                    NS(
                        message=NS(
                            tool_calls=None,
                            content="I cannot complete that request.",
                        )
                    )
                ],
                usage=None,
            )

    result = investigate(question, client=PlainTextLLM())

    assert expected.lower() in result.answer.summary.lower()
    assert result.trace == []
    assert result.answer.numeric_claims == []
