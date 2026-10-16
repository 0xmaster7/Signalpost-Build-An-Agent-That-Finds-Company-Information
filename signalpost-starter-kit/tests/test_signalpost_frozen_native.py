"""Public starter-shaped frozen-registry execution regressions, with no network."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]

class NativeFrozenRegistryTests(unittest.TestCase):
    def test_native_csv_and_jsonl_snapshots_work_from_an_unrelated_directory(self):
        cases = {
            "lower.csv": "organisasjonsnummer,navn,organisasjonsform.kode\n923609016,Snapshot Example ASA,ASA\n",
            "title.csv": "Organisasjonsnummer,Navn,Organisasjonsform.kode\n923609016,Snapshot Example ASA,ASA\n",
            "native.jsonl": json.dumps({"organisasjonsnummer":"923609016","navn":"Snapshot Example ASA"})+"\n",
        }
        for filename, contents in cases.items():
            with self.subTest(format=filename), tempfile.TemporaryDirectory() as tmp:
                base=Path(tmp)
                (base/filename).write_text(contents)
                (base/"input.jsonl").write_text('{"organisation_number":"923609016"}\n')
                env=dict(os.environ);env.pop("PYTHONPATH",None)
                result=subprocess.run([sys.executable,str(ROOT/"signalpost-starter-kit/run_signalpost.py"),
                    "--input",str(base/"input.jsonl"),"--registry-snapshot",str(base/filename),
                    "--output",str(base/"output.jsonl"),"--state-output",str(base/"state.json")],
                    cwd=tmp,env=env,capture_output=True,text=True,timeout=20)
                self.assertEqual(result.returncode,0,result.stderr)
                rows=[json.loads(line) for line in (base/"output.jsonl").read_text().splitlines()]
                self.assertEqual(len(rows),1)
                self.assertEqual(rows[0]["terminal_state"],"available")
                self.assertEqual(rows[0]["claims"][0]["value"],"Snapshot Example ASA")
                self.assertEqual(json.loads(result.stdout)["physical_requests"],0)

    def test_public_starter_json_batch_wrapper_preserves_rows(self):
        from signalpost.inputs import parse_records
        rows=parse_records(json.dumps({"organisation_numbers":["923609016","976390512"]}),"json")
        self.assertEqual([row.organisation_number for row in rows],["923609016","976390512"])

    def test_frozen_snapshot_date_and_source_parameters_are_honored(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)
            (base/"registry.jsonl").write_text(json.dumps({"organisation_number":"923609016","name":"Snapshot Example ASA"})+"\n")
            (base/"input.txt").write_text("923609016\n")
            for label,as_of,available in [("past","2024-01-01",True),("future","2027-01-01",False)]:
                with self.subTest(snapshot=label):
                    result=subprocess.run([sys.executable,str(ROOT/"signalpost-starter-kit/run_signalpost.py"),
                        "--input",str(base/"input.txt"),"--registry-snapshot",str(base/"registry.jsonl"),
                        "--registry-snapshot-as-of",as_of,"--registry-source-url","https://registry.example.test/snapshot",
                        "--evidence-cutoff","2026-01-01T00:00:00Z","--output",str(base/(label+".jsonl")),
                        "--state-output",str(base/(label+"-state.json"))],capture_output=True,text=True,cwd=tmp,timeout=20)
                    self.assertEqual(result.returncode,0,result.stderr)
                    row=json.loads((base/(label+".jsonl")).read_text())
                    self.assertEqual(bool(row["claims"]),available)
                    if available:
                        self.assertTrue(row["claims"][0]["as_of"].startswith("2024-01-01"))
                        self.assertEqual(row["evidence"][0]["source_url"],"https://registry.example.test/snapshot")

    def test_live_municipality_values_point_to_the_actual_nested_address(self):
        import asyncio
        from datetime import datetime,timezone
        from signalpost.brreg import fetch_company
        class Gateway:
            async def fetch(self,url,**kwargs):
                if kwargs["purpose"]=="entity":
                    body={"organisasjonsnummer":"923609016","navn":"Source Shape ASA",
                        "forretningsadresse":{"kommune":"STAVANGER","kommunenummer":"1103"}}
                elif kwargs["purpose"]=="subunits":
                    body={"_embedded":{"underenheter":[]},"page":{"number":0,"totalPages":1}}
                elif kwargs["purpose"]=="roles":body={"rollegrupper":[]}
                else:body=[]
                return 200,{},json.dumps(body).encode(),url,"ok"
        result=asyncio.run(fetch_company("923609016",Gateway(),datetime(2099,1,1,tzinfo=timezone.utc)))
        evidence={e.evidence_id:e for e in result.evidence}
        for field,value,pointer in [("municipality","STAVANGER","/forretningsadresse/kommune"),
            ("municipality_number","1103","/forretningsadresse/kommunenummer")]:
            claim=next((c for c in result.claims if c.field==field),None)
            self.assertIsNotNone(claim)
            self.assertEqual(claim.value,value)
            self.assertEqual(evidence[claim.evidence_ids[0]].json_pointer,pointer)

    def test_source_timeout_returns_failed_result_without_fabricated_http_status(self):
        import asyncio
        from datetime import datetime,timezone
        from signalpost.brreg import fetch_company
        class Gateway:
            async def fetch(self,url,**kwargs):return 0,{},b"",url,"timeout"
        result=asyncio.run(fetch_company("923609016",Gateway(),datetime(2030,1,1,tzinfo=timezone.utc)))
        self.assertEqual(result.terminal_state.value,"failed")
        self.assertFalse(result.claims)
        self.assertTrue(result.errors)
        self.assertTrue(all(s.http_status is None for s in result.snapshots))

    def test_unexpected_worker_failure_still_publishes_every_terminal_row(self):
        import contextlib
        import io
        from unittest.mock import AsyncMock,patch
        from signalpost.run import main
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);(base/"input.txt").write_text("923609016\n976390512\n")
            with patch("signalpost.run.fetch_company",new=AsyncMock(side_effect=RuntimeError("controlled worker failure"))),contextlib.redirect_stdout(io.StringIO()):
                code=main(["--input",str(base/"input.txt"),"--live-brreg","--output",str(base/"output.jsonl"),"--state-output",str(base/"state.json")])
            self.assertEqual(code,0)
            rows=[json.loads(line) for line in (base/"output.jsonl").read_text().splitlines()]
            self.assertEqual([row["organisation_number"] for row in rows],["923609016","976390512"])
            self.assertTrue(all(row["terminal_state"]=="failed" and not row["claims"] for row in rows))
            self.assertTrue(all(any(e["code"]=="BRREG_ACTION_UNEXPECTED_FAILURE" for e in row["errors"]) for row in rows))

    def test_role_projection_locators_resolve_to_person_and_organisation_sources(self):
        import asyncio
        from datetime import datetime,timezone
        from signalpost.brreg import fetch_company
        roles={"rollegrupper":[{"type":{"kode":"STYR","beskrivelse":"Board"},"sistEndret":"2025-01-01",
            "roller":[{"person":{"navn":{"fornavn":"Source","etternavn":"Person"}},"type":{"kode":"MEDL","beskrivelse":"Member"},"fratraadt":False},
                      {"enhet":{"organisasjonsnummer":"976390512","navn":"Source Organisation AS"},"type":{"kode":"MEDL","beskrivelse":"Member"},"fratraadt":False}]}]}
        class Gateway:
            async def fetch(self,url,**kwargs):
                body=roles if kwargs["purpose"]=="roles" else {"organisasjonsnummer":"923609016","navn":"Source Shape AS"} if kwargs["purpose"]=="entity" else {"_embedded":{"underenheter":[]},"page":{"number":0,"totalPages":1}} if kwargs["purpose"]=="subunits" else []
                return 200,{},json.dumps(body).encode(),url,"ok"
        result=asyncio.run(fetch_company("923609016",Gateway(),datetime(2030,1,1,tzinfo=timezone.utc)))
        evidence={e.evidence_id:e for e in result.evidence}
        for claim in result.claims:
            if claim.field_family!="role":continue
            pointer=evidence[claim.evidence_ids[0]].json_pointer
            value=roles
            for token in pointer.lstrip("/").split("/"):
                value=value[int(token)] if isinstance(value,list) else value[token]
            if claim.field=="role.name":
                actual=" ".join(value[k] for k in ("fornavn","mellomnavn","etternavn") if value.get(k)) if isinstance(value,dict) else value
                self.assertEqual(actual,claim.value)
            elif claim.field=="role.holder_kind":
                self.assertEqual(claim.value,"organisation" if value.get("enhet") else "person")
            elif claim.field=="role.inactive":
                self.assertEqual(claim.value,bool(value.get("avregistrert") or value.get("fratraadt")))
            else:self.assertEqual(value,claim.value)
