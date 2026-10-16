"""Real launcher regressions for growing batches and strict checkpoint identity."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from signalpost.history import SOURCE_POLICY_VERSION, canonical_json, sha256_json, validate_artifact

ROOT = Path(__file__).resolve().parents[2]

class GrowingBatchTests(unittest.TestCase):
    def test_growing_subset_budget_changes_and_legacy_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)
            registry=base/"registry.jsonl"
            orgs=["923609016","976390512","995854600"]
            def snapshot(name):
                registry.write_text("".join(json.dumps({"organisation_number":org,"name":name if i==0 else "Controlled Company "+str(i),"as_of":"2024-01-01"})+"\n" for i,org in enumerate(orgs)))
            snapshot("Controlled Original ASA")
            def run(label, inputs, prior=None, config=None, source=None, resume_checkpoint=None):
                folder=base/label;folder.mkdir()
                (folder/"input.txt").write_text("\n".join(inputs)+"\n")
                command=[sys.executable,str(ROOT/"signalpost-starter-kit/run_signalpost.py"),"--input",str(folder/"input.txt"),"--registry-snapshot",str(registry),"--output",str(folder/"output.jsonl"),"--state-output",str(folder/"state.json"),"--evidence-cutoff","2030-01-01T00:00:00Z"]
                if prior:command += ["--previous-state",str(prior)]
                if config is not None:
                    (folder/"config.json").write_text(json.dumps(config));command += ["--config",str(folder/"config.json")]
                if source:command += ["--registry-source-url",source]
                if resume_checkpoint:command += ["--resume","--checkpoint",str(resume_checkpoint)]
                env=dict(os.environ);env.pop("PYTHONPATH",None)
                proc=subprocess.run(command,cwd=base,env=env,capture_output=True,text=True,timeout=30)
                if resume_checkpoint:
                    self.assertEqual(proc.returncode,1,proc.stderr)
                    self.assertIn("fingerprint does not match",proc.stderr)
                    return
                self.assertEqual(proc.returncode,0,proc.stderr)
                self.assertEqual(json.loads(proc.stdout)["physical_requests"],0)
                rows=[json.loads(line) for line in (folder/"output.jsonl").read_text().splitlines()]
                self.assertEqual([r["organisation_number"] for r in rows],inputs)
                state=json.loads((folder/"state.json").read_text());validate_artifact(state)
                return rows,folder/"state.json",state
            initial,baseline,state=run("baseline",orgs[:1])
            # Reproduce the exact old operational identity, then prove a matching
            # legacy handoff migrates without changing its content-addressed ref.
            legacy_identity={"source_policy_version":SOURCE_POLICY_VERSION,"runtime_config":{},"registry_source_url":None,"registry_snapshot_as_of":None,"network_policy":"direct","live_brreg":False,"live_websites":False,"no_keyless_websites":False,"budget":{"hard_seconds":1800.0,"soft_seconds":1350.0,"completion_reserve_seconds":300.0,"physical_request_limit":1012,"logical_request_limit":None,"paid_cost_limit":"0","global_http_concurrency":32,"per_host_concurrency":2,"per_company_physical_limit":None,"per_host_physical_limit":None}}
            # CLI defaults are intentionally checked here, not inferred from a
            # matching production hash helper.
            legacy_fingerprint=sha256_json(legacy_identity)
            state["configuration_fingerprint"]=legacy_fingerprint
            for company in state["companies"].values():company["configuration_fingerprint"]=legacy_fingerprint
            legacy=base/"legacy.json";legacy.write_text(json.dumps(state))
            migrated,migration,_=run("migration",orgs[:1],legacy)
            self.assertEqual(migrated[0]["refresh"]["mode"],"compared")
            self.assertEqual(migrated[0]["refresh"]["previous_state_ref"],"sha256:"+hashlib.sha256(canonical_json(state)).hexdigest())
            snapshot("Controlled Changed ASA")
            grown,expanded,expanded_state=run("expanded",[orgs[1],orgs[0],orgs[2],orgs[0]],migration)
            self.assertEqual([r["refresh"]["mode"] for r in grown],["baseline_no_prior_state","compared","baseline_no_prior_state","compared"])
            change=grown[1]["refresh"]["changes"]
            self.assertEqual(len(change),1)
            self.assertEqual(change[0]["old_value"],"Controlled Original ASA")
            self.assertEqual(change[0]["new_value"],"Controlled Changed ASA")
            self.assertTrue(change[0]["previous_evidence"] and change[0]["current_evidence"])
            self.assertEqual(set(expanded_state["companies"]),set(orgs))
            subset,subset_path,subset_state=run("subset",orgs[1:2],expanded,{"budget":{"physical_request_limit":1,"global_http_concurrency":1}})
            self.assertEqual(subset[0]["refresh"]["mode"],"compared")
            self.assertEqual(subset_state["companies"][orgs[0]],expanded_state["companies"][orgs[0]])
            repeated,_,_=run("repeated",orgs,subset_path,{"physical_request_limit":2000})
            self.assertTrue(all(r["refresh"]["mode"]=="compared" and not r["refresh"]["changes"] for r in repeated))
            wrong,_,_=run("wrong-source",orgs,subset_path,source="https://different.example.test/registry")
            self.assertTrue(all(r["refresh"]["mode"]=="incompatible_prior_state" for r in wrong))
            run("bad-resume",orgs, resume_checkpoint=baseline.with_suffix(".json.checkpoint.sqlite"))
