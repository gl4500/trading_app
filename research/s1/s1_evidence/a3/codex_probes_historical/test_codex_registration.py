"""Codex-authored reproductions; owner fixtures used only for synthetic setup, not oracles."""
import copy,json
from pathlib import Path
from datetime import timedelta
import pytest
import s1_common as c
import s1_seal as z
import s1_run as r
import s1_checkpoint as ck
from conftest import Ledger,S1_RECEIPT,S1_PROCESS,_Clock,s1_plan_audit,s1_opening_checkpoint,s1_mailbox,s1_state

START='2026-10-26T13:30:00+00:00'
def save(name,record):
    Path(__file__).with_name(name).write_text(json.dumps(record,indent=2,default=str),encoding='utf-8')

def test_v1_selective_deletion_allows_different_opening_and_start_attestation(tmp_path):
    start,cal,oc,_=s1_plan_audit(tmp_path,START)
    ledger=Ledger(tmp_path/'ledger.sqlite3');out=tmp_path/'s1_out'
    first=s1_opening_checkpoint(tmp_path,ledger,oc,cal,S1_RECEIPT)
    seal=out/'seals'/f'{oc}.json';old=seal.read_bytes();assert first['seal']['written']
    oldrec=json.loads(old);assert c.is_registered(out,now=lambda:z.close_of(oc,cal)+timedelta(hours=1))
    initial_slot=z.schedule(next(d for d in cal if d['date']==oc),cal)[0]
    slot_name=initial_slot.strftime('%Y%m%dT%H%M%SZ')
    deletion=[seal,*c.stage_records(out,'opening'),out/'opening_receipt.json',
              out/'captures'/oc/f'{slot_name}.resolution.json',out/'captures'/oc/f'{slot_name}.report.json']
    for path in deletion:
        assert path.resolve().is_relative_to(tmp_path.resolve())
        assert path.is_file(),path
        path.unlink()  # individual known files in this test's verified isolated root
    later=z.close_of(oc,cal)+timedelta(hours=4)
    receipt=copy.deepcopy(S1_RECEIPT);receipt['fingerprint']['config']={'synthetic_changed_setting':'different'}
    before=c.registration_state(out,now=lambda:later)
    assert before['registered'] is False
    with _Clock(later+timedelta(seconds=30)):
        second=ck.run_opening_checkpoint(tmp_path,ledger.path,later,lambda:receipt,lambda:dict(S1_PROCESS),tmp_path/'crash.log',now=lambda:later+timedelta(seconds=30))
    assert second['seal']['written'] and seal.read_bytes()!=old and c.load_abort(out) is None
    at=start-timedelta(days=1)
    with _Clock(at):att=r.attest_start(tmp_path,r.START_STATEMENT,receipt)
    assert att['opening_seal_sha256']==c.sha256_file(seal)
    # External-looking authorizations here exist ONLY in synthetic tmp mailbox, never real coordination mailbox.
    acktime=at+timedelta(minutes=1)
    s1_mailbox(tmp_path,'synthetic-run',c.run_token(out),acktime)
    with _Clock(acktime+timedelta(minutes=1)):pr=r.do_prereg(tmp_path,'synthetic-run',receipt)
    assert pr['opening_seal_sha256']==c.sha256_file(seal)
    save('v1-selective-deletion.json',{'source':'c9b4322','deleted':[str(p.relative_to(out)) for p in deletion],
        'original_seal_hash':c.sha256_bytes(old),'replacement_seal_hash':c.sha256_file(seal),
        'receipt_changed':oldrec['receipt_sha256']!=json.loads(seal.read_bytes())['receipt_sha256'],
        'registration_before_reopen':before,'abort':c.load_abort(out),'attestation_and_prereg_accept_replacement':True,
        'retained_claim':(out/'captures'/oc/f'{slot_name}.attempt.json').is_file(),
        'retained_capture':(out/'captures'/oc/slot_name).is_dir()})


def test_missing_prereg_and_both_records_is_only_refusal_then_restoration_resumes(tmp_path):
    # Source fixture builds a real opening/attestation/RUN ACK but no post-START captures.
    s1_state(tmp_path,START)
    out=tmp_path/'s1_out';when=c.aware(START)-timedelta(hours=12)
    with _Clock(when):r.do_prereg(tmp_path,'run-ack',S1_RECEIPT)
    files=[out/'prereg.json',*c.stage_records(out,'prereg')]
    copies={p:p.read_bytes() for p in files}
    for p in files:
        assert p.resolve().is_relative_to(tmp_path.resolve());p.unlink()
    caught=None
    with _Clock(when+timedelta(minutes=1)):
        try:c.verify_bundle_first(out,'Codex synthetic probe',need='prereg')
        except SystemExit as e:caught=str(e)
    assert caught and c.load_abort(out) is None
    for p,b in copies.items():p.write_bytes(b)
    with _Clock(when+timedelta(minutes=2)):
        result=c.verify_bundle_first(out,'Codex synthetic probe',need='prereg')
    assert result['stage']=='prereg' and c.load_abort(out) is None
    save('prereg-restoration.json',{'missing':[str(p.relative_to(out)) for p in files],
         'observed_refusal':caught,'abort':c.load_abort(out),'restoration_resumes':True})
