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
