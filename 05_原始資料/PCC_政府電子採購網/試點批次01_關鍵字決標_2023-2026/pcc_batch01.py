#!/usr/bin/env python3
"""
政府電子採購網（行政院公共工程委員會）官方開放資料：決標公告 → 關鍵字篩選批次 01

只使用官方來源 https://web.pcc.gov.tw/tps/tp/OpenData/showList（授權：政府資料開放授權條款-第1版）。
不使用 g0v 或任何第三方鏡像。僅用 Python 標準函式庫。

用法：
  python3 pcc_batch01.py                 # 下載 + 篩選 + 輸出
  python3 pcc_batch01.py --skip-download # 只處理 ./raw/ 中已有的檔案（可手動從官網下載後放入）
參數：--raw ./raw  --out ./out  --start 2023-01-01  --end 2026-12-31
"""
import argparse, csv, html, io, json, os, re, sys, unicodedata, urllib.parse, urllib.request, zipfile
from collections import Counter, defaultdict
from datetime import date
import xml.etree.ElementTree as ET

LIST_URL = "https://web.pcc.gov.tw/tps/tp/OpenData/showList"
MIN_AMOUNT = 400_000

# ---------- 關鍵字類別（類別編號自訂，見 README） ----------
CATEGORIES = [
    ("01", "永續旅遊／觀光", ["永續旅遊", "永續觀光", "GSTC", "永續標章", "旅行業輔導"], []),
    ("02", "溫室氣體與碳管理", ["溫室氣體盤查", "碳足跡", "ISO 14064", "碳盤查"], []),
    ("03", "低碳社區與氣候調適", ["低碳永續家園", "淨零社區", "社區減碳", "氣候變遷調適"], []),
    ("04", "原住民族產業與人才", ["原住民族產業", "產業聚落"],
     [("原住民族", "人才培訓"), ("原住民族", "永續發展")]),
    ("05", "成效與社會影響力評估", ["成效評估", "社會影響力", "SROI", "影響力評估", "社會投資報酬"], []),
]

def norm(s):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s or "")).upper()

def match_keywords(title):
    t = norm(title)
    cats, hits = [], []
    for code, _name, singles, pairs in CATEGORIES:
        h = [k for k in singles if norm(k) in t]
        h += [f"{a}+{b}" for a, b in pairs if norm(a) in t and norm(b) in t]
        if h:
            cats.append(code); hits += h
    return cats, hits

# ---------- 欄位名稱候選（官方檔案欄位名可能隨版本不同） ----------
F = {
    "title":   ["標案名稱", "tenderName", "TenderName", "title"],
    "caseno":  ["標案案號", "案號", "tenderCaseNo", "jobNumber", "caseNo"],
    "org":     ["機關名稱", "招標機關", "orgName", "unitName"],
    "orgcode": ["機關代碼", "招標機關代碼", "orgId", "unitId"],
    "date":    ["決標日期", "awardDate", "award_date"],
    "amount":  ["總決標金額", "決標金額", "totalAwardAmount", "awardAmount", "totalAmount"],
    "method":  ["決標方式", "awardWay", "awardMethod"],
    "place":   ["履約地點", "履約地點（含地區）", "performPlace", "location"],
    "cat":     ["標的分類", "採購性質", "procurementCategory", "category", "tenderType"],
    "url":     ["公告網址", "detailUrl", "url", "link"],
    "vname":   ["得標廠商", "廠商名稱", "得標廠商名稱", "supplierName", "vendorName", "companyName"],
    "vid":     ["廠商代碼", "得標廠商代碼", "統一編號", "supplierId", "vendorId", "companyId"],
    "vamount": ["得標廠商決標金額", "廠商決標金額", "supplierAwardAmount", "決標金額"],
}
VENDOR_CONTAINERS = ["得標廠商", "決標廠商", "得標廠商資料", "suppliers", "supplier", "vendors", "vendor", "companies"]

def pick(d, key):
    for k in F[key]:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""

# ---------- 下載 ----------
def http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (pcc-batch01 open-data script)"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()

def download(raw_dir, start, end):
    os.makedirs(raw_dir, exist_ok=True)
    page = http_get(LIST_URL).decode("utf-8", "replace")
    if "has been blocked" in page:
        sys.exit("採購網拒絕本機 IP（Web Page Blocked），請改在台灣網路環境執行，或手動下載後用 --skip-download。")
    links = set(re.findall(r'href="([^"]*downloadFile[^"]*)"', page))
    got = 0
    for href in sorted(links):
        href = html.unescape(href)
        fn = urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("fileName", [os.path.basename(href)])[0]
        low = fn.lower()
        if "gpa" in low or not ("award" in low or "決標" in fn):
            continue
        m = re.search(r"(20\d{2})(\d{2})(\d{2})", fn)
        if not m:
            continue
        d = date(*map(int, m.groups()))
        if not (start <= d <= end):
            continue
        dest = os.path.join(raw_dir, os.path.basename(fn))  # 保留原始檔名（含日期）
        if os.path.exists(dest):
            continue
        with open(dest, "wb") as f:
            f.write(http_get(urllib.parse.urljoin(LIST_URL, href)))
        got += 1
        print("下載", fn)
    print(f"下載完成：{got} 個新檔案")

# ---------- 解析 ----------
def parse_date(s):
    s = (s or "").strip()
    m = re.match(r"^(\d{2,4})[/\-.年]?(\d{1,2})[/\-.月]?(\d{1,2})", s)
    if not m:
        return None
    y, mo, d = map(int, m.groups())
    if y < 1911:
        y += 1911  # 民國年
    try:
        return date(y, mo, d)
    except ValueError:
        return None

def parse_amount(s):
    s = re.sub(r"[^\d.]", "", unicodedata.normalize("NFKC", s or ""))
    try:
        return float(s) if s else None
    except ValueError:
        return None

def xml_to_obj(el):
    kids = list(el)
    if not kids:
        return (el.text or "").strip()
    d = {}
    for c in kids:
        tag = c.tag.split("}")[-1]
        v = xml_to_obj(c)
        if tag in d:
            if not isinstance(d[tag], list):
                d[tag] = [d[tag]]
            d[tag].append(v)
        else:
            d[tag] = v
    return d

def find_records(obj):
    """遞迴找出含「標案名稱」類欄位的字典，即一筆決標公告。"""
    if isinstance(obj, list):
        for x in obj:
            yield from find_records(x)
    elif isinstance(obj, dict):
        if any(isinstance(obj.get(k), str) for k in F["title"]):
            yield obj
        else:
            for v in obj.values():
                yield from find_records(v)

def load_file(path):
    name = os.path.basename(path)
    data = open(path, "rb").read()
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                yield from load_bytes(z.read(n), f"{name}!{n}")
    else:
        yield from load_bytes(data, name)

def load_bytes(data, name):
    text = None
    for enc in ("utf-8-sig", "big5", "cp950"):
        try:
            text = data.decode(enc); break
        except UnicodeDecodeError:
            pass
    if text is None:
        raise ValueError(f"{name}: 無法判斷編碼")
    s = text.lstrip()
    if s.startswith("<"):
        objs = [xml_to_obj(ET.fromstring(data))]
    elif s.startswith("{") or s.startswith("["):
        objs = [json.loads(text)]
    else:
        objs = [list(csv.DictReader(io.StringIO(text)))]
    for o in objs:
        for rec in find_records(o):
            yield rec, name

def vendors_of(rec):
    vs = []
    for k in VENDOR_CONTAINERS:
        v = rec.get(k)
        if isinstance(v, dict):
            vs.append(v)
        elif isinstance(v, list):
            vs += [x for x in v if isinstance(x, dict)]
            if all(isinstance(x, str) for x in v):  # 平面多值
                vs += [{"廠商名稱": x} for x in v]
    if not vs:
        name = pick(rec, "vname")
        if name:
            # 一欄多家時以分隔符拆開
            names = re.split(r"[;；、|]", name)
            ids = re.split(r"[;；、|]", pick(rec, "vid")) if pick(rec, "vid") else []
            vs = [{"廠商名稱": n.strip(), "廠商代碼": ids[i].strip() if i < len(ids) else ""}
                  for i, n in enumerate(names) if n.strip()]
    return vs or [{}]

ORG_MARK = re.compile(r"(公司|有限|股份|行$|社$|會$|院$|所$|中心|大學|學院|學校|協會|學會|基金會|事務所|工作室|顧問|企業|"
                      r"合作社|聯盟|組織|研究|科技|工程|署$|局$|處$|部$|團$|店$|廠$|聯合|集團|銀行|機構|館$|室$)")

def deidentify(name, vid):
    """得標廠商若為個人：名稱改寫為「個人」，統編留空（不輸出自然人姓名或身分證號）。"""
    vid_n = re.sub(r"\s", "", vid or "")
    is_ubn = bool(re.fullmatch(r"\d{8}", vid_n))
    looks_person = (not ORG_MARK.search(name or "")) and bool(re.fullmatch(r"[一-鿿‧·．○*＊Ｏ]{2,4}", name or ""))
    if (vid_n and not is_ubn) or looks_person or (not vid_n and not ORG_MARK.search(name or "") and name):
        return "個人", ""
    return name, vid_n

# ---------- 主流程 ----------
COLS = ["類別編號", "命中關鍵字", "標案名稱", "案號", "招標機關", "招標機關代碼", "決標日期", "決標金額",
        "得標廠商", "得標廠商統一編號", "決標方式", "履約地點", "標的分類", "原始公告網址或檔名"]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="./raw"); ap.add_argument("--out", default="./out")
    ap.add_argument("--start", default="2023-01-01"); ap.add_argument("--end", default="2026-12-31")
    ap.add_argument("--skip-download", action="store_true")
    a = ap.parse_args()
    start, end = date.fromisoformat(a.start), date.fromisoformat(a.end)
    if not a.skip_download:
        download(a.raw, start, end)

    excl = Counter(); seen = set(); rows = []; problems = []
    total = 0
    files = sorted(f for f in os.listdir(a.raw) if not f.startswith(".")) if os.path.isdir(a.raw) else []
    for fn in files:
        try:
            recs = list(load_file(os.path.join(a.raw, fn)))
        except Exception as e:
            problems.append(f"{fn}: 解析失敗 {e}"); continue
        for rec, src in recs:
            title, caseno, orgcode = pick(rec, "title"), pick(rec, "caseno"), pick(rec, "orgcode")
            d = parse_date(pick(rec, "date"))
            key = (orgcode, caseno, title, d)
            if key in seen:
                excl["重複公告（同機關代碼＋案號＋名稱＋決標日）"] += 1; continue
            seen.add(key); total += 1
            if d is None:
                excl["決標日期缺漏或無法解析"] += 1; continue
            if not (start <= d <= end):
                excl["決標日期不在範圍內"] += 1; continue
            if "勞務" not in pick(rec, "cat"):
                excl["標的分類非勞務"] += 1; continue
            amt = parse_amount(pick(rec, "amount"))
            if amt is None:
                excl["決標金額缺漏"] += 1; continue
            if amt < MIN_AMOUNT:
                excl["決標金額 < 400,000"] += 1; continue
            cats, hits = match_keywords(title)
            if not cats:
                excl["標案名稱未命中關鍵字"] += 1; continue
            for v in vendors_of(rec):
                vname, vid = deidentify(pick(v, "vname"), pick(v, "vid"))
                vamt = parse_amount(pick(v, "vamount")) if v is not rec else None
                rows.append({
                    "類別編號": "；".join(cats), "命中關鍵字": "；".join(hits), "標案名稱": title, "案號": caseno,
                    "招標機關": pick(rec, "org"), "招標機關代碼": orgcode, "決標日期": d.isoformat(),
                    "決標金額": f"{int(vamt if vamt is not None else amt)}",
                    "得標廠商": vname, "得標廠商統一編號": vid, "決標方式": pick(rec, "method"),
                    "履約地點": pick(rec, "place"), "標的分類": pick(rec, "cat"),
                    "原始公告網址或檔名": pick(rec, "url") or src,
                })

    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "pcc_batch01.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLS); w.writeheader(); w.writerows(rows)

    by_cat_year = defaultdict(Counter); cases_cat_year = defaultdict(set)
    for r in rows:
        y = r["決標日期"][:4]
        for c in r["類別編號"].split("；"):
            by_cat_year[c][y] += 1
            cases_cat_year[(c, y)].add((r["招標機關代碼"], r["案號"], r["決標日期"]))
    years = sorted({r["決標日期"][:4] for r in rows})
    L = ["政府電子採購網 決標公告 關鍵字批次 01", f"決標日期範圍：{start} ～ {end}", f"來源檔案數：{len(files)}",
         f"讀入公告（去重後）：{total}", f"輸出列數（每家得標廠商一列）：{len(rows)}",
         f"輸出標案數：{len({(r['招標機關代碼'], r['案號'], r['決標日期']) for r in rows})}", "",
         "【各類別 × 年度 列數（標案數）】※跨類別標案會在每個命中類別各計一次"]
    for code, name, *_ in CATEGORIES:
        parts = [f"{y}: {by_cat_year[code][y]}（{len(cases_cat_year[(code, y)])}）" for y in years]
        L.append(f"{code} {name}：合計 {sum(by_cat_year[code].values())}　" + "　".join(parts))
    L += ["", "【排除筆數（依序套用，單位：公告）】"]
    for k in ["重複公告（同機關代碼＋案號＋名稱＋決標日）", "決標日期缺漏或無法解析", "決標日期不在範圍內",
              "標的分類非勞務", "決標金額缺漏", "決標金額 < 400,000", "標案名稱未命中關鍵字"]:
        L.append(f"{k}：{excl[k]}")
    if problems:
        L += ["", "【處理問題】"] + problems
    with open(os.path.join(a.out, "summary.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("\n".join(L))

if __name__ == "__main__":
    main()
