import json,shutil
from pathlib import Path
from datetime import timedelta
import pytest
import s1_common as c
import s1_run as r
from conftest import S1_RECEIPT,_Clock,s1_state
START='2026-10-26T13:30:00+00:00'

@pytest.mark.parametrize('auth_damage',['missing','unparseable'])
def test_bundle_change_plus_damaged_bootstrap_is_refusal_without_persistent_abort(tmp_path,monkeypatch,auth_damage):
    state=s1_state(tmp_path,START)
    with _Clock(state['prereg_at']):r.do_prereg(tmp_path,'run-ack',S1_RECEIPT)
    out=tmp_path/'s1_out';copy=tmp_path/'bundle-copy';copy.mkdir()
    for rel in (*c.BUNDLE_CODE,*c.DOC_PINS):
        target=copy/rel;target.parent.mkdir(exist_ok=True,parents=True);shutil.copyfile(c.HERE/rel,target)
    original=c.bundle_sha256();monkeypatch.setattr(c,'HERE',copy)
    assert c.bundle_sha256()==original
    code=copy/'s1_checkpoint.py';saved=code.read_bytes();code.write_bytes(saved+b'\n# synthetic observed bundle change\n')
    damaged=[out/'prereg.json',out/'audit/manifest.json'];saved_auth={p:p.read_bytes() for p in damaged}
    for p in damaged:
        assert p.resolve().is_relative_to(tmp_path.resolve())
        if auth_damage=='missing':p.unlink()
        else:p.write_text('{not JSON',encoding='utf-8')
    at=state['start']-timedelta(hours=1)
    with _Clock(at),pytest.raises(SystemExit) as error:c.verify_bundle_first(out,'Codex combined-damage probe',need='prereg')
    assert c.load_abort(out) is None
    for p,b in saved_auth.items():p.write_bytes(b)
    code.write_bytes(saved)
    with _Clock(at+timedelta(minutes=1)):reg=c.verify_bundle_first(out,'Codex restored probe',need='prereg')
    assert reg['stage']=='prereg' and c.load_abort(out) is None
    Path(__file__).with_name('bundle-bootstrap-'+auth_damage+'.json').write_text(json.dumps({'head':'c9b4322','bundle_original':original,'auth_damage':auth_damage,'artifacts':[str(p.relative_to(out)) for p in damaged],'refusal':str(error.value),'abort':c.load_abort(out),'restoration_resumes':True,'source_changed_only_in':'isolated bundle-copy; original source unchanged'},indent=2),encoding='utf-8')
