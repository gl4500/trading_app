"""Actual capture and publication path with injected wall clock; no snapshot/scorer stub."""
from pathlib import Path
from datetime import timedelta
import json
import pytest
import s1_common as c
import s1_checkpoint as ck
import s1_run as r
import s1_seal as z
from conftest import S1_RECEIPT,S1_PROCESS,_Clock,s1_state
START='2026-10-26T13:30:00+00:00'

def exercise(tmp_path,monkeypatch,offset_us):
    state=s1_state(tmp_path,START)
    with _Clock(state['prereg_at']):r.do_prereg(tmp_path,'run-ack',S1_RECEIPT)
    day=next(d for d in state['calendar'] if d['date']=='2026-10-26')
    sch=z.close_of(day['date'],state['calendar'])+timedelta(minutes=45)
    dl=z.resolution_deadline(sch,day,state['calendar']);clock=[sch+timedelta(seconds=30)]
    target=sch.strftime('%Y%m%dT%H%M%SZ')+'.resolution.json'
    real=c.publish_exclusive;links=[]
    def delayed(path,data):
        if Path(path).name==target:
            clock[0]=dl+timedelta(microseconds=offset_us)
            links.append(clock[0].isoformat())  # advance BEFORE publication, not merely after it
        return real(path,data)
    monkeypatch.setattr(c,'publish_exclusive',delayed)
    with _Clock(clock[0]):
        rep=ck.run_checkpoint(tmp_path,state['ledger'].path,sch,lambda:S1_RECEIPT,lambda:dict(S1_PROCESS),tmp_path/'crash.log',now=lambda:clock[0])
    result={'offset_microseconds':offset_us,'resolution_deadline':dl.isoformat(),'injected_publication_time':links,
            'resolution':rep.get('resolution'),'seal':rep.get('seal'),'capture_end':rep.get('capture_end'),
            'abort':c.load_abort(tmp_path/'s1_out')}
    Path(__file__).with_name(f'publication-offset-{offset_us}.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result

@pytest.mark.parametrize('offset_us',[-1,0,1])
def test_observe_actual_publication_deadline_behavior(tmp_path,monkeypatch,offset_us):
    result=exercise(tmp_path,monkeypatch,offset_us)
    assert result['seal']['written'] is True  # diagnostic records existing behavior, not a correctness pass
    if offset_us>=0:assert result['resolution']['publication_overrun'] is True

@pytest.mark.parametrize('offset_us',[0,1])
def test_required_durable_publication_at_or_after_deadline_must_not_seal(tmp_path,monkeypatch,offset_us):
    result=exercise(tmp_path,monkeypatch,offset_us)
    assert result['seal']['written'] is False, 'B1.3 requires actual durable success strictly before D'
