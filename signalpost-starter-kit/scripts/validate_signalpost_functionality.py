#!/usr/bin/env python3
"""Independent public-requirements acceptance, using real processes and JSON/HTTP.

No production test helpers or live acquisition. --real-data reuses a preserved
canonical result; controlled snapshots are explicitly fictional scenarios.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.parse import urlencode
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[2]
LAUNCHER=ROOT/"signalpost-starter-kit/run_signalpost.py"
SECTIONS={"identity_brand","accounts_history","leadership_workplaces","website_owned_profiles",
          "hiring_activity","claims_evidence_states","refresh_changes"}
STATES={"available","not_available","blocked","not_applicable","ambiguous","failed"}

def inspect_rows(path,expected):
    rows=[json.loads(line) for line in path.read_text().splitlines()]
    assert len(rows)==len(expected),(path,len(rows),len(expected))
    assert [r["organisation_number"] for r in rows]==expected
    assert len({r["input_ref"] for r in rows})==len(rows)
    for row in rows:
        assert row["terminal_state"] in STATES
        assert set(row["sections"])==SECTIONS
        ev={e["evidence_id"]:e for e in row["evidence"]}
        snaps={s["source_id"]:s for s in row["source_snapshots"]}
        for claim in row["claims"]:
            assert claim["organisation_number"]==row["organisation_number"]
            assert claim["evidence_ids"] and claim["source_snapshot_ids"]
            for ref in claim["evidence_ids"]:
                e=ev[ref]
                assert e["subject_organisation_number"]==row["organisation_number"]
                assert e["source_url"] and e["retrieved_at"] and len(e["content_sha256"])==64
                assert e["json_pointer"] or e.get("excerpt")
                for sid in e["source_snapshot_ids"]:
                    snap=snaps[sid]
                    assert e["source_url"]==snap["source_url"]
            if claim["field_family"]=="financial":
                assert claim["unit"] and claim["currency"] and claim["period_start"] and claim["period_end"]
        ids={c["claim_id"] for c in row["claims"]}
        for sentence in row["synthesis"]["summary"]["sentences"]:
            assert all(ref in ids for ref in sentence.get("fact_ids",[]))
            assert sentence.get("evidence_ids") or sentence.get("change_ids")
    return rows

def run_fault_cases(base, source_responses=None):
    """Keep the real CLI/gateway/parser; replace only HTTP and DNS with controlled fixtures."""
    hook=base/"fault-hook";hook.mkdir(exist_ok=True)
    (hook/"sitecustomize.py").write_text(FAULT_HOOK)
    outcomes={}
    for mode,expected in [("not_found","not_available"),("refused","blocked"),("timeout","failed"),("partial","available")]:
        folder=base/("source_"+mode);folder.mkdir(exist_ok=True)
        (folder/"input.txt").write_text("923609016\n")
        env={**os.environ,"PYTHONPATH":str(hook)+os.pathsep+str(ROOT),"SIGNALPOST_ACCEPTANCE_FAULT_MODE":mode}
        if source_responses:env["SIGNALPOST_ACCEPTANCE_SOURCE_DIR"]=str(Path(source_responses).resolve())
        command=[sys.executable,str(LAUNCHER),"--input",str(folder/"input.txt"),"--live-brreg",
                 "--output",str(folder/"output.jsonl"),"--state-output",str(folder/"state.json"),
                 "--evidence-cutoff","2030-01-01T00:00:00Z"]
        result=subprocess.run(command,cwd=base,env=env,capture_output=True,text=True,timeout=60)
        (folder/"stdout.log").write_text(result.stdout);(folder/"stderr.log").write_text(result.stderr)
        assert result.returncode==0,(mode,result.stderr[-1000:])
        rows=inspect_rows(folder/"output.jsonl",["923609016"])
        assert rows[0]["terminal_state"]==expected,(mode,rows[0]["terminal_state"])
        if mode!="partial":assert not rows[0]["claims"]
        else:
            assert rows[0]["sections"]["leadership_workplaces"]["state"] in STATES
            assert not any(c["field_family"]=="financial" for c in rows[0]["claims"])
            if source_responses:
                raw=json.loads((Path(source_responses)/"entity-equinor.json").read_text())
                assert next(c["value"] for c in rows[0]["claims"] if c["field"]=="name")==raw["navn"]
                claim=next(c for c in rows[0]["claims"] if c["field"]=="municipality")
                assert claim["value"]==raw["forretningsadresse"]["kommune"]
                evidence={e["evidence_id"]:e for e in rows[0]["evidence"]}
                assert evidence[claim["evidence_ids"][0]]["json_pointer"]=="/forretningsadresse/kommune"
        outcomes[mode]={"status":"PASS","terminal_state":expected,"exit_code":result.returncode,
                        "actual_http_requests":0,"controlled_transport":True,"claims":len(rows[0]["claims"])}
    return outcomes

FAULT_HOOK = r'''
import json,os,socket
from pathlib import Path
from urllib.parse import urlsplit
from signalpost import run
from signalpost.network import NetworkGateway
mode=os.environ["SIGNALPOST_ACCEPTANCE_FAULT_MODE"]
source=os.environ.get("SIGNALPOST_ACCEPTANCE_SOURCE_DIR")
class Transport:
 async def request(self,url,headers,timeout):
  path=urlsplit(url).path
  if path=="/robots.txt":return 200,{},b"User-agent: *\nAllow: /\n",url
  if mode=="timeout":raise TimeoutError("controlled source timeout")
  if mode in {"not_found","refused"}:return (404 if mode=="not_found" else 403),{},b"{}",url
  if path.endswith("/roller"):return 503,{},b"{}",url
  if source:
   label="entity-equinor" if "/enheter/" in path else "accounts-equinor" if "/regnskap/" in path else "workplaces-equinor"
   return 200,{"Content-Type":"application/json"},(Path(source)/(label+".json")).read_bytes(),url
  body={"organisasjonsnummer":"923609016","navn":"Controlled Partial Source ASA","forretningsadresse":{"kommune":"STAVANGER","kommunenummer":"1103"}} if "/enheter/" in path else {"_embedded":{"underenheter":[]},"page":{"number":0,"totalPages":1}} if path.endswith("/underenheter") else []
  return 200,{"Content-Type":"application/json"},json.dumps(body).encode(),url
original=socket.getaddrinfo
def resolve(host,*args,**kwargs):
 if host=="data.brreg.no":return [(socket.AF_INET,socket.SOCK_STREAM,socket.IPPROTO_TCP,"",("93.184.216.34",443))]
 raise AssertionError("Unexpected host in controlled offline acceptance: "+str(host))
socket.getaddrinfo=resolve
run.NetworkGateway=lambda **kwargs:NetworkGateway(transport=Transport(),**kwargs)
'''

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output-dir",required=True)
    parser.add_argument("--real-data")
    parser.add_argument("--source-responses", help="Optional retained BRREG response directory for offline partial-source replay")
    args=parser.parse_args()
    base=Path(args.output_dir).resolve();base.mkdir(parents=True,exist_ok=True)
    registry=base/"registry.jsonl"
    def save_registry(name="Functional Snapshot A ASA"):
        registry.write_text(json.dumps({"organisasjonsnummer":"923609016","navn":name,"as_of":"2024-01-01"})+"\n"+
            json.dumps({"organisation_number":"012345676","name":"Functional Leading Zero AS","as_of":"2024-01-01"})+"\n")
    save_registry()
    env=dict(os.environ);env.pop("PYTHONPATH",None)
    results={}
    def run_case(label,contents,fmt,expected,extra=None,prior=None,resume=False):
        folder=base/label;folder.mkdir(exist_ok=True)
        inp=folder/("input."+fmt);inp.write_text(contents)
        output=folder/"output.jsonl";state=folder/"state.json"
        command=[sys.executable,str(LAUNCHER),"--input",str(inp),"--format",fmt,
                 "--registry-snapshot",str(registry),"--output",str(output),"--state-output",str(state),
                 "--evidence-cutoff","2026-10-17T18:29:00Z"]
        if prior:command.extend(["--previous-state",str(prior)])
        if extra:command.extend(extra)
        if resume:command.append("--resume")
        process=subprocess.run(command,cwd=base,env=env,capture_output=True,text=True,timeout=30)
        (folder/"stdout.log").write_text(process.stdout);(folder/"stderr.log").write_text(process.stderr)
        assert process.returncode==0,(label,process.returncode,process.stderr[-1000:])
        report=json.loads(process.stdout)
        assert report["physical_requests"]==0
        rows=inspect_rows(output,expected)
        results[label]={"status":"PASS","rows":len(rows),"exit_code":process.returncode,
                        "terminal_states":[r["terminal_state"] for r in rows],"stderr_bytes":len(process.stderr),
                        "physical_requests":report["physical_requests"],"output_sha256":hashlib.sha256(output.read_bytes()).hexdigest()}
        return rows,state,output
    rows,_,_=run_case("single","923609016\n","plain",["923609016"])
    assert rows[0]["claims"][0]["value"]=="Functional Snapshot A ASA"
    run_case("array",json.dumps(["923609016","012345676","923609016"]),"json",["923609016","012345676","923609016"])
    run_case("starter_wrapper",json.dumps({"organisation_numbers":["923609016","012345676"]}),"json",["923609016","012345676"])
    run_case("csv","organisation_number\n012345676\n923609016\n","csv",["012345676","923609016"])
    rows,_,mixed=run_case("malformed",'{"organisation_number":"923609016"}\n{broken}\n{"organisation_number":"bad"}\n{"organisation_number":"976390512"}\n',"jsonl",["923609016","","bad","976390512"])
    assert rows[0]["terminal_state"]=="available" and all(r["terminal_state"]=="failed" and r["errors"] for r in rows[1:])
    run_case("resume","923609016\n","plain",["923609016"])
    run_case("resume","923609016\n","plain",["923609016"],resume=True)
    rows,baseline,_=run_case("baseline","923609016\n","plain",["923609016"])
    assert not rows[0]["refresh"]["changes"]
    save_registry("Functional Snapshot B ASA")
    rows,updated,history=run_case("changed","923609016\n","plain",["923609016"],prior=baseline)
    changes=rows[0]["refresh"]["changes"]
    assert len(changes)==1 and changes[0]["old_value"]=="Functional Snapshot A ASA" and changes[0]["new_value"]=="Functional Snapshot B ASA",changes
    assert changes[0]["previous_evidence"] and changes[0]["current_evidence"]
    rows,_,_=run_case("repeated","923609016\n","plain",["923609016"],prior=updated)
    assert not rows[0]["refresh"]["changes"]
    grown,grown_state,_=run_case("growing_batch", "923609016\n012345676\n923609016\n", "plain",
        ["923609016","012345676","923609016"],prior=updated)
    assert [row["refresh"]["mode"] for row in grown]==["compared","baseline_no_prior_state","compared"]
    assert not grown[0]["refresh"]["changes"]
    _,subset_state,_=run_case("subset_batch","012345676\n","plain",["012345676"],prior=grown_state)
    preserved=json.loads(subset_state.read_text())["companies"]
    assert set(preserved)=={"923609016","012345676"}
    assert preserved["923609016"]==json.loads(grown_state.read_text())["companies"]["923609016"]
    missing=subprocess.run([sys.executable,str(LAUNCHER),"--input",str(base/"does-not-exist")],cwd=base,env=env,capture_output=True,text=True)
    assert missing.returncode==2 and not missing.stdout and missing.stderr
    results["missing_input"]={"status":"PASS","exit_code":missing.returncode}
    data=Path(args.real_data).resolve() if args.real_data else history
    actual=[json.loads(line) for line in data.read_text().splitlines()]
    inspect_rows(data,[r["organisation_number"] for r in actual])
    with socket.socket() as sock:
        sock.bind(("127.0.0.1",0));port=sock.getsockname()[1]
    proc=subprocess.Popen([sys.executable,str(ROOT/"signalpost-starter-kit/run_signalpost_web.py"),"--data",str(data),"--port",str(port)],cwd=base,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    def get(path,params=None):
        url=f"http://127.0.0.1:{port}"+path+("?"+urlencode(params,doseq=True) if params else "")
        with urlopen(url,timeout=5) as response:
            assert response.status==200
            return response.read().decode()
    try:
        for _ in range(100):
            try:get("/");break
            except OSError:time.sleep(.05)
        else:raise RuntimeError("web launcher did not become ready")
        org=actual[0]["organisation_number"]
        legal=next(c for c in actual[0]["claims"] if c["field"] in {"name","legal_name"})
        home=get("/",{"q":org});assert 'href="/companies/'+org+'"' in home
        profile=get("/companies/"+org);assert str(legal["value"]) in profile
        supported=get("/verify",{"org":org,"field":"legal_name","value":legal["value"]});assert 'class="state">supported' in supported
        contradicted=get("/verify",{"org":org,"field":"legal_name","value":"Unrelated Fictional Company"});assert 'class="state">contradicted' in contradicted
        ev=next(e for e in actual[0]["evidence"] if e["evidence_id"] in legal["evidence_ids"])
        detail=get("/evidence/"+org+"/"+ev["evidence_id"])
        assert ev["source_url"] in detail and ev["content_sha256"] in detail
        unknown=get("/changes",{"org":"000000000"});assert "No material change events recorded" in unknown
        if len(actual)>1:
            comparison=get("/compare",{"org":[org,actual[1]["organisation_number"]],"field":"legal_name,revenue"})
            assert legal["value"] in comparison and "not_comparable" in comparison
            (base/"comparison.html").write_text(comparison)
        (base/"profile.html").write_text(profile)
        results["http_real_records" if args.real_data else "http_controlled_records"]={"status":"PASS","number_search":"PASS","verify_supported_contradicted":"PASS","source_url_and_hash":"PASS","unknown_history":"PASS"}
    finally:
        proc.terminate();proc.wait(timeout=5)
    proc=subprocess.Popen([sys.executable,str(ROOT/"signalpost-starter-kit/run_signalpost_web.py"),"--data",str(mixed),"--port",str(port)],cwd=base,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    try:
        for _ in range(100):
            try:mixed_home=get("/");break
            except OSError:time.sleep(.05)
        else:raise RuntimeError("mixed invalid-input output cannot launch the dashboard")
        assert "Inputs that could not be researched" in mixed_home and "row:2" in mixed_home and "row:3" in mixed_home
        assert 'href="/companies/923609016"' in mixed_home
        results["mixed_invalid_input_dashboard"]={"status":"PASS","invalid_rows_visible":2}
    finally:
        proc.terminate();proc.wait(timeout=5)
    results["controlled_source_failures"]=run_fault_cases(base,args.source_responses)
    report={"measurement_kind":"independent_process_json_http_acceptance","source_sha":subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),"dirty":bool(subprocess.check_output(["git","status","--porcelain"],cwd=ROOT).strip()),"official_schema_available":False,"network_acquisition":False,"real_data_sha256":hashlib.sha256(data.read_bytes()).hexdigest(),"cases":results,"passed":True}
    (base/"acceptance.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report,indent=2))
if __name__=="__main__":main()
