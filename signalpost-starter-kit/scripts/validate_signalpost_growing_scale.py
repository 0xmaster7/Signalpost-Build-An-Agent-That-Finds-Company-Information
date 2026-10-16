#!/usr/bin/env python3
"""Offline growing-batch process acceptance with explicitly fictional registry data."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[2]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir",required=True)
    args=parser.parse_args()
    base=Path(args.output_dir).resolve()
    base.mkdir(parents=True,exist_ok=False)
    orgs=[str(700000000+i) for i in range(1100)]
    registry=base/"registry.jsonl"
    previous=None
    results={}
    for label,inputs,changed in [("baseline1000",orgs[:1000],False),("expanded1100",orgs,True),("subset2",orgs[:2],True),("repeated1100",orgs,True)]:
        registry.write_text("".join(json.dumps({"organisation_number":org,"name":("Controlled Changed Company" if changed and i==0 else "Controlled Scale Company "+str(i)),"as_of":"2024-01-01"})+"\n" for i,org in enumerate(orgs)))
        folder=base/label;folder.mkdir()
        inp=folder/"input.json";inp.write_text(json.dumps({"organisation_numbers":inputs}))
        command=[sys.executable,str(ROOT/"signalpost-starter-kit/run_signalpost.py"),"--input",str(inp),"--registry-snapshot",str(registry),"--output",str(folder/"output.jsonl"),"--state-output",str(folder/"state.json"),"--evidence-cutoff","2030-01-01T00:00:00Z"]
        if previous:command += ["--previous-state",str(previous)]
        start=time.monotonic()
        proc=subprocess.run(command,cwd=base,env={k:v for k,v in os.environ.items() if k!="PYTHONPATH"},capture_output=True,text=True,timeout=300)
        (folder/"command.json").write_text(json.dumps(command,indent=2))
        (folder/"stdout.log").write_text(proc.stdout);(folder/"stderr.log").write_text(proc.stderr)
        assert proc.returncode==0,proc.stderr[-1000:]
        rows=[json.loads(line) for line in (folder/"output.jsonl").read_text().splitlines()]
        assert [row["organisation_number"] for row in rows]==inputs
        assert all(row["terminal_state"]=="available" for row in rows)
        assert json.loads(proc.stdout)["physical_requests"]==0
        state=json.loads((folder/"state.json").read_text())
        if label=="expanded1100":
            assert all(row["refresh"]["mode"]=="compared" for row in rows[:1000])
            assert all(row["refresh"]["mode"]=="baseline_no_prior_state" for row in rows[1000:])
            assert len(rows[0]["refresh"]["changes"])==1
            change=rows[0]["refresh"]["changes"][0]
            assert change["previous_evidence"] and change["current_evidence"]
            assert change["new_value"]=="Controlled Changed Company"
        if label=="subset2":
            assert len(state["companies"])==1100
            prior=json.loads(previous.read_text())
            assert state["companies"][orgs[100]]==prior["companies"][orgs[100]]
        if label=="repeated1100":
            assert all(row["refresh"]["mode"]=="compared" and not row["refresh"]["changes"] for row in rows)
        results[label]={"passed":True,"exit_code":proc.returncode,"rows":len(rows),"state_companies":len(state["companies"]),"seconds":round(time.monotonic()-start,3),"physical_requests":0,"changes":sum(len(row["refresh"]["changes"]) for row in rows),"output_sha256":hashlib.sha256((folder/"output.jsonl").read_bytes()).hexdigest()}
        previous=folder/"state.json"
        (base/"results.json").write_text(json.dumps(results,indent=2))
    print(json.dumps({"passed":True,"fictional_frozen_data":True,"cases":results},indent=2))

if __name__=="__main__":main()
