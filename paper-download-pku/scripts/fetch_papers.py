#!/usr/bin/env python
"""按 DOI 批量下载期刊全文 PDF（本机专用）。

用法示例：
  # 1) 首次（或会话过期）登录 ScienceDirect（CARSI / 北大 IAAA）
  python fetch_papers.py sd-login

  # 2) 从 Excel 清单批量下载（按列名映射目录与文件名）
  python fetch_papers.py from-xlsx --xlsx "D:/AgentsLocal/无负极钠电文献_去重与重新分类.xlsx" \
      --sheet 文献总表 --out-root "D:/AgentsLocal/无负极钠电文献_分类全文"

  # 3) 从 JSON 清单下载
  python fetch_papers.py from-json --json manifest.json --out-root ./pdfs

  # 4) 只下某几篇 / 限定数量 / 指定出版商
  python fetch_papers.py from-json --json m.json --out-root ./pdfs --only AFNa-060 AFNa-079
  python fetch_papers.py from-json --json m.json --out-root ./pdfs --doi-prefix 10.1002

解释器：C:\\Users\\<用户名>\\.workbuddy\\binaries\\python\\envs\\default\\Scripts\\python.exe
依赖：playwright（已装 chromium + 系统 Chrome）、pypdf、openpyxl
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
import sys
import time
import urllib.request

from playwright.async_api import async_playwright

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

DEFAULT_PROFILE = os.path.join(os.path.expanduser("~"), ".workbuddy", "cache", "paper-download-profile")

# 每个出版商的请求间隔（秒）。ScienceDirect 过于密集会 429，必须放宽。
SPACING = {"10.1002": (4, 8), "10.1039": (8, 12), "10.1038": (5, 9),
           "10.1126": (12, 18), "10.1016": (25, 40), "10.1021": (10, 15), "*": (6, 10)}

BLOCK_WORDS = ["are you a robot", "captcha", "problem providing the content",
               "performing security verification", "unusual traffic", "请稍候"]


# ---------------------------------------------------------------- 基础工具

def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def safe_fn(s: str) -> str:
    s = re.sub(r'[\\/:*?"<>|]', " ", str(s))
    return re.sub(r"\s+", " ", s).strip()


def target_path(rec: dict, out_root: str) -> str:
    sub = safe_fn(rec.get("dir") or "")
    year = re.sub(r"\D", "", str(rec.get("year") or ""))[:4]
    title = safe_fn(rec.get("title") or "")[:116].strip()
    name = f"{rec.get('id')}_{year}_{title}.pdf" if rec.get("id") else f"{title}.pdf"
    return os.path.join(out_root, sub, safe_fn(name)) if sub else os.path.join(out_root, safe_fn(name))


def pdf_ok(path: str, min_pages: int = 2, min_size: int = 60000) -> bool:
    """校验是不是完整 PDF（截断/HTML 错误页都会在这里被拦下）。"""
    if not os.path.exists(path) or os.path.getsize(path) < min_size:
        return False
    try:
        with open(path, "rb") as f:
            if f.read(4) != b"%PDF":
                return False
    except OSError:
        return False
    try:
        from pypdf import PdfReader
        return len(PdfReader(path, strict=False).pages) >= min_pages
    except Exception:
        return False


def ensure_pdf_external(profile_dir: str) -> None:
    """让 Chrome 下载 PDF 而不是内嵌预览（download 事件才抓得到）。"""
    pref = os.path.join(profile_dir, "Default", "Preferences")
    if not os.path.exists(pref):
        return
    try:
        with open(pref, encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("plugins", {})["always_open_pdf_externally"] = True
        with open(pref, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass


def crossref_pii(doi: str) -> str | None:
    """Elsevier DOI → PII（文章页地址要用的 S 开头编号）。"""
    try:
        req = urllib.request.Request(f"https://api.crossref.org/works/{doi}",
                                     headers={"User-Agent": "paper-download/1.0 (mailto:none@example.com)"})
        msg = json.load(urllib.request.urlopen(req, timeout=30))["message"]
        for alt in msg.get("alternative-id") or []:
            if alt.startswith("S"):
                return alt
        for link in msg.get("link") or []:
            m = re.search(r"PII:(S\d+)", link.get("URL", ""))
            if m:
                return m.group(1)
    except Exception:
        return None
    return None


def publisher_urls(doi: str) -> list[str]:
    """各出版商可直连的 PDF 地址（按成功率高到低）。"""
    u: list[str] = []
    if doi.startswith("10.1002"):          # Wiley
        u.append(f"https://onlinelibrary.wiley.com/doi/pdfdirect/{doi}?download=true")
    elif doi.startswith("10.1039"):        # RSC
        m = re.match(r"10\.1039/[a-z](\d)([a-z]{2})", doi)
        if m:
            u.append(f"https://pubs.rsc.org/en/content/articlepdf/{2000 + int(m.group(1))}"
                     f"/{m.group(2)}/{doi.split('/')[1]}")
    elif doi.startswith("10.1038"):        # Nature / Springer
        u.append(f"https://link.springer.com/content/pdf/{doi}.pdf")
        u.append(f"https://www.nature.com/articles/{doi.split('/', 1)[1]}.pdf")
    elif doi.startswith("10.1126"):        # Science / AAAS
        u.append(f"https://www.science.org/doi/pdf/{doi}?download=true")
    elif doi.startswith("10.1021"):        # ACS
        u.append(f"https://pubs.acs.org/doi/pdf/{doi}?download=true")
    return u


# ---------------------------------------------------------------- 下载核心

async def grab(page, ctx, url: str, out: str, timeout_s: int = 45) -> str | None:
    """导航到 url 并把 PDF 落到 out。返回说明字符串，失败返回 None。"""
    dls: list = []
    state = {"html": False}

    def on_dl(d):
        dls.append(d)

    async def on_resp(resp):
        try:
            ct = (resp.headers.get("content-type") or "").lower()
            if resp.request.resource_type == "document" and "text/html" in ct:
                state["html"] = True
            if "application/pdf" in ct:
                await resp.finished()
                body = await resp.body()
                if body[:4] == b"%PDF" and len(body) > 60000:
                    with open(out + ".part", "wb") as f:
                        f.write(body)
                    os.replace(out + ".part", out)
        except Exception:
            pass

    page.on("download", on_dl)
    page.on("response", lambda r: asyncio.ensure_future(on_resp(r)))
    try:
        await page.goto(url, timeout=timeout_s * 1000)
    except Exception:
        pass
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        await page.wait_for_timeout(700)
        if dls:
            try:
                await dls[0].save_as(out)
            except Exception:
                pass
            if pdf_ok(out):
                break
        if pdf_ok(out):
            break
        if state["html"] and not dls:
            await page.wait_for_timeout(1500)
            if not dls and not pdf_ok(out):
                break
    page.remove_listener("download", on_dl)
    if pdf_ok(out):
        return f"{'download' if dls else 'response'} {os.path.getsize(out) // 1024}KB"
    if os.path.exists(out):
        os.remove(out)
    return None


async def page_blocked(page) -> bool:
    try:
        title = (await page.title()).lower()
        body = (await page.inner_text("body"))[:800].lower()
    except Exception:
        return True
    return any(w in body or w in title for w in BLOCK_WORDS)


async def pmc_pdf(page, ctx, doi: str, out: str) -> str | None:
    """Europe PMC / PMC 兜底（适合 Science Advances 等 OA 文章）。"""
    try:
        raw = await page.evaluate("""async (doi) => {
            const u = "https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=DOI:%22"
                    + encodeURIComponent(doi) + "%22&format=json&resultType=core";
            const r = await fetch(u); return await r.text();
        }""", doi)
        res = json.loads(raw).get("resultList", {}).get("result", [])
        if not res:
            return None
        pmcid = res[0].get("pmcid")
        if not pmcid:
            return None
        for url in (f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/pdf/",
                    f"https://europepmc.org/articles/{pmcid}?pdf=render"):
            how = await grab(page, ctx, url, out, timeout_s=40)
            if how:
                return f"pmc {how}"
    except Exception:
        return None
    return None


async def fetch_elsevier(page, ctx, rec: dict, out: str) -> str:
    """ScienceDirect：依赖已登录的 CARSI 会话；靠点击 View PDF 触发下载。"""
    pii = rec.get("pii") or crossref_pii(rec["doi"])
    if not pii:
        return "no-pii"
    await page.goto(f"https://www.sciencedirect.com/science/article/pii/{pii}",
                    wait_until="domcontentloaded", timeout=90000)
    await page.wait_for_timeout(2500)
    body = (await page.inner_text("body"))[:800]
    if "Brought to you by" not in body:
        return "no-session（先跑 sd-login）"
    dls: list = []
    h = lambda d: dls.append(d)
    page.on("download", h)
    try:
        await page.click("a:has-text('View PDF')", timeout=20000)
    except Exception:
        pass
    for _ in range(60):
        await page.wait_for_timeout(1000)
        if dls:
            break
        if pdf_ok(out):
            break
    page.remove_listener("download", h)
    for extra in ctx.pages[1:]:
        try:
            await extra.close()
        except Exception:
            pass
    if dls:
        try:
            src = await dls[0].path()
            if src and os.path.exists(src):
                size = os.path.getsize(src)
                with open(src, "rb") as f:
                    head = f.read(4)
                if head == b"%PDF" and size > 60000:
                    with open(out, "wb") as f:
                        f.write(open(src, "rb").read())
                    return f"ok {size // 1024}KB"
                return f"notpdf {size}B（多为 429 限流，需冷却 15-30 分钟）"
        except Exception as e:
            return f"dl-{type(e).__name__}"
    return "no-download"


async def process(ctx, rec: dict, out: str) -> tuple[bool, str]:
    if pdf_ok(out):
        return True, "exists"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    doi = str(rec.get("doi") or "").strip()
    page = await ctx.new_page()
    note = ""
    try:
        if doi.startswith("10.1016"):
            note = await fetch_elsevier(page, ctx, rec, out)
            return pdf_ok(out), note

        urls = publisher_urls(doi)
        if not urls:                      # 未知出版商：从落地页找 PDF 链接
            try:
                await page.goto(f"https://doi.org/{doi}", wait_until="domcontentloaded", timeout=60000)
                for _ in range(3):
                    cands = await page.eval_on_selector_all(
                        "a", "els=>els.map(e=>e.href).filter(h=>h && (/articlepdf/i.test(h)"
                             "||/\\/doi\\/(pdf|pdfdirect|epdf)\\//i.test(h)||/article-pdf/i.test(h)))")
                    if cands:
                        urls = list(dict.fromkeys(cands))
                        break
                    await page.wait_for_timeout(4000)
            except Exception as e:
                note += f"land-{type(e).__name__} "

        for url in urls:
            how = await grab(page, ctx, url, out, timeout_s=60)
            if how:
                return True, note + how
        if doi.startswith("10.1126"):
            how = await pmc_pdf(page, ctx, doi, out)
            if how:
                return True, note + how
        return False, note + "no-pdf"
    finally:
        await page.close()


# ---------------------------------------------------------------- 清单读取

def load_xlsx(path: str, sheet: str) -> list[dict]:
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[sheet] if sheet else wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    head = [str(c).strip() if c is not None else "" for c in rows[0]]

    def pick(*names):
        for n in names:
            if n in head:
                return head.index(n)
        return None

    i_id = pick("编号", "ID", "id")
    i_dir = pick("主研究方向", "分类", "目录", "folder")
    i_title = pick("论文题目（原文）", "题目", "title")
    i_doi = pick("DOI", "doi")
    i_year = pick("出版年（WoS）", "年份", "year")
    if i_doi is None:
        sys.exit("清单里找不到 DOI 列")
    out = []
    for r in rows[1:]:
        if not r or i_doi >= len(r) or not r[i_doi]:
            continue
        out.append({
            "id": str(r[i_id]).strip() if i_id is not None and r[i_id] else "",
            "dir": str(r[i_dir]).strip() if i_dir is not None and r[i_dir] else "",
            "title": str(r[i_title] or "").strip() if i_title is not None else "",
            "doi": str(r[i_doi]).strip(),
            "year": str(r[i_year] or "").strip() if i_year is not None else "",
        })
    return out


def load_json(path: str) -> list[dict]:
    data = json.load(open(path, encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("items") or data.get("records") or []
    return data


# ---------------------------------------------------------------- 命令

async def run_batch(records: list[dict], args) -> None:
    ok, fail = [], []
    async with async_playwright() as p:
        ensure_pdf_external(args.profile)
        ctx = await p.chromium.launch_persistent_context(
            args.profile, channel="chrome", headless=args.headless, accept_downloads=True,
            locale="zh-CN", viewport={"width": 1440, "height": 950},
            args=["--disable-blink-features=AutomationControlled", "--no-first-run",
                  "--no-default-browser-check"])
        await ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        for i, rec in enumerate(records, 1):
            out = target_path(rec, args.out_root)
            done, note = False, ""
            for attempt in range(3):
                try:
                    done, note = await process(ctx, rec, out)
                except Exception as e:
                    done, note = False, f"exc-{type(e).__name__}"
                if done:
                    break
                log(f"    {rec.get('id') or rec['doi']} 第{attempt + 1}次失败：{note}")
                await asyncio.sleep(30 * (attempt + 1))
            log(f"[{i}/{len(records)}] {rec.get('id') or rec['doi']:12s} "
                f"{'OK ' if done else 'FAIL'} {note}")
            (ok if done else fail).append(rec.get("id") or rec["doi"])
            pref = next((k for k in SPACING if k != "*" and rec["doi"].startswith(k)), "*")
            await asyncio.sleep(random.uniform(*SPACING[pref]))
        await ctx.close()
    log(f"完成：成功 {len(ok)}，失败 {len(fail)}")
    if fail:
        log("失败清单：" + ", ".join(fail))


async def cmd_sd_login(args) -> None:
    """打开有头 Chrome，走 Elsevier 机构登录 → Peking University → 北大 IAAA。"""
    async with async_playwright() as p:
        ensure_pdf_external(args.profile)
        ctx = await p.chromium.launch_persistent_context(
            args.profile, channel="chrome", headless=False, accept_downloads=True,
            locale="zh-CN", viewport={"width": 1440, "height": 950},
            args=["--disable-blink-features=AutomationControlled", "--no-first-run",
                  "--no-default-browser-check"])
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto("https://www.sciencedirect.com/user/institution/login?targetURL=%2F",
                        wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(4000)
        # 切到 Peking University（不要用深圳大学城图书馆）
        for sel in ["button:has-text('取消')", "a:has-text('取消')"]:
            el = await page.query_selector(sel)
            if el:
                await el.click()
                break
        await page.wait_for_timeout(3000)
        box = await page.query_selector("input[type='text']")
        if box:
            await box.fill("Peking")
            await page.wait_for_timeout(3500)
            opt = await page.query_selector("text=Peking University")
            if opt:
                await opt.click()
        log(">>> 请在浏览器窗口用北大 IAAA 登录（学号 + 密码）")
        for _ in range(180):
            await page.wait_for_timeout(4000)
            if "sciencedirect.com" in page.url and not await page_blocked(page):
                log(">>> 登录成功，会话已保存到 profile")
                break
        else:
            log(">>> 等待超时，未检测到登录成功")
        await ctx.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="按 DOI 批量下载期刊全文")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--out-root", required=True, help="PDF 根目录（按 dir 字段建子目录）")
        p.add_argument("--profile", default=DEFAULT_PROFILE, help="浏览器持久化 profile 目录")
        p.add_argument("--headless", action="store_true", help="无头模式（默认有头）")
        p.add_argument("--only", nargs="*", help="只处理这些编号")
        p.add_argument("--doi-prefix", nargs="*", help="只处理这些 DOI 前缀，如 10.1002")
        p.add_argument("--limit", type=int)

    p1 = sub.add_parser("from-xlsx")
    p1.add_argument("--xlsx", required=True)
    p1.add_argument("--sheet", default="")
    common(p1)

    p2 = sub.add_parser("from-json")
    p2.add_argument("--json", required=True)
    common(p2)

    p3 = sub.add_parser("sd-login")
    p3.add_argument("--profile", default=DEFAULT_PROFILE)

    args = ap.parse_args()
    if args.cmd == "sd-login":
        asyncio.run(cmd_sd_login(args))
        return

    recs = load_xlsx(args.xlsx, args.sheet) if args.cmd == "from-xlsx" else load_json(args.json)
    if getattr(args, "only", None):
        recs = [r for r in recs if r.get("id") in args.only]
    if getattr(args, "doi_prefix", None):
        recs = [r for r in recs if str(r["doi"]).startswith(tuple(args.doi_prefix))]
    if getattr(args, "limit", None):
        recs = recs[: args.limit]
    log(f"待处理 {len(recs)} 篇 → {args.out_root}")
    asyncio.run(run_batch(recs, args))


if __name__ == "__main__":
    main()
