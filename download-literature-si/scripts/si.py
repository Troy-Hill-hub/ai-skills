#!/usr/bin/env python3
"""Portable SI inventory, download reconciliation, source-bound verification and audit.
No credentials, browser profiles, browser automation or guessed publisher URLs.
"""
from __future__ import annotations
import argparse, contextlib, hashlib, importlib.metadata, io, json, os
from pathlib import Path
import re, sys, time, unicodedata, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
import zipfile

HOSTS = set('onlinelibrary.wiley.com advanced.onlinelibrary.wiley.com pubs.acs.org acs.figshare.com api.figshare.com ndownloader.figshare.com www.sciencedirect.com ars.els-cdn.com api.elsevier.com pubs.rsc.org www.nature.com link.springer.com static-content.springer-cdn.com media.springernature.com pmc.ncbi.nlm.nih.gov www.ebi.ac.uk pmc-oa-opendata.s3.amazonaws.com api.crossref.org doi.org'.split())
DOI = re.compile(r'10\.\d{4,9}/[-A-Z0-9._;()/:]+', re.I)
CLOSED = {'skipped_user_request', 'no_si_confirmed'}

def emit(x):
    print(json.dumps(x, ensure_ascii=False, indent=2))

def norm(x):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(x)).casefold() if c.isalnum())

def digest(data):
    return hashlib.sha256(data).hexdigest()

def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1024**2), b''):
            h.update(b)
    return h.hexdigest()

def clean_doi(x):
    x = urllib.parse.unquote(str(x or '')).strip().lower()
    x = re.sub(r'^https?://(?:dx\.)?doi\.org/', '', x).rstrip('.,;')
    while x.endswith(')') and x.count(')') > x.count('('):
        x = x[:-1]
    return x

def atomic_json(path, x):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(x, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, path)

@contextlib.contextmanager
def lock(state):
    state = Path(state)
    state.mkdir(parents=True, exist_ok=True)
    path = state / '.writer.lock'
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ValueError(f'Project locked: {path}. Inspect its PID before removing a stale lock.')
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        path.unlink(missing_ok=True)

def read(state):
    p = json.loads((Path(state) / 'project.json').read_text(encoding='utf-8'))
    if p.get('version') != 1:
        raise ValueError('Unsupported project version')
    return p

def save(state, p):
    atomic_json(Path(state) / 'project.json', p)

def split_ids(x):
    return [s.strip() for s in (x or '').split(',') if s.strip()]

def select(rows, wanted):
    if not wanted:
        return list(rows)
    unknown = set(wanted) - {r['id'] for r in rows}
    if unknown:
        raise ValueError(f'Unknown IDs: {sorted(unknown)}')
    return [r for r in rows if r['id'] in wanted]

def safe_url(url, hosts):
    if re.search(r'[\s\x00-\x1f"<>]', url):
        raise ValueError('URL has whitespace/unsafe characters; use the actual encoded href')
    u = urllib.parse.urlsplit(url)
    if u.scheme != 'https' or not u.hostname or u.username or u.password:
        raise ValueError('Only HTTPS without embedded credentials is accepted')
    if u.hostname.lower() not in hosts:
        raise ValueError(f'Host {u.hostname} not registered; verify provenance, then use allow-host')
    return u

class CheckedRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, hosts):
        self.hosts = hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        safe_url(newurl, self.hosts)
        return super().redirect_request(req, fp, code, msg, headers, newurl)

def inspect_document(data):
    """Integrity only. A manual exception never bypasses this check."""
    if data.startswith(b'%PDF-'):
        from pypdf import PdfReader
        if b'%%EOF' not in data[-4096:]:
            raise ValueError('PDF has no terminal EOF marker')
        doc = PdfReader(io.BytesIO(data))
        if doc.is_encrypted or not len(doc.pages):
            raise ValueError('Empty/encrypted PDF requires separate handling')
        for page in doc.pages:
            _ = page.mediabox
        return {'format': 'pdf', 'pages': len(doc.pages)}, '\n'.join(x.extract_text() or '' for x in doc.pages[:3])
    if data.startswith(b'PK'):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if 'word/document.xml' not in z.namelist():
                raise ValueError('ZIP is not DOCX; inspect archives separately')
            if sum(x.file_size for x in z.infolist()) > 1024**3:
                raise ValueError('DOCX expands beyond 1 GiB; inspect separately')
            if z.testzip() is not None:
                raise ValueError('DOCX CRC failed')
            text = ''.join(ET.fromstring(z.read('word/document.xml')).itertext())
            return {'format': 'docx', 'images': sum(x.startswith('word/media/') for x in z.namelist())}, text[:30000]
    raise ValueError('Not PDF/DOCX: HTML, legacy DOC and other formats require separate handling')

def validate(data, paper, job, p):
    detail, text = inspect_document(data)
    review = p['reviews'].get(job['id'], {})
    manual = (review.get('sha256') == digest(data) and review.get('url') == job['url']
              and review.get('evidence_url') == job['evidence_url'])
    title = norm(paper.get('title', ''))
    title_match = len(title) >= 20 and title in norm(text)
    # Keep DOI identity away from a long SI reference list; ambiguous files need review.
    dois = {clean_doi(x) for x in DOI.findall(re.sub(r'(?<=\S)\n(?=\S)', '', text[:3000]))}
    doi_match = bool(paper.get('doi')) and clean_doi(paper['doi']) in dois
    heading = any(x in norm(text) for x in ['supportinginformation', 'supplementaryinformation',
        'supplementalmaterial', 'supplementarymaterial', 'electronicsupplementary', 'supportingmaterial'])
    if job['role'] == 'checklist':
        if not manual:
            raise ValueError('Checklist needs source-bound manual review and cannot replace main SI')
    elif not manual and not (heading and (title_match or doi_match)):
        raise ValueError('SI identity/heading not established; inspect original and record review')
    detail.update(sha256=digest(data), bytes=len(data), doi_match=doi_match,
                  title_match=title_match, si_heading=heading)
    if manual:
        detail['manual_review'] = review['note']
    return detail

def inventory(a):
    from pypdf import PdfReader
    root = Path(a.folder).resolve()
    if (Path(a.state) / 'project.json').exists():
        raise ValueError('State already exists; resume it or choose a new directory')
    paths = root.rglob('*') if a.recursive else root.iterdir()
    files = sorted((f for f in paths if f.is_file() and f.suffix.lower() == '.pdf'
        and not f.name.lower().startswith('si-')), key=lambda f: str(f).casefold())
    if not files:
        raise ValueError('No original PDFs found')
    papers = []
    for n, f in enumerate(files, 1):
        row = {'id': f'{n:04d}', 'relative_path': str(f.relative_to(root)), 'stem': f.stem,
            'original_sha256': file_hash(f), 'bytes': f.stat().st_size, 'doi': '', 'title': '', 'note': ''}
        try:
            doc = PdfReader(f)
            text = '\n'.join(x.extract_text() or '' for x in doc.pages[:2])
            row.update(pages=len(doc.pages), first_text=text[:12000],
                title_metadata=str((doc.metadata or {}).get('/Title', '')),
                doi_candidates=list(dict.fromkeys(clean_doi(x) for x in DOI.findall(text))))
            urls = []
            for page in doc.pages:
                for ref in page.get('/Annots', []):
                    action = ref.get_object().get('/A')
                    action = action.get_object() if hasattr(action, 'get_object') else action
                    if action and action.get('/URI'):
                        urls.append(str(action['/URI']))
            row['embedded_urls'] = list(dict.fromkeys(urls))
        except Exception as e:
            row['inventory_error'] = str(e)
        papers.append(row)
    save(a.state, {'version': 1, 'root': str(root), 'created_at': time.time(),
        'allowed_hosts': sorted(HOSTS), 'papers': papers, 'jobs': [], 'reviews': {}})
    emit({'original_pdfs': len(papers), 'next': 'Confirm DOI candidates using set-paper, then run metadata.'})

def set_paper(a, p):
    records = json.loads(Path(a.records).read_text(encoding='utf-8')) if a.records else [vars(a)]
    for record in records:
        paper = select(p['papers'], [record['id']])[0]
        if record.get('doi'):
            doi = clean_doi(record['doi'])
            if not DOI.fullmatch(doi):
                raise ValueError('Invalid DOI')
            if doi != paper['doi'] and any(paper['id'] in j['paper_ids'] for j in p['jobs']):
                raise ValueError('Cannot change DOI after registering jobs')
            paper['doi'] = doi
        for key in ['title', 'note']:
            if record.get(key):
                paper[key] = record[key].strip()

def metadata(a, p):
    for paper in select(p['papers'], split_ids(a.ids)):
        if not paper['doi']:
            continue
        url = 'https://api.crossref.org/works/' + urllib.parse.quote(paper['doi'], safe='/')
        try:
            request = urllib.request.Request(url, headers={'User-Agent': 'Literature-SI-Workflow/1.0', 'Accept': 'application/json'})
            with urllib.request.urlopen(request, timeout=20) as res:
                record = json.load(res)['message']
            if clean_doi(record.get('DOI')) != paper['doi']:
                raise ValueError('Crossref DOI mismatch')
            paper['crossref'] = {'title': record.get('title', [''])[0],
                'url': record.get('resource', {}).get('primary', {}).get('URL', ''), 'links': record.get('link', [])}
            if not paper['title']:
                paper['title'] = paper['crossref']['title']
            emit({'id': paper['id'], 'title': paper['title']})
        except Exception as e:
            emit({'id': paper['id'], 'error': str(e)})
        time.sleep(.2)

def add_job(a, p):
    if a.records:
        records = json.loads(Path(a.records).read_text(encoding='utf-8'))
        for row in records:
            data = {'records': None, 'role': 'main', 'label': None, 'optional': False, **row}
            if isinstance(data.get('ids'), list):
                data['ids'] = ','.join(data['ids'])
            for key in ['ids', 'url', 'filename', 'evidence_url']:
                if not data.get(key):
                    raise ValueError(f'Job record missing {key}')
            add_job(argparse.Namespace(**data), p)
        return
    if not all([a.ids, a.url, a.filename, a.evidence_url]):
        raise ValueError('Supply --records or all of --ids, --url, --filename, --evidence-url')
    papers = select(p['papers'], split_ids(a.ids))
    if not papers or any(not x['doi'] for x in papers) or len({x['doi'] for x in papers}) != 1:
        raise ValueError('One job needs confirmed papers belonging to exactly one DOI')
    u = safe_url(a.url, p['allowed_hosts'])
    safe_url(a.evidence_url, p['allowed_hosts'])
    q = urllib.parse.parse_qs(u.query).get('doi', [])
    if q and clean_doi(q[0]) != papers[0]['doi']:
        raise ValueError('URL DOI differs from paper DOI')
    source_filename = urllib.parse.parse_qs(u.query).get('file', [])
    if source_filename and source_filename[0].lower() != a.filename.lower():
        raise ValueError('URL file parameter differs from registered attachment filename')
    if not a.filename or Path(a.filename).name != a.filename or re.search(r'[<>:"/\\|?*\x00-\x1f]', a.filename):
        raise ValueError('Use the official attachment basename')
    if Path(a.filename).suffix.lower() not in {'.pdf', '.docx'}:
        raise ValueError('Helper accepts PDF/DOCX only; process other formats separately')
    if a.label and not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', a.label):
        raise ValueError('Use a 1-40 character alphanumeric, hyphen or underscore label')
    for job in p['jobs']:
        if job['url'] == a.url:
            if job['doi'] != papers[0]['doi']:
                raise ValueError('URL already assigned to another DOI')
            job['paper_ids'] = sorted(set(job['paper_ids']) | {x['id'] for x in papers})
            emit({'merged_job': job['id']})
            return
    job = {'id': f'J{len(p["jobs"])+1:04d}', 'doi': papers[0]['doi'],
        'paper_ids': [x['id'] for x in papers], 'url': a.url, 'filename': a.filename,
        'evidence_url': a.evidence_url, 'role': a.role, 'label': a.label or '',
        'required': not a.optional, 'status': 'planned', 'attempts': [], 'outputs': []}
    p['jobs'].append(job)
    emit({'job': job['id']})

def eligible(job, p):
    return job['status'] not in CLOSED and any(x.get('disposition') not in CLOSED for x in select(p['papers'], job['paper_ids']))

def accept(data, source, job, p):
    if not eligible(job, p):
        raise ValueError('Closed job requires explicit resume')
    papers = [x for x in select(p['papers'], job['paper_ids']) if x.get('disposition') not in CLOSED]
    checks = {x['id']: validate(data, x, job, p) for x in papers}
    if any('.' + d['format'] != Path(job['filename']).suffix.lower() for d in checks.values()):
        raise ValueError('Extension differs from actual format; inspect and correct the job first')
    active_ids = {x['id'] for x in papers}
    artifacts = [x for x in job['outputs'] if x['paper_id'] not in active_ids]
    for paper in papers:
        detail = checks[paper['id']]
        folder = Path(p['root']) / Path(paper['relative_path']).parent
        label = job['label'] or ('Checklist' if job['role'] == 'checklist' else '')
        base = 'SI-' + paper['stem'] + ('-' + label if label else '')
        dest = folder / (base + '.' + detail['format'])
        n = 2
        while dest.exists() and file_hash(dest) != detail['sha256']:
            dest = folder / (base + f'-{n:02d}.' + detail['format'])
            n += 1
        if not dest.exists():
            with dest.open('xb') as f:
                f.write(data)
        artifacts.append({'paper_id': paper['id'], 'path': str(dest.resolve()),
            'source_file': str(source), 'validation': detail})
    job.update(status='verified', outputs=artifacts, verified_at=time.time())
    job.pop('error', None)

def fetch(a, p):
    opener = urllib.request.build_opener(CheckedRedirect(p['allowed_hosts']))
    for job in select(p['jobs'], split_ids(a.jobs)):
        if not eligible(job, p) or job['status'] == 'verified' or (job['status'] != 'planned' and not a.retry):
            continue
        try:
            safe_url(job['url'], p['allowed_hosts'])
            started = time.monotonic()
            request = urllib.request.Request(job['url'], headers={'User-Agent': 'Mozilla/5.0'})
            with opener.open(request, timeout=20) as res:
                chunks, total = [], 0
                while True:
                    b = res.read(262144)
                    if not b:
                        break
                    chunks.append(b)
                    total += len(b)
                    if total > a.max_mb * 1024**2 or time.monotonic() - started > a.deadline:
                        raise TimeoutError('Transfer limit reached; switch to browser or explicitly adjust limits')
            data = b''.join(chunks)
            if data.lstrip().startswith(b'<'):
                raise ValueError('HTML response instead of attachment; access remains unverified')
            raw = Path(a.state) / 'raw' / (job['id'] + '-' + job['filename'])
            raw.parent.mkdir(exist_ok=True)
            raw.write_bytes(data)
            try:
                accept(data, raw, job, p)
            except Exception as e:
                job.update(status='review', error=str(e), review_file=str(raw.resolve()))
        except Exception as e:
            job.update(status='access_unverified', error=str(e))
        job['attempts'].append({'method': 'http', 'time': time.time(), 'status': job['status'], 'error': job.get('error')})
        save(a.state, p)
        emit({'job': job['id'], 'status': job['status'], 'error': job.get('error')})

def find_files(job, directories):
    name = Path(job['filename'])
    pattern = re.compile(re.escape(name.stem) + r'(?: \(\d+\))?' + re.escape(name.suffix), re.I)
    found = []
    for folder in directories:
        root = Path(folder).expanduser().resolve()
        if root.is_dir():
            found.extend(f for f in root.iterdir() if f.is_file() and pattern.fullmatch(f.name))
    return sorted(set(found), key=lambda f: f.stat().st_mtime, reverse=True)

def ingest(a, p):
    result = {'accepted': [], 'waiting': [], 'review': [], 'skipped': []}
    for job in select(p['jobs'], split_ids(a.jobs)):
        if not eligible(job, p):
            result['skipped'].append(job['id'])
            continue
        active_ids = {x['id'] for x in select(p['papers'], job['paper_ids']) if x.get('disposition') not in CLOSED}
        if job['status'] == 'verified' and active_ids <= {x['paper_id'] for x in job['outputs']}:
            continue
        files = find_files(job, a.downloads)
        if job['status'] == 'verified':
            files += [Path(x['path']) for x in job['outputs'] if Path(x['path']).is_file() and Path(x['path']) not in files]
        if not files:
            result['waiting'].append(job['id'])
            continue
        errors = []
        for file in files:
            try:
                before = file.stat()
                data = file.read_bytes()
                after = file.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise ValueError('File still changing')
                accept(data, file, job, p)
                result['accepted'].append(job['id'])
                break
            except Exception as e:
                errors.append({'file': str(file), 'error': str(e)})
        else:
            job.update(status='review', error=errors)
            result['review'].append({'job': job['id'], 'errors': errors})
    atomic_json(Path(a.state) / 'last-ingest.json', result)
    emit(result)

def review(a, p):
    job = select(p['jobs'], [a.job])[0]
    if len(a.note.strip()) < 40:
        raise ValueError('Record concrete official-source/original-paper evidence, at least 40 characters')
    data = Path(a.file).read_bytes()
    inspect_document(data)
    p['reviews'][job['id']] = {'sha256': digest(data), 'url': job['url'],
        'evidence_url': job['evidence_url'], 'note': a.note, 'time': time.time()}
    emit({'review_recorded': job['id'], 'next': 'Run ingest again; review itself copies no files.'})

def mark(a, p):
    if not a.jobs and not a.ids:
        raise ValueError('Specify --jobs or --ids explicitly')
    if a.jobs:
        for job in select(p['jobs'], split_ids(a.jobs)):
            if job['status'] == 'verified' and a.status != 'planned':
                raise ValueError('Keep verified artifacts; cannot label them as absent/skipped')
            job.update(status=a.status, note=a.note)
    if a.ids:
        for paper in select(p['papers'], split_ids(a.ids)):
            paper.update(disposition=a.status if a.status in CLOSED else '', note=a.note)

def paper_status(paper, p):
    if paper.get('disposition') in CLOSED:
        return paper['disposition']
    jobs = [j for j in p['jobs'] if paper['id'] in j['paper_ids']]
    if not jobs:
        return 'si_availability_unverified'
    def has_output(j):
        return j['status'] == 'verified' and any(x['paper_id'] == paper['id'] for x in j['outputs'])
    main = any(j['role'] == 'main' and has_output(j) for j in jobs)
    if main and all(has_output(j) for j in jobs if j['required']):
        return 'complete'
    if any(j['status'] == 'skipped_user_request' for j in jobs):
        return 'skipped_user_request'
    if any(j['status'] == 'review' for j in jobs):
        return 'review'
    return 'incomplete'

def status(a, p):
    rows, counts = [], {}
    for paper in p['papers']:
        s = paper_status(paper, p)
        counts[s] = counts.get(s, 0) + 1
        outputs = [x['path'] for j in p['jobs'] for x in j['outputs'] if x['paper_id'] == paper['id']]
        notes = [paper.get('note', '')] + [j.get('note', '') for j in p['jobs'] if paper['id'] in j['paper_ids']]
        rows.append({'id': paper['id'], 'paper': paper['relative_path'], 'doi': paper['doi'],
            'status': s, 'note': '; '.join(x for x in notes if x), 'outputs': outputs})
    summary = {'original_pdfs': len(rows), 'unique_confirmed_dois': len({x['doi'] for x in p['papers'] if x['doi']}),
        'unconfirmed_dois': sum(not x['doi'] for x in p['papers']),
        'si_artifact_files': len({x['path'] for j in p['jobs'] for x in j['outputs']}),
        'paper_status_counts': counts, 'attachment_jobs': len(p['jobs']),
        'verified_jobs': sum(j['status'] == 'verified' for j in p['jobs'])}
    atomic_json(Path(a.state) / 'SI下载记录.json', {'summary': summary, 'papers': rows, 'jobs': p['jobs'], 'reviews': p['reviews']})
    def cell(x):
        return str(x).replace('|', '\\|').replace('\n', ' ')
    lines = ['# SI 下载清单', '', json.dumps(summary, ensure_ascii=False), '',
        '完成数按原始 PDF 计算；同 DOI 原文分别保留。Checklist 单独存在不算主 SI 完成。', '',
        '| ID | 原文 | DOI | 状态 | 说明 | 已核验附件 |', '| --- | --- | --- | --- | --- | --- |']
    for row in rows:
        values = [row[k] for k in ['id', 'paper', 'doi', 'status', 'note']] + ['；'.join(row['outputs'])]
        lines.append('| ' + ' | '.join(cell(x) for x in values) + ' |')
    (Path(a.state) / 'SI下载清单.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    emit(summary)

def export(a, p):
    jobs = [j for j in select(p['jobs'], split_ids(a.jobs)) if eligible(j, p) and j['status'] not in {'verified', 'review'}]
    path = Path(a.state) / 'browser-jobs.json'
    atomic_json(path, {'version': 1, 'allowed_hosts': p['allowed_hosts'],
        'jobs': [{'id': j['id'], 'url': j['url'], 'filename': j['filename']} for j in jobs]})
    emit({'ledger': str(path.resolve()), 'jobs': len(jobs)})

def audit(a, p):
    changed, failures, verified, images = [], [], set(), []
    for paper in p['papers']:
        f = Path(p['root']) / paper['relative_path']
        if not f.is_file() or file_hash(f) != paper['original_sha256']:
            changed.append(str(f))
    qa = Path(a.state) / 'qa'
    if a.render:
        import pypdfium2 as pdfium
        from PIL import Image, ImageDraw
        qa.mkdir(exist_ok=True)
    for job in p['jobs']:
        for output in job['outputs']:
            try:
                f = Path(output['path'])
                data = f.read_bytes()
                if digest(data) != output['validation']['sha256']:
                    raise ValueError('Output hash changed')
                paper = select(p['papers'], [output['paper_id']])[0]
                validate(data, paper, job, p)
                if a.render and f.suffix.lower() == '.pdf':
                    doc = pdfium.PdfDocument(str(f))
                    for n in sorted({0, len(doc) - 1}):
                        page = doc[n]
                        img = page.render(scale=.6).to_pil().convert('RGB')
                        img.thumbnail((320, 420))
                        target = qa / f'{job["id"]}-{paper["id"]}-{n+1}.png'
                        img.save(target)
                        images.append(target)
                        page.close()
                    doc.close()
                verified.add(str(f))
            except Exception as e:
                failures.append({'job': job['id'], 'output': output['path'], 'error': str(e)})
    sheets = []
    if a.render:
        for start in range(0, len(images), 16):
            canvas = Image.new('RGB', (1360, 1800), '#e5e7eb')
            draw = ImageDraw.Draw(canvas)
            for i, f in enumerate(images[start:start+16]):
                x, y = i % 4 * 340, i // 4 * 450
                with Image.open(f) as img:
                    canvas.paste(img, (x + (340-img.width)//2, y+25))
                draw.text((x+5, y+3), f.stem, fill='black')
            target = qa / f'contact-{start//16+1}.jpg'
            canvas.save(target, quality=90)
            sheets.append(str(target.resolve()))
    report = {'originals_changed_or_missing': changed, 'verified_artifacts': len(verified),
        'failures': failures, 'contact_sheets': sheets,
        'visual_review': 'Agent must inspect contact sheets' if a.render else 'Not rendered in this audit'}
    atomic_json(Path(a.state) / 'audit.json', report)
    emit(report)
    if changed or failures:
        raise ValueError('Audit failed; see audit.json')

def doctor():
    packages = {}
    for name in ['pypdf', 'pypdfium2', 'Pillow']:
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = 'missing'
    emit({'python': sys.executable, 'version': sys.version, 'os': sys.platform, 'packages': packages,
        'core_ready': packages['pypdf'] != 'missing', 'browser': 'Use the agent environment supported interface; no SDK is bundled.'})

def parser():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='command', required=True)
    sub.add_parser('doctor')
    for name in ['inventory', 'set-paper', 'metadata', 'add-job', 'allow-host', 'fetch', 'ingest', 'review', 'mark', 'status', 'export', 'audit']:
        s = sub.add_parser(name)
        s.add_argument('--state', required=True, help='Project state directory, not a JSON filename')
        if name == 'inventory':
            s.add_argument('--folder', required=True)
            s.add_argument('--recursive', action='store_true')
        elif name == 'set-paper':
            g = s.add_mutually_exclusive_group(required=True)
            g.add_argument('--id')
            g.add_argument('--records', help='JSON list of confirmed {id,doi,title,note} records')
            for flag in ['doi', 'title', 'note']:
                s.add_argument('--' + flag)
        elif name == 'metadata':
            s.add_argument('--ids')
        elif name == 'add-job':
            s.add_argument('--records', help='JSON list of confirmed attachment records')
            for flag in ['ids', 'url', 'filename', 'evidence-url']:
                s.add_argument('--' + flag)
            s.add_argument('--role', choices=['main', 'checklist', 'extra'], default='main')
            s.add_argument('--label')
            s.add_argument('--optional', action='store_true')
        elif name == 'allow-host':
            s.add_argument('--host', required=True)
            s.add_argument('--evidence-url', required=True)
        elif name in ['fetch', 'ingest', 'export']:
            s.add_argument('--jobs')
            if name == 'fetch':
                s.add_argument('--retry', action='store_true')
                s.add_argument('--max-mb', type=int, default=256)
                s.add_argument('--deadline', type=int, default=180)
            if name == 'ingest':
                s.add_argument('--downloads', nargs='+', required=True)
        elif name == 'review':
            for flag in ['job', 'file', 'note']:
                s.add_argument('--' + flag, required=True)
        elif name == 'mark':
            s.add_argument('--ids')
            s.add_argument('--jobs')
            s.add_argument('--status', choices=['skipped_user_request', 'no_si_confirmed', 'planned'], required=True)
            s.add_argument('--note', required=True)
        elif name == 'audit':
            s.add_argument('--render', action='store_true')
    return ap

def main(argv=None):
    a = parser().parse_args(argv)
    if a.command == 'doctor':
        doctor()
        return
    with lock(a.state):
        if a.command == 'inventory':
            inventory(a)
            return
        p = read(a.state)
        if a.command == 'allow-host':
            host = a.host.lower().strip()
            if not re.fullmatch(r'[a-z0-9][a-z0-9.-]+\.[a-z]{2,}', host):
                raise ValueError('Use a DNS hostname, not URL/IP')
            safe_url(a.evidence_url, p['allowed_hosts'])
            p['allowed_hosts'] = sorted(set(p['allowed_hosts']) | {host})
            p.setdefault('host_evidence', {})[host] = a.evidence_url
        else:
            functions = {'set-paper': set_paper, 'metadata': metadata, 'add-job': add_job,
                'fetch': fetch, 'ingest': ingest, 'review': review, 'mark': mark,
                'status': status, 'export': export, 'audit': audit}
            functions[a.command](a, p)
        save(a.state, p)

if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, ImportError, KeyError, zipfile.BadZipFile) as e:
        print(f'ERROR: {e}', file=sys.stderr)
        sys.exit(2)
