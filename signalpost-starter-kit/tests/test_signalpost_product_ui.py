"""Product presentation acceptance: truth, grouping and provenance stay intact."""
import json
from pathlib import Path
import tempfile
import unittest
from bs4 import BeautifulSoup

from signalpost.adapter import to_evaluator
from signalpost.query import load_profiles
from signalpost.web import create_app
from signalpost.web_ui import record_groups, roles
import test_signalpost_m08 as m08

make_envelope=m08.make_envelope
finance=m08.finance


class ProductUXTests(unittest.TestCase):
    setUp=m08.ServerRenderedUXTests.setUp
    tearDown=m08.ServerRenderedUXTests.tearDown
    get=m08.ServerRenderedUXTests.get

    def test_search_starts_simple_and_retains_all_advanced_conditions(self):
        soup=BeautifulSoup(self.get('/').text,'html.parser')
        self.assertIsNone(soup.select_one('details.disclosure').get('open'))
        self.assertEqual(soup.select_one('form input[name=q]')['value'],'')
        self.assertNotIn('0 supporting source records',soup.get_text())
        self.assertEqual(len(soup.select('nav[aria-label="Main navigation"] [aria-current=page]')),1)
        response=self.get('/',params=[('q','Acme'),('filter_field','legal_form'),('filter_op','eq'),('filter_value','AS'),('filter_field','municipality'),('filter_op','eq'),('filter_value','Oslo')])
        filtered=BeautifulSoup(response.text,'html.parser')
        self.assertEqual(response.status_code,200)
        self.assertEqual([e['value'] for e in filtered.select('input[name=filter_value]')],['AS','Oslo',''])
        self.assertEqual([e.select_one('option[selected]')['value'] for e in filtered.select('select[name=filter_field]')],['legal_form','municipality',''])
        self.assertTrue(filtered.select_one('details.disclosure').has_attr('open'))
        self.assertIn('View matching evidence',filtered.get_text())

    def test_profile_has_company_name_and_every_available_claim_keeps_evidence(self):
        soup=BeautifulSoup(self.get('/companies/001234567').text,'html.parser')
        self.assertEqual(soup.h1.get_text(),'Acme <script> AS')
        self.assertNotIn('Evidence-bounded summary',soup.get_text())
        self.assertIn('Latest source observation',soup.get_text())
        self.assertEqual({e['data-claim-id'] for e in soup.select('[data-claim-id]')},{c.claim_id for c in load_profiles(self.path)['001234567'].claims if c.state.value=='available'})
        for element in soup.select('[data-claim-id]'):
            self.assertTrue(element.select_one('a[href^="/evidence/001234567/"]'))
        self.assertEqual([s['id'] for s in soup.select('section[id]')],['identity','financials','leadership','workplaces','websites','activity','history','sources'])
        self.assertFalse(soup.find('script',string=lambda s:s and 'alert(1)' in s))

    def test_comparison_preserves_selection_and_uses_named_headers(self):
        response=self.get('/compare',params=[('org','001234567'),('org','123456789'),('field','legal_name,revenue')])
        soup=BeautifulSoup(response.text,'html.parser')
        self.assertEqual([e['value'] for e in soup.select('input[name=org]')],['001234567','123456789','',''])
        self.assertIn('Acme <script> AS',soup.select_one('thead').get_text())
        self.assertEqual(soup.select_one('input[name=field]')['value'],'legal_name,revenue')
        self.assertTrue(soup.select_one('.table-wrap[tabindex="0"]'))
        self.assertEqual(len(soup.select('tbody tr')[-1].select('td')),2)
        self.assertTrue(soup.select('[data-state=not_comparable]'))

    def test_verification_shows_only_the_canonical_values_selected_by_the_query(self):
        for value,state in [('Acme <script> AS','supported'),('Wrong Name','contradicted')]:
            soup=BeautifulSoup(self.get('/verify',params={'org':'001234567','field':'legal_name','value':value}).text,'html.parser')
            self.assertEqual(soup.select_one('.result-banner')['data-state'],state)
            self.assertIn('Acme <script> AS',soup.select_one('.canonical-value').get_text())
            self.assertEqual(soup.select_one('input[name=value]')['value'],value)
            self.assertTrue(soup.select_one('.result-banner a[href^="/evidence/"]'))
        missing=BeautifulSoup(self.get('/verify',params={'org':'001234567','field':'revenue','value':'0'}).text,'html.parser')
        self.assertEqual(missing.select_one('.result-banner')['data-state'],'insufficient_evidence')
        self.assertIsNone(missing.select_one('.canonical-value'))

    def test_evidence_retains_exact_identifiers_dimensions_and_snapshot_permissions(self):
        profile=load_profiles(self.path)['001234567'];item=next(iter(profile.evidence.values()))
        soup=BeautifulSoup(self.get('/evidence/001234567/'+item.evidence_id).text,'html.parser')
        self.assertIn(item.content_sha256,soup.get_text())
        self.assertIn(item.evidence_id,soup.get_text())
        self.assertIn('Snapshot(s) and permissions',soup.get_text())
        canonical=json.loads(soup.select_one('pre').get_text())
        self.assertTrue(canonical)
        self.assertIn(item.evidence_id,canonical[0]['evidence_ids'])
        self.assertTrue(canonical[0]['source_snapshot_ids'])
        self.assertTrue(soup.find('a',href=item.source_url))

    def test_changes_empty_state_has_no_empty_table_and_real_events_keep_both_times(self):
        empty=BeautifulSoup(self.get('/changes',params={'org':'923609016'}).text,'html.parser')
        self.assertIsNone(empty.find('table'))
        self.assertIn('No material change events recorded',empty.get_text())
        populated=BeautifulSoup(self.get('/changes',params={'org':'001234567'}).text,'html.parser')
        self.assertTrue(populated.select_one('.event .change-values'))
        self.assertIn('Before',populated.get_text());self.assertIn('After',populated.get_text())
        self.assertIn('effective date not established',populated.get_text())
        self.assertTrue(populated.select_one('.event a[href^="/evidence/"]'))
        self.assertEqual(populated.select_one('input[name=org]')['value'],'001234567')

    def test_bad_input_is_html_feedback_with_preserved_values_and_correct_status(self):
        response=self.get('/',params={'q':'<script>','field':'employees','value':'bad'})
        soup=BeautifulSoup(response.text,'html.parser')
        self.assertEqual(response.status_code,400)
        self.assertIn('text/html',response.headers['content-type'])
        self.assertIn('numeric filter value is malformed',soup.select_one('[role=alert]').get_text())
        self.assertEqual(soup.select_one('input[name=q]')['value'],'<script>')
        self.assertEqual(soup.select_one('input[name=value]')['value'],'bad')
        comparison=self.get('/compare',params={'org':'001234567'})
        self.assertEqual(comparison.status_code,400)
        self.assertIn('compare requires two to four',comparison.text)
        absent=self.get('/companies/000000000')
        self.assertEqual(absent.status_code,404)
        self.assertIn('Return to saved companies',absent.text)

    def test_unparseable_source_identifier_does_not_crash_presentation(self):
        row=make_envelope('001234567','Controlled Malformed Source AS',[{'field':'legal_form','value':'AS','source_url':'http://['}])
        self.path.write_text(json.dumps(to_evaluator(row))+'\n');self.app=create_app(self.path)
        for route in ['/companies/001234567','/evidence/001234567/001234567:e1','/verify?org=001234567&field=legal_form&value=AS']:
            response=self.get(route)
            self.assertEqual(response.status_code,200)
            self.assertNotIn('href="http://["',response.text)

    def test_multiple_financial_values_stay_in_their_own_company_cell(self):
        self.rows[0]=make_envelope('001234567','Controlled Multiple AS',[finance(0),finance(10,end='2023-12-31')])
        self.path.write_text(''.join(json.dumps(to_evaluator(row))+'\n' for row in self.rows))
        self.app=create_app(self.path)
        soup=BeautifulSoup(self.get('/compare',params={'org':'001234567,123456789','field':'revenue'}).text,'html.parser')
        cells=soup.select('tbody tr td')
        self.assertEqual(len(cells),2)
        self.assertEqual(len(cells[0].select('.cell-value')),2)
        self.assertEqual(len(cells[1].select('.cell-value')),1)


class ProvenRecordGroupingTests(unittest.TestCase):
    def profile(self,specs):
        row=make_envelope('923609016','Controlled Source Records ASA',specs)
        for claim,evidence,snapshot in zip(row.claims[1:],row.evidence[1:],row.source_snapshots[1:]):
            spec=next(s for s,c in zip(specs,row.claims[1:]) if c is claim)
            evidence.source_url=snapshot.source_url='https://registry.example.test/records'
            evidence.content_sha256=snapshot.content_sha256=spec.get('digest','a'*64)
            evidence.json_pointer=spec['pointer']
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'data.jsonl';path.write_text(json.dumps(to_evaluator(row))+'\n')
            return load_profiles(path)['923609016']

    def test_role_name_and_description_join_by_record_not_claim_order(self):
        def role(field,value,pointer):return {'field':field,'value':value,'pointer':pointer,'family':'role','section':'leadership_workplaces'}
        profile=self.profile([
            role('role.name','Alice','/rollegrupper/0/roller/0/person/navn'),
            role('role.name','Bob','/rollegrupper/0/roller/1/person/navn'),
            role('role.role_description','Director','/rollegrupper/0/roller/1/type/beskrivelse'),
            role('role.role_description','Chair','/rollegrupper/0/roller/0/type/beskrivelse'),
            role('role.role_group','Board','/rollegrupper/0/type/beskrivelse'),
            role('role.name','Unbound Person','/value'),
        ])
        soup=BeautifulSoup(roles(profile),'html.parser')
        entries={e.h3.get_text():e.get_text() for e in soup.select('.role-person')}
        self.assertIn('Chair',entries['Alice']);self.assertNotIn('Director',entries['Alice'])
        self.assertIn('Director',entries['Bob']);self.assertNotIn('Chair',entries['Bob'])
        self.assertNotIn('Unbound Person',entries)
        self.assertIn('Unbound Person',soup.get_text())
        self.assertEqual(len(record_groups(profile,'role')[0]),2)

    def test_same_period_and_scope_do_not_merge_different_filings_or_source_versions(self):
        def metadata(field,value,pointer,digest='a'*64):return {'field':field,'value':value,'pointer':pointer,'digest':digest,'family':'financial_record_metadata','section':'accounts_history','period_end':'2024-12-31T00:00:00Z'}
        profile=self.profile([
            metadata('financial_record.record_id','111','/0/id'),metadata('financial_record.period_end','2024-12-31','/0/regnskapsperiode/tilDato'),
            metadata('financial_record.record_id','222','/1/id'),metadata('financial_record.period_end','2024-12-31','/1/regnskapsperiode/tilDato'),
            metadata('financial_record.record_id','333','/0/id','b'*64),
        ])
        groups,unbound=record_groups(profile,'financial')
        self.assertEqual(len(groups),3);self.assertFalse(unbound)
        self.assertEqual(sorted([c.value for c in claims if c.field=='financial_record.record_id'] for _,claims in groups),[['111'],['222'],['333']])

    def test_missing_shared_record_binding_leaves_supported_facts_unjoined(self):
        profile=self.profile([{'field':'role.name','value':'Source Person','pointer':'/name','family':'role','section':'leadership_workplaces'}, {'field':'role.role_description','value':'Chair','pointer':'/description','family':'role','section':'leadership_workplaces'}])
        groups,unbound=record_groups(profile,'role')
        self.assertFalse(groups);self.assertEqual(len(unbound),2)
        soup=BeautifulSoup(roles(profile),'html.parser')
        self.assertIsNone(soup.select_one('.role-person'))
        self.assertEqual(len(soup.select('[data-claim-id]')),2)
