"""Offline behavioral tests; no live network, browser or real papers.
Run: python selftest.py --workdir <writable-root>. Keeps isolated fixtures/report.
"""
import argparse, contextlib, io, json, tempfile, urllib.error, zipfile
from pathlib import Path
from unittest.mock import patch
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
import si

TITLE = 'Synthetic electrolyte interface chemistry under controlled experimental conditions'
DOI = '10.1002/adfm.123456'
BASE = 'https://advanced.onlinelibrary.wiley.com'

def pdf(text):
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({NameObject('/Type'):NameObject('/Font'), NameObject('/Subtype'):NameObject('/Type1'), NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
    content = DecodedStreamObject()
    content.set_data(('BT /F1 8 Tf 20 750 Td ('+text+') Tj ET').encode('ascii'))
    page[NameObject('/Contents')] = writer._add_object(content)
    out = io.BytesIO(); writer.write(out)
    return out.getvalue()

def docx(text):
    out = io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('word/document.xml','<w:document xmlns:w="urn:fixture"><w:body><w:p><w:r><w:t>'+text+'</w:t></w:r></w:p></w:body></w:document>')
    return out.getvalue()

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--workdir',required=True); a=ap.parse_args()
    base=Path(a.workdir).resolve(); base.mkdir(parents=True,exist_ok=True)
    root=Path(tempfile.mkdtemp(prefix='si-selftest-',dir=base))
    papers,state,downloads=root/'papers',root/'state',root/'downloads'
    papers.mkdir(); downloads.mkdir(); checks=[]
    original=pdf(TITLE+' DOI: '+DOI)
    for name in ['a.pdf','b.pdf','c.pdf']:(papers/name).write_bytes(original)
    (papers/'SI-existing.pdf').write_bytes(b'untouched')
    def run(name,*argv):
        with contextlib.redirect_stdout(io.StringIO()):si.main([name,'--state',str(state),*argv])
    def project():return si.read(state)
    def check(name,condition):
        assert condition,name
        checks.append(name)
    def add(ids,filename,role='main'):
        run('add-job','--ids',ids,'--url',BASE+'/action/downloadSupplement?doi=10.1002%2Fadfm.123456&file='+filename,
            '--filename',filename,'--evidence-url',BASE+'/doi/'+DOI,'--role',role)
    def ingest():run('ingest','--downloads',str(downloads))
    run('inventory','--folder',str(papers)); p=project()
    check('excludes SI files and does not auto-select first DOI',len(p['papers'])==3 and not any(x['doi'] for x in p['papers']))
    records=root/'confirmed.json'; records.write_text(json.dumps([{'id':f'{i:04d}','doi':DOI,'title':TITLE} for i in range(1,4)]),encoding='utf-8')
    run('set-paper','--records',str(records)); add('0001','main.docx')
    good=docx('Supporting Information '+TITLE+' DOI: '+DOI)
    (downloads/'MAIN (1).DOCX').write_bytes(good); (downloads/'main.docx').write_bytes(good[:35]); ingest()
    check('finds valid numbered uppercase duplicate despite corrupt canonical file',project()['jobs'][0]['status']=='verified')
    add('0002','main.docx'); p=project()
    check('new duplicate original remains incomplete until its output is copied',si.paper_status(p['papers'][1],p)!='complete')
    (papers/'SI-b.docx').write_bytes(b'keep this existing content'); ingest()
    check('copies duplicate DOI without overwriting different existing content',(papers/'SI-b.docx').read_bytes()==b'keep this existing content' and (papers/'SI-b-02.docx').read_bytes()==good)
    jobs=root/'jobs.json'
    jobs.write_text(json.dumps([{'ids':['0001','0002'],'url':BASE+'/action/downloadSupplement?doi=10.1002%2Fadfm.123456&file=main.docx','filename':'main.docx','evidence_url':BASE+'/doi/'+DOI}]),encoding='utf-8')
    run('add-job','--records',str(jobs))
    check('batch job registration merges the same official attachment without duplicating jobs',len(project()['jobs'])==1 and project()['jobs'][0]['paper_ids']==['0001','0002'])
    add('0001','checklist.pdf','checklist'); checklist=pdf('Battery Data Reporting Checklist')
    (downloads/'checklist.pdf').write_bytes(checklist); ingest(); p=project()
    check('unreviewed required checklist blocks complete status',si.paper_status(p['papers'][0],p)=='review')
    run('review','--job','J0002','--file',str(downloads/'checklist.pdf'),'--note','Official paper attachment is the battery data reporting checklist; role and provenance match the synthetic official fixture.')
    (downloads/'checklist.pdf').write_bytes(pdf('Different unreviewed content')); ingest()
    check('manual review does not authorize different bytes',project()['jobs'][1]['status']=='review')
    (downloads/'checklist.pdf').write_bytes(checklist); ingest(); p=project()
    check('reviewed checklist has separate name and main SI is retained',(papers/'SI-a-Checklist.pdf').exists() and si.paper_status(p['papers'][0],p)=='complete')
    fixture=project(); fixture['jobs']=[fixture['jobs'][1]]
    check('checklist alone never counts as main SI',si.paper_status(fixture['papers'][0],fixture)!='complete')
    add('0003','stopped.docx'); (downloads/'stopped.docx.crdownload').write_bytes(good); ingest()
    check('partial downloads are not ingested',project()['jobs'][2]['status']=='planned')
    run('mark','--ids','0003','--status','skipped_user_request','--note','User explicitly stopped this pending fixture.')
    (downloads/'stopped.docx').write_bytes(good); ingest()
    check('later file cannot silently resume a stopped paper',not (papers/'SI-c.docx').exists())
    run('mark','--ids','0003','--status','planned','--note','User explicitly resumed this fixture.'); ingest()
    check('explicit resume permits completion',(papers/'SI-c.docx').exists())
    add('0003','blocked.docx')
    class Blocked:
        def open(self,*args,**kwargs):raise urllib.error.HTTPError('https://example.org',403,'Forbidden',{},None)
    with patch('urllib.request.build_opener',return_value=Blocked()):
        run('fetch','--jobs','J0004'); run('fetch','--jobs','J0004')
    j=project()['jobs'][3]
    check('403 is unverified access, not absence, with no automatic retry',j['status']=='access_unverified' and len(j['attempts'])==1)
    run('mark','--jobs','J0004','--status','skipped_user_request','--note','Intentional failing network fixture.')
    run('export'); run('status'); run('audit','--render')
    report=json.loads((state/'audit.json').read_text(encoding='utf-8'))
    check('hash audit and PDF rendering pass',not report['failures'] and not report['originals_changed_or_missing'] and bool(report['contact_sheets']))
    (papers/'a.pdf').write_bytes(original+b'changed')
    try:run('audit');raise AssertionError('Original tamper was not detected')
    except ValueError:
        check('audit detects modified original PDF',bool(json.loads((state/'audit.json').read_text(encoding='utf-8'))['originals_changed_or_missing']))
    (papers/'a.pdf').write_bytes(original);run('audit','--render')
    report={'passed':len(checks),'checks':checks,'fixture_dir':str(root),'contact_sheets':json.loads((state/'audit.json').read_text(encoding='utf-8'))['contact_sheets']}
    si.atomic_json(root/'selftest-report.json',report);si.emit(report)

if __name__=='__main__':main()
