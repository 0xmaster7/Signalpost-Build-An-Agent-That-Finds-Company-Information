from types import SimpleNamespace
from signalpost.brreg import normalize_entity,financial_records,METRICS
from signalpost.run import _website_profile
from signalpost.websites import registry_contact_leads,additional_no_candidates


def test_official_registered_locations_preserve_type_and_country():
    body={'organisasjonsnummer':'987974249','organisasjonsform':{'kode':'AS'},
        'forretningsadresse':{'adresse':['Street 1'],'poststed':'OSLO','land':'Norge','landkode':'NO'},
        'beliggenhetsadresse':{'adresse':['Other 2'],'landkode':'NO'}}
    out=normalize_entity(body)
    assert out['business_address']['landkode']=='NO'
    assert out['registered_workplace_address']['adresse']==['Other 2']
    body['organisasjonsform']['kode']='ENK'
    out=normalize_entity(body)
    assert out['business_address'] is None and out['registered_workplace_address'] is None


def test_contact_domains_are_leads_not_mailboxes_and_free_mail_excluded():
    assert registry_contact_leads({'epostadresse':'owner@gmail.com'})==[]
    assert registry_contact_leads({'epostadresse':'hello@example.no'})==[('https://example.no/','epostadresse')]
    assert registry_contact_leads({'epostadresse':'a@example.no/path'})==[]
    assert registry_contact_leads({'hjemmeside':'www.example.no'})==[('https://www.example.no/','hjemmeside')]
    assert len(additional_no_candidates('Distinctive Industrial AS'))==2
    assert additional_no_candidates('AS')==[]


def test_website_corroboration_uses_verified_person_names_only():
    def claim(field,value,eid):
        return SimpleNamespace(section='leadership_workplaces',field=field,value=value,scope='person_role',evidence_ids=[eid])
    live=SimpleNamespace(observations={},evidence=[SimpleNamespace(evidence_id='person',extraction_method='brreg_role_name_join_v1')],
        claims=[claim('role.name','Kari Nordmann','person'),claim('role.role_description','Daglig leder','role'),claim('role.name','Auditor AS','org')])
    assert _website_profile('987974249',live_result=live)['registered_roles']==['Kari Nordmann']


def test_extended_mapping_does_not_zero_fill_absent_metrics():
    records=financial_records([{'regnskapsperiode':{'fraDato':'2025-01-01','tilDato':'2025-12-31'},
        'regnskapstype':'SELSKAP','resultatregnskapResultat':{'driftsresultat':{'driftskostnad':{'sumDriftskostnad':12}}}}])
    assert len(METRICS)==23
    assert records[0]['metrics']['operating_costs']==12
    assert records[0]['metrics']['cash'] is None


def test_new_financial_query_fields_keep_required_dimensions():
    from signalpost.query import FindFilter, QueryError, FIELD_ALIASES, validate_filter
    from decimal import Decimal
    import pytest
    with pytest.raises(QueryError):
        validate_filter(FindFilter('cash','gt',Decimal(0)))
    validate_filter(FindFilter('cash','gt',Decimal(0),currency='NOK',period_end='2025-12-31',scope='legal_entity',unit='NOK'))
    assert FIELD_ALIASES['registered_address']=='business_address'


def test_current_registered_workplaces_publish_but_historical_cutoffs_do_not():
    import asyncio,json
    from datetime import datetime,timezone
    from signalpost.brreg import fetch_company
    org='930827088'
    class Gateway:
        async def fetch(self,url,**kw):
            purpose=kw['purpose']
            if purpose=='entity':body={'organisasjonsnummer':org,'navn':'Test AS','organisasjonsform':{'kode':'AS'}}
            elif purpose=='accounts':body=[]
            elif purpose=='roles':body={'rollegrupper':[]}
            elif purpose=='subunits':body={'_embedded':{'underenheter':[{'organisasjonsnummer':'979586701','overordnetEnhet':org,'navn':'Test workplace','beliggenhetsadresse':{'adresse':['Road 1']},'hjemmeside':'workplace.example.no'}]},'page':{'number':0,'totalPages':1}}
            else:raise AssertionError(purpose)
            return 200,{},json.dumps(body).encode(),url,'ok'
    cutoff=datetime.now(timezone.utc)
    live=asyncio.run(fetch_company(org,Gateway(),cutoff,allow_current_identity_after_run_start=True))
    workplace=[c for c in live.claims if c.field_family=='workplace']
    assert any(c.field=='workplace.beliggenhetsadresse' for c in workplace)
    assert all(c.subject_id=='979586701' and c.scope=='workplace' and c.as_of is None for c in workplace)
    assert any(x['source']=='workplace_contact' for x in live.observations['website_candidates'])
    historical=asyncio.run(fetch_company(org,Gateway(),cutoff,allow_current_identity_after_run_start=False))
    assert not any(c.field_family=='workplace' for c in historical.claims)


def test_contact_lead_locator_serializes_in_closed_synthesis_schema():
    from signalpost.synthesis import validate_synthesis_schema
    validate_synthesis_schema({'brreg_observations':{'website_candidates':[{'raw':'https://example.no/',
        'source':'registry_email','json_pointer':'/epostadresse'}]}})
