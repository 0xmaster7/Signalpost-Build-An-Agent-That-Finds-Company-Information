"""Document attribution and reconciliation regressions. All OCR boxes are synthetic."""
from copy import deepcopy
from signalpost.annual_accounts import reconcile, decimal_number
from signalpost.network import _brreg_document_api_url

ORG = "987974249"

def word(text, x, y, width=130, confidence=.99):
    return dict(text=text,x1=x,x2=x+width,y1=y,y2=y+12,confidence=confidence)

def sample():
    cover = dict(page=1,width=1000,words=[word("Organisasjonsnummer: " + ORG,10,10,600),
        word("Journalnummer: 2026488063",10,30,600),
        word("Arsregnskapets periode: 01.01.2025 - 31.12.2025",10,50,800),
        word("Morselskap i konsern: Nei",10,70,600)])
    financial = dict(page=2,width=1000,words=[word("Organisasjonsnr: " + ORG,10,10,500),
        word("RESULTATREGNSKAP",10,30,500),word("Belop i: NOK",10,50,200),
        word("2025",650,50,50),word("2024",850,50,50),
        word("Sum inntekter",10,90,300),word("5 135 536",610,90,120),word("5 590 589",820,90,120),
        word("Driftsresultat",10,110,300),word("-22 366",610,110,120),word("1 099 625",820,110,120),
        word("Arsresultat",10,130,300),word("-12 695",610,130,120),word("865 488",820,130,120)])
    workforce = dict(page=5,width=1000,words=[word("Organisasjonsnr: " + ORG,10,10,500),
        word("NOTEOPPLYSNINGER - SELSKAP",10,30,500),
        word("Antall arsverk i regnskapsaret",10,70,500),word("10,00",10,90,100)])
    record = dict(period_start="2025-01-01",period_end="2025-12-31",currency="NOK",
        raw={"journalnr":"2026488063"},metrics=dict(revenue=5135536,operating_result=-22366,annual_result=-12695))
    return [cover,financial,workforce],record

def test_recovery_and_explicit_zero():
    pages,record=sample(); out=reconcile(pages,ORG,record)
    assert len(out["financial"])==3 and out["workforce"]["value"]==10
    pages[2]["words"][-1]["text"]="0.00"
    assert reconcile(pages,ORG,record)["workforce"]["value"]==0

def test_wrong_company_period_journal_and_group_rejected():
    for text in ["Organisasjonsnummer: 999999999","Journalnummer: 1234567890",
                 "Arsregnskapets periode: 01.01.2024 - 31.12.2024"]:
        pages,record=sample(); key=text.split(":")[0]
        next(w for w in pages[0]["words"] if w["text"].startswith(key))["text"]=text
        out=reconcile(pages,ORG,record)
        assert out["financial"]==[] and out["workforce"] is None
    pages,record=sample(); pages[1]["words"][1]["text"]="RESULTATREGNSKAP KONSERN"
    assert reconcile(pages,ORG,record)["financial"]==[]

def test_per_claim_conflict_and_ocr_ambiguity():
    pages,record=sample(); pages[1]["words"][5]["text"]="Sum inntekter"
    record["metrics"]["revenue"]+=1
    out=reconcile(pages,ORG,record)
    assert {x["metric"] for x in out["financial"]}=={"operating_result","annual_result"}
    assert out["workforce"]["value"]==10
    pages[2]["words"][-1]["text"]="100"
    assert reconcile(pages,ORG,record)["workforce"] is None
    for value in ["1 00","1O.00","1.00 2.00"]:
        assert decimal_number(value,workforce=True) is None

def test_conflicting_workforce_and_swapped_year_columns():
    pages,record=sample(); other=deepcopy(pages[2]); other["page"]=6; other["words"][-1]["text"]="2.00"
    assert reconcile(pages+[other],ORG,record)["workforce"] is None
    pages[1]["words"][3]["text"]="2024"; pages[1]["words"][4]["text"]="2025"
    assert reconcile(pages,ORG,record)["financial"]==[]

def test_unit_missing_and_endpoint_binding():
    pages,record=sample(); pages[1]["words"][2]["text"]="Amounts"
    out=reconcile(pages,ORG,record)
    assert out["financial"]==[] and out["workforce"] is not None
    url=f"https://data.brreg.no/regnskapsregisteret/regnskap/aarsregnskap/kopi/{ORG}/2025"
    assert _brreg_document_api_url(url,"annual_account_copy")
    for wrong in [url+"?x=1",url.replace("data.brreg.no","evil.example"),url.replace("/2025","/other")]:
        assert not _brreg_document_api_url(wrong,"annual_account_copy")

def test_parent_requires_explicit_standalone_scope_and_joined_ocr_unit_label():
    pages,record=sample(); pages[0]["words"][-1]["text"]="Morselskap i konsern: Ja"
    assert reconcile(pages,ORG,record)["financial"]==[]
    pages[0]["words"].append(word("Konsernregnskap lagt ved: Nei",10,90,600))
    pages[1]["words"][2]["text"]="Belopi:NOK"
    assert len(reconcile(pages,ORG,record)["financial"])==3


def test_balance_sheet_metrics_reconcile_individually():
    pages,record=sample()
    balance=dict(page=3,width=1000,words=[word("Organisasjonsnr: "+ORG,10,10,500),
        word("BALANSE",10,30,500),word("Belop i: TNOK",10,50,200),word("2025",650,50,50),word("2024",850,50,50)])
    labels={"total_assets":"Sum eiendeler","equity":"Sum egenkapital","total_debt":"Sum gjeld",
        "fixed_assets":"Sum anleggsmidler","current_assets":"Sum omlopsmidler",
        "receivables":"Sum fordringer","cash":"Sum bankinnskudd og kontanter",
        "paid_in_equity":"Sum innskutt egenkapital","retained_earnings":"Sum opptjent egenkapital",
        "short_term_debt":"Sum kortsiktig gjeld","long_term_debt":"Sum langsiktig gjeld"}
    for i,(metric,label) in enumerate(labels.items()):
        value=i+1;record["metrics"][metric]=value*1000
        balance['words'] += [word(label,10,90+i*20,400),word(str(value),650,90+i*20,50),word('99',850,90+i*20,50)]
    out=reconcile(pages+[balance],ORG,record)
    values={c['metric']:c['value'] for c in out['financial']}
    assert all(values[m]==record['metrics'][m] for m in labels)
    record['metrics']['equity']+=1
    out=reconcile(pages+[balance],ORG,record)
    assert 'equity' in out['conflicts'] and 'total_assets' in {c['metric'] for c in out['financial']}
    balance['words'][1]['text']='BALANSE - KONSERN'
    assert 'total_assets' not in {c['metric'] for c in reconcile(pages+[balance],ORG,record)['financial']}


def test_extended_income_rows_require_json_and_correct_year():
    pages,record=sample()
    fields={'operating_costs':'Sum kostnader','payroll_costs':'Lonnskostnader',
        'profit_before_tax':'Resultat for skattekostnad','tax_expense':'Skattekostnad pa resultat',
        'net_financial_items':'Netto finans','sales_revenue':'Salgsinntekter',
        'financial_income':'Sum finansinntekter','financial_costs':'Sum finanskostnader',
        'total_comprehensive_result':'Totalresultat'}
    for i,(metric,label) in enumerate(fields.items()):
        record['metrics'][metric]=i*100
        pages[1]['words'] += [word(label,10,170+i*20,400),word(str(i*100),650,170+i*20,50),word('99',850,170+i*20,50)]
    got={c['metric'] for c in reconcile(pages,ORG,record)['financial']}
    assert set(fields)<=got
    record['metrics'].pop('tax_expense')
    assert 'tax_expense' not in {c['metric'] for c in reconcile(pages,ORG,record)['financial']}


def test_explicit_million_scale_and_ambiguous_units():
    from signalpost.annual_accounts import _money_unit, lines
    from decimal import Decimal
    for unit, scale in [("NOK 1 000 000",1000000),("NOK 1.000.000",1000000),
                        ("NOK 1000000",1000000),("NOK millioner",1000000),
                        ("NOK 1 000",1000),("NOK Note",1),("TNOK",1000),("MNOK",1000000)]:
        pages,record=sample()
        pages[1]['words'][2]['text']='Belop i: '+unit
        got=_money_unit(lines(pages[1]))
        assert got is not None and got[:2]==('NOK',Decimal(scale))
    for unit in ['NOK ukjent','NOK 1 000 000 000','TNOK millioner','MNOK tusen']:
        pages,record=sample();pages[1]['words'][2]['text']='Belop i: '+unit
        assert reconcile(pages,ORG,record)['financial']==[]
    # Prove reconciliation uses the corrected scale rather than only the label.
    pages,record=sample();pages[1]['words'][2]['text']='Belop i: NOK 1 000 000'
    record['metrics']['revenue']=2000000;pages[1]['words'][6]['text']='2'
    assert next(c for c in reconcile(pages,ORG,record)['financial'] if c['metric']=='revenue')['value']==2000000


def test_explicit_workforce_variants_and_abstention():
    for text in ['Gjennomsnittlig antall arsverk: 10,00',
                 'Antall arsverk i regnskapsaret 2025 er 10,00',
                 'Selskapet har hatt 10,00 arsverk', 'Tal pa aarsverk i rekneskapsaret: 10,00']:
        pages,record=sample();pages[2]['words']=pages[2]['words'][:2]+[word(text,10,70,800)]
        assert reconcile(pages,ORG,record)['workforce']['value']==10
    for text in ['Antall ansatte: 10,00','Selskapet har ingen ansatte',
                 'Antall arsverk i regnskapsaret 2024 er 10,00',
                 'Konsernet har hatt 10,00 arsverk',
                 'Gjennomsnittlig antall arsverk: 1O,00',
                 'Antall arsverk i regnskapsaret 10,00 12,00']:
        pages,record=sample();pages[2]['words']=pages[2]['words'][:2]+[word(text,10,70,800)]
        assert reconcile(pages,ORG,record)['workforce'] is None
    pages,record=sample();pages[2]['words'][-1]['y1']=300;pages[2]['words'][-1]['y2']=312
    assert reconcile(pages,ORG,record)['workforce'] is None
    pages,record=sample();pages[2]['words'].append(word('Konsern',10,50,100))
    assert reconcile(pages,ORG,record)['workforce'] is None
    pages,record=sample();pages[2]['words'][-1]['confidence']=.5
    assert reconcile(pages,ORG,record)['workforce'] is None


def test_ocr_queue_deadline_and_cache(monkeypatch):
    import asyncio
    import hashlib
    from signalpost.annual_accounts import DocumentProcessor
    async def check():
        processor=DocumentProcessor()
        await processor.slots.acquire();await processor.slots.acquire()
        async def forbidden(*args,**kwargs):
            raise AssertionError('expired queued request must not start a worker')
        monkeypatch.setattr(asyncio,'create_subprocess_exec',forbidden)
        try:
            try:
                await asyncio.wait_for(processor.ocr(b'pdf',.02),timeout=.5)
            except TimeoutError:
                pass
            else:
                raise AssertionError('queued request did not time out')
        finally:
            processor.slots.release();processor.slots.release()
        assert processor.slots._value==2
        processor.cache[hashlib.sha256(b'pdf').hexdigest()]=[{'page':1}]
        assert await processor.ocr(b'pdf',.02)==([{'page':1}],True)
    asyncio.run(check())


def test_ocr_timeout_kills_worker_and_releases_slot(monkeypatch):
    import asyncio
    from signalpost.annual_accounts import DocumentProcessor
    class Worker:
        returncode=None
        killed=False
        async def communicate(self,body):
            await asyncio.Event().wait()
        def kill(self):
            self.killed=True;self.returncode=-9
        async def wait(self):
            return self.returncode
    async def check():
        worker=Worker()
        async def spawn(*args,**kwargs):return worker
        monkeypatch.setattr(asyncio,'create_subprocess_exec',spawn)
        processor=DocumentProcessor()
        try:await processor.ocr(b'pdf',.02)
        except TimeoutError:pass
        else:raise AssertionError('worker did not time out')
        assert worker.killed and processor.slots._value==2 and not processor.cache
    asyncio.run(check())
