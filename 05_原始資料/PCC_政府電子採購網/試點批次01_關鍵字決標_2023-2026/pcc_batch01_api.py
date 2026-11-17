#!/usr/bin/env python3
"""
批次 01（API 版）：資料來源為第三方 API pcc-api.openfun.app（g0v／openfun，資料收集自政府電子採購網）。
2026-11-17 因官方 web.pcc.gov.tw 拒絕雲端 IP，經使用者同意改用此 API。
授權：依採購網著作權聲明（合理使用、需註明出處），不是政府資料開放授權條款。
每筆公告的「原始公告網址」仍指向採購網官方公告頁。

流程：
 1. 用 searchbytitle 逐一搜尋關鍵字（另搜「原住民族」，用來做雙關鍵字條件）
 2. 留下公告日期 ≥ 2023-01-01、類型為決標公告或更正決標公告、本地重新比對命中關鍵字的案件
 3. 抓 tender 明細，將去個資的原始公告存到 ./raw/<公告日期>_<公告檔名>.json
 4. 篩選後輸出 ./out/pcc_batch01.csv 和 ./out/summary.txt
用法：python3 pcc_batch01_api.py [--cache ./api_cache] [--raw ./raw] [--out ./out]
"""
import argparse, csv, hashlib, json, os, re, sys, time, urllib.parse, urllib.request
from collections import Counter, defaultdict
from datetime import date
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pcc_batch01 import CATEGORIES, COLS, MIN_AMOUNT, match_keywords, parse_date, parse_amount

API = "https://pcc-api.openfun.app/api/"
START, END = date(2023, 1, 1), date(2026, 12, 31)
SEARCH_KW = sorted({k for _, _, s, p in CATEGORIES for k in s} | {"ISO14064"} | {a for _, _, _, p in CATEGORIES for a, _ in p})
AWARD_TYPES = ("決標公告", "更正決標公告")
PII_KEY = re.compile(r"(聯絡人|評選委員|工作小組|姓名|電話|傳真|電子郵件|地址|附加說明|備註|說明|英文公告)")
ORG_PREFIXES = ("已公告資料:", "採購資料:")

def get(url):
    for i in range(6):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 research-script"})
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.load(r)
        except Exception as e:
            print("retry", url, e, file=sys.stderr); time.sleep(3 * (i + 1))
    raise RuntimeError("fetch failed: " + url)

def cached(path, url):
    if os.path.exists(path):
        return json.load(open(path, encoding="utf-8"))
    d = get(url); time.sleep(0.2)
    json.dump(d, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    return d

def search_all(cache, kw):
    path = os.path.join(cache, "search", kw.replace(" ", "_") + ".json")
    if os.path.exists(path):
        return json.load(open(path, encoding="utf-8"))
    recs, p = [], 1
    while True:
        d = get(API + "searchbytitle?" + urllib.parse.urlencode({"query": kw, "page": p}))
        recs += d.get("records", [])
        if p >= d.get("total_pages", 1):
            break
        p += 1; time.sleep(0.3)
    json.dump(recs, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    return recs

def f(d, name):
    for p in ORG_PREFIXES:
        if d.get(p + name):
            return d[p + name].strip()
    return ""

def winners(d):
    out = {}
    for k, v in d.items():
        m = re.match(r"投標廠商:投標廠商(\d+):是否得標$", k)
        if m and v.strip() == "是":
            n = m.group(1); pre = f"投標廠商:投標廠商{n}:"
            out[int(n)] = {"name": d.get(pre + "廠商名稱", "").strip(), "id": d.get(pre + "廠商代碼", "").strip(),
                           "org": d.get(pre + "組織型態", "").strip(), "amount": d.get(pre + "決標金額", "")}
    return [out[k] for k in sorted(out)]

TW_ID = re.compile(r"[A-Z][1289]\d{8}")

def is_person(w):
    """自然人：組織型態為「自然人」，或廠商代碼符合身分證／居留證格式。學校、機關、外國廠商的非統編代碼不算個人。"""
    return w["org"] == "自然人" or bool(TW_ID.fullmatch(w["id"] or ""))

def sanitize(rec):
    det = rec.get("detail") or {}
    secret = set()
    for k, v in det.items():
        m = re.match(r"(投標廠商:投標廠商\d+:)廠商代碼$", k)
        if m:
            w = {"id": v.strip(), "org": det.get(m.group(1) + "組織型態", "").strip()}
            if is_person(w):
                secret |= {v.strip(), det.get(m.group(1) + "廠商名稱", "").strip(), det.get(m.group(1) + "廠商名稱(英)", "").strip()}
    secret.discard("")
    d = {}
    for k, v in det.items():
        if PII_KEY.search(k):
            continue
        if isinstance(v, str) and v.strip() in secret:
            v = "個人"
        d[k] = v
    return {"date": rec.get("date"), "filename": rec.get("filename"), "unit_id": rec.get("unit_id"),
            "job_number": rec.get("job_number"), "type": rec["brief"]["type"], "detail": d,
            "source": "pcc-api.openfun.app（資料源自政府電子採購網）"}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="./api_cache"); ap.add_argument("--raw", default="./raw"); ap.add_argument("--out", default="./out")
    a = ap.parse_args()
    for sub in ("search", "tender"):
        os.makedirs(os.path.join(a.cache, sub), exist_ok=True)
    os.makedirs(a.raw, exist_ok=True); os.makedirs(a.out, exist_ok=True)

    excl = Counter(); search_hits = {}
    ann_seen = {}; cases = {}
    for kw in SEARCH_KW:
        recs = search_all(a.cache, kw); search_hits[kw] = len(recs)
        for x in recs:
            key = (x["unit_id"], x["job_number"], x["filename"])
            if key in ann_seen:
                continue
            ann_seen[key] = 1
            if x["date"] < 20230101:
                excl["A. 公告日期早於 2023-01-01（決標日必然更早）"] += 1; continue
            if x["brief"]["type"] not in AWARD_TYPES:
                excl["B. 公告類型非決標公告／更正決標公告（招標、無法決標、定期彙送等）"] += 1; continue
            if not match_keywords(x["brief"]["title"])[0]:
                excl["C. 標案名稱本地比對未命中（多為僅含「原住民族」而無第二關鍵字）"] += 1; continue
            cases[(x["unit_id"], x["job_number"])] = x["tender_api_url"].replace("http:", "https:")

    rows = []; problems = []; kept_cases = set()
    for (uid, job), url in sorted(cases.items()):
        h = hashlib.md5(f"{uid}|{job}".encode()).hexdigest()
        t = cached(os.path.join(a.cache, "tender", h + ".json"), url)
        awards = [r for r in t.get("records", []) if r["brief"]["type"] in AWARD_TYPES and r.get("detail")]
        # 同一決標公告序號只保留最新一則（更正決標公告取代原公告）
        latest = {}
        for r in sorted(awards, key=lambda r: (r["date"], r["filename"])):
            seq = r["detail"].get("決標資料:決標公告序號", "")
            if seq in latest:
                excl["D. 被後續更正決標公告取代的舊公告"] += 1
            latest[seq] = r
        for seq, r in sorted(latest.items()):
            d = r["detail"]; title = f(d, "標案名稱")
            ws = winners(d)
            raw_fn = f"{r['date']}_{r['filename']}.json"
            json.dump(sanitize(r), open(os.path.join(a.raw, raw_fn), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            ad = parse_date(d.get("決標資料:決標日期", ""))
            if ad is None:
                excl["E. 決標日期缺漏或無法解析"] += 1; continue
            if not (START <= ad <= END):
                excl["F. 決標日期不在 2023-01-01～2026-12-31"] += 1; continue
            cat = f(d, "標的分類")
            if "勞務" not in cat:
                excl["G. 標的分類非勞務"] += 1; continue
            amt = parse_amount(d.get("決標資料:總決標金額", ""))
            if amt is None:
                excl["H. 總決標金額缺漏或未公開"] += 1; continue
            if amt < MIN_AMOUNT:
                excl["I. 總決標金額 < 400,000"] += 1; continue
            cats, hits = match_keywords(title)
            if not cats:
                excl["J. 明細標案名稱未命中關鍵字"] += 1; continue
            if not ws:
                problems.append(f"{raw_fn}: 找不到「是否得標=是」的廠商，以空白廠商輸出一列")
                ws = [{"name": "", "id": "", "org": "", "amount": ""}]
            kept_cases.add((uid, job, seq))
            for w in ws:
                person = is_person(w)
                vamt = parse_amount(w["amount"])
                rows.append({
                    "類別編號": "；".join(cats), "命中關鍵字": "；".join(hits), "標案名稱": title,
                    "案號": f(d, "標案案號") or job, "招標機關": d.get("機關資料:機關名稱", ""),
                    "招標機關代碼": d.get("機關資料:機關代碼", uid), "決標日期": ad.isoformat(),
                    "決標金額": str(int(vamt if vamt is not None else amt)),
                    "得標廠商": "個人" if person else w["name"], "得標廠商統一編號": "" if person else w["id"],
                    "決標方式": f(d, "決標方式"), "履約地點": f(d, "履約地點（含地區）") or f(d, "履約地點"),
                    "標的分類": cat, "原始公告網址或檔名": d.get("url") or raw_fn,
                })

    rows.sort(key=lambda r: (r["類別編號"], r["決標日期"], r["案號"]))
    with open(os.path.join(a.out, "pcc_batch01.csv"), "w", newline="", encoding="utf-8-sig") as fp:
        w = csv.DictWriter(fp, fieldnames=COLS); w.writeheader(); w.writerows(rows)

    years = [str(y) for y in range(START.year, END.year + 1)]
    rc = defaultdict(Counter); cc = defaultdict(set)
    for r in rows:
        y = r["決標日期"][:4]
        for c in r["類別編號"].split("；"):
            rc[c][y] += 1; cc[(c, y)].add((r["招標機關代碼"], r["案號"], r["決標日期"]))
    persons = sum(1 for r in rows if r["得標廠商"] == "個人")
    L = ["政府電子採購網 決標公告 關鍵字批次 01（2023-01-01～2026-12-31）",
         "資料來源：pcc-api.openfun.app（第三方 g0v／openfun API，資料收集自政府電子採購網）；授權依採購網著作權聲明，引用請註明出處。",
         "（官方 web.pcc.gov.tw 拒絕本環境的雲端 IP，經使用者同意改用此 API。）",
         f"擷取日期：{date.today().isoformat()}", "",
         f"輸出列數（每家得標廠商一列）：{len(rows)}",
         f"輸出決標公告數（標案）：{len(kept_cases)}",
         f"其中得標廠商為個人而改寫的列數：{persons}", "",
         "【各類別 × 年度：列數（標案數）】※一案命中多類別時，各類別各計一次"]
    L.append("類別\t" + "\t".join(years) + "\t合計")
    for code, name, *_ in CATEGORIES:
        L.append(f"{code} {name}\t" + "\t".join(f"{rc[code][y]}（{len(cc[(code, y)])}）" for y in years)
                 + f"\t{sum(rc[code].values())}（{len({k for (c, _), s in cc.items() if c == code for k in s})}）")
    L.append("全部（不重複）\t" + "\t".join(
        f"{sum(1 for r in rows if r['決標日期'][:4] == y)}（{len({k for (c, yy), s in cc.items() if yy == y for k in s})}）" for y in years)
        + f"\t{len(rows)}（{len(kept_cases)}）")
    L += ["", "【母體說明】排除計數以 API 標題搜尋的結果為母體（以下為不重複公告數），不是採購網全部公告。",
          "各關鍵字搜尋命中公告數（不限年度、不限公告類型）：" + "、".join(f"{k} {v}" for k, v in search_hits.items()),
          f"不重複公告總數：{len(ann_seen)}；進入明細查詢的標案數：{len(cases)}", "",
          "【排除筆數（依序套用；A–C 以公告計，D–J 以決標公告計）】"]
    for k in sorted(excl):
        L.append(f"{k}：{excl[k]}")
    L += ["", "註：決標金額欄為該得標廠商的決標金額（沒有時填總決標金額）；門檻 400,000 以總決標金額判斷。",
          "註：得標廠商組織型態為「自然人」或廠商代碼為身分證／居留證格式時，名稱改為「個人」，統編留空。raw/ 檔已移除聯絡人、評選委員、電話、地址、附加說明等可能含自然人姓名的欄位，個人得標者的名稱與代碼改為「個人」。"]
    if problems:
        L += ["", "【處理問題】"] + problems
    open(os.path.join(a.out, "summary.txt"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L))

if __name__ == "__main__":
    main()
