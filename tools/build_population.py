"""抓取地级市常住人口，生成 data/population.csv

数据源：红黑人口库（hongheiku.com），各市页面头部标注“<年份>年初常住人口”，
随每年统计公报更新，因此每周重跑可自动跟进。

实现路径：
1. 从 31 个省级页面的“辖区”下拉框收集市级页面链接；
2. 再从“全国地级市人口排名”分页列表补充（部分省份页面没有下拉框）；
3. 逐个抓市级页，解析 h1 城市名、省份标签、常住人口与年份；
4. 用 data/regions.csv 把名称对到行政区划代码。

用法：
  python tools/build_population.py             # 联网抓取并写 data/population.csv
  python tools/build_population.py --offline   # 只用缓存
  python tools/build_population.py --refresh   # 忽略缓存重新抓
"""
import argparse
import csv
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "_cache_hhk")
OUT = os.path.join(ROOT, "data", "population.csv")
REGIONS = os.path.join(ROOT, "data", "regions.csv")

HDR = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

PROV_PAGES = {
    "北京市": 1088, "天津市": 1094, "河北省": 976, "山西省": 1042, "内蒙古自治区": 1070,
    "辽宁省": 1021, "吉林省": 1059, "黑龙江省": 1036, "上海市": 1082, "江苏省": 971,
    "浙江省": 999, "安徽省": 986, "福建省": 1026, "江西省": 1016, "山东省": 955,
    "河南省": 960, "湖北省": 994, "湖南省": 981, "广东省": 950, "广西壮族自治区": 1004,
    "海南省": 1099, "重庆市": 1053, "四川省": 965, "贵州省": 1047, "云南省": 1009,
    "西藏自治区": 1119, "陕西省": 1031, "甘肃省": 1064, "青海省": 1112,
    "宁夏回族自治区": 1106, "新疆维吾尔自治区": 1075,
    "香港特别行政区": 1105, "澳门特别行政区": 1125,
}

POP_RE = re.compile(
    r"<span>\s*([0-9]+(?:\.[0-9]+)?)(万)?\s*</span>\s*(?:</a>)?[^<]{0,40}<b>\s*(\d{4})年[初末]?常住人口",
    re.S,
)
POP_RE_ALT = re.compile(
    r"<span>\s*([0-9]+(?:\.[0-9]+)?)(万)?\s*</span>\s*(?:</a>)?[^<]{0,40}<b>[^<]{0,8}常住人口"
)
# 部分页面只有“第七次人口普查年初常住人口”（即 2020 年数据）
POP_SEVEN_RE = re.compile(
    r"<span>\s*([0-9]+(?:\.[0-9]+)?)(万)?\s*</span>\s*(?:</a>)?[^<]{0,40}<b>\s*第七次人口普查[^<]{0,6}常住人口"
)

# 站点缺页的省份用七普公报表格兜底：{省: 公报页 URL}
GAZETTE_PAGES = {
    "山东省": "https://www.hongheiku.com/goto/tn06",
}

# 河南省公报为图片表，站点无分市页面，采用《河南省第七次全国人口普查公报（第二号）》
# https://m.henan.gov.cn/2021/05-21/2149620.html 的原值（2020-11-01）
MANUAL = {
    "河南省": {
        "郑州市": 12600574, "开封市": 4824016, "洛阳市": 7056699, "平顶山市": 4987137,
        "安阳市": 5477616, "鹤壁市": 1565973, "新乡市": 6251929, "焦作市": 3521078,
        "濮阳市": 3772088, "许昌市": 4379998, "漯河市": 2367490, "三门峡市": 2034872,
        "南阳市": 9713112, "商丘市": 7816831, "信阳市": 6234401, "周口市": 9026015,
        "驻马店市": 7008427, "济源市": 727265,
    },
}
OPTION_RE = re.compile(r'<option value="([^"]+)"[^>]*>\s*-\s*([^<]+?)\s*</option>')
H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
TAG_RE = re.compile(r'href="https://www.hongheiku.com/tag/([^"]+)"')
CITY_LINK_RE = re.compile(r'href="(https://www.hongheiku.com/shijirenkou/\d+\.html)"')


def fetch(url, offline=False, refresh=False):
    os.makedirs(CACHE, exist_ok=True)
    key = re.sub(r"[^0-9a-zA-Z]+", "_", url)[-100:] + ".html"
    path = os.path.join(CACHE, key)
    if not refresh and os.path.exists(path) and os.path.getsize(path) > 0:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    if offline:
        return ""
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=HDR)
            with urllib.request.urlopen(req, timeout=30) as r:
                html = r.read().decode("utf-8", "ignore")
            with open(path, "w", encoding="utf-8") as f:
                f.write(html)
            time.sleep(0.2)
            return html
        except Exception:
            if attempt == 2:
                print(f"  ! 抓取失败 {url}", file=sys.stderr)
                return ""
            time.sleep(1.2 * (attempt + 1))
    return ""


def parse_pop(html):
    if not html:
        return None, None
    m = POP_RE.search(html)
    if m:
        num = float(m.group(1)) * (10000 if m.group(2) else 1)
        return int(round(num)), int(m.group(3))
    m = POP_SEVEN_RE.search(html)
    if m:
        num = float(m.group(1)) * (10000 if m.group(2) else 1)
        return int(round(num)), 2020
    m = POP_RE_ALT.search(html)
    if m:
        num = float(m.group(1)) * (10000 if m.group(2) else 1)
        return int(round(num)), None
    return None, None


def parse_gazette(url, offline, refresh):
    """解析七普公报页第一张表：地区 + 人口数"""
    html = fetch(url, offline, refresh)
    out = {}
    tables = re.findall(r"<table.*?</table>", html, re.S)
    for t in tables:
        rows = re.findall(r"<tr.*?</tr>", t, re.S)
        hit = 0
        for row in rows:
            cells = [re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", c))
                     for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]
            if len(cells) < 2:
                continue
            name, val = cells[0], cells[1]
            if not re.fullmatch(r"[0-9]{5,9}", val):
                continue
            if len(name) < 2 or "地区" in name:
                continue
            out[name] = int(val)
            hit += 1
        if hit >= 5:
            break
    return out


def parse_name(html):
    m = H1_RE.search(html)
    if not m:
        return None
    name = re.sub(r"<[^>]+>", "", m.group(1)).strip()
    name = name.replace("人口数据", "").strip()
    return name or None


def parse_prov_tag(html):
    tags = [urllib.parse.unquote(t) for t in TAG_RE.findall(html)]
    for t in tags:
        if t in ("各省", "全国") or not t:
            continue
        return t
    return None


def norm(name):
    name = name.replace("*", "").replace(" ", "")
    for suf in ("特别行政区", "维吾尔自治区", "壮族自治区", "回族自治区", "自治区",
                "省", "市", "地区", "盟", "自治州"):
        name = name.replace(suf, "")
    return name


def load_regions():
    with open(REGIONS, "r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


class Matcher:
    def __init__(self, regions):
        self.regions = regions
        self.by_name = {}
        self.prov_key = {}
        for r in regions:
            self.by_name.setdefault(r["name"], []).append(r)
            if r["level"] == "1":
                self.prov_key[norm(r["name"])] = r["name"]

    def resolve(self, name, prov_short=None):
        cands = self.by_name.get(name, [])
        if cands:
            if prov_short:
                prov_full = self.prov_key.get(norm(prov_short))
                for c in cands:
                    if c["parent_code"] and self.name_of(c["parent_code"]) == prov_full:
                        return c["code"]
            lv = [c for c in cands if c["level"] in ("2", "1")]
            return (lv or cands)[0]["code"]
        n = norm(name)
        for key, ls in self.by_name.items():
            if norm(key) == n or norm(key).startswith(n) or n.startswith(norm(key)):
                lv = [c for c in ls if c["level"] in ("2", "1")]
                if lv:
                    return lv[0]["code"]
        return None

    def name_of(self, code):
        for r in self.regions:
            if r["code"] == code:
                return r["name"]
        return ""


def collect_city_urls(offline, refresh):
    urls = set()
    for prov, pid in PROV_PAGES.items():
        if not pid:
            continue
        html = fetch(f"https://www.hongheiku.com/sjrk/{pid}.html", offline, refresh)
        for u, n in OPTION_RE.findall(html):
            if "/shijirenkou/" in u:
                urls.add(u)
    # 列表页补充
    BASE = "https://www.hongheiku.com/category/shijirenkou"
    for page in range(1, 16):
        u = BASE if page == 1 else f"{BASE}/page/{page}"
        html = fetch(u, offline, refresh)
        if not html:
            break
        new = set(CITY_LINK_RE.findall(html))
        before = len(urls)
        urls |= new
        if len(urls) == before and page > 2:
            break
    return urls


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    regions = load_regions()
    m = Matcher(regions)

    print("收集市级页面链接…")
    city_urls = collect_city_urls(args.offline, args.refresh)
    print(f"共 {len(city_urls)} 个候选页面")

    # 省级节点自身人口
    rows = []
    for prov, pid in PROV_PAGES.items():
        if not pid:
            continue
        html = fetch(f"https://www.hongheiku.com/sjrk/{pid}.html", args.offline, args.refresh)
        pop, year = parse_pop(html)
        if pop:
            code = m.resolve(prov, prov)
            if code:
                rows.append((code, prov, pop, year, f"https://www.hongheiku.com/sjrk/{pid}.html"))

    def work(u):
        html = fetch(u, args.offline, args.refresh)
        name = parse_name(html)
        pop, year = parse_pop(html)
        prov = parse_prov_tag(html)
        return u, name, prov, pop, year

    print("抓取市级页面…")
    ok = 0
    miss = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for i, (u, name, prov, pop, year) in enumerate(ex.map(work, sorted(city_urls)), 1):
            if name and pop:
                code = m.resolve(name, prov)
                if code:
                    rows.append((code, name, pop, year, u))
                    ok += 1
                else:
                    miss.append(f"{name}(未匹配)")
            elif name:
                miss.append(f"{name}(无人口字段)")
            if i % 40 == 0:
                print(f"  ...{i}/{len(city_urls)}  成功 {ok}")

    # 公报兜底（站点缺页的省份）
    for prov, url in GAZETTE_PAGES.items():
        table = parse_gazette(url, args.offline, args.refresh)
        for name, val in table.items():
            code = m.resolve(name, prov)
            if code:
                rows.append((code, name, val, 2020, url))
        print(f"公报兜底 {prov}: {len(table)} 条")
    for prov, table in MANUAL.items():
        for name, val in table.items():
            code = m.resolve(name, prov)
            if code:
                rows.append((code, name, val, 2020, "https://m.henan.gov.cn/2021/05-21/2149620.html"))

    # 去重（同一 code 取最早出现，市优先于省）
    seen = {}
    for code, name, pop, year, src in rows:
        if code in seen:
            continue
        seen[code] = (name, pop, year, src)

    out_rows = [
        {"code": c, "name": v[0], "pop": v[1], "pop_year": v[2] or "", "source": v[3]}
        for c, v in sorted(seen.items())
    ]
    with open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["code", "name", "pop", "pop_year", "source"])
        w.writeheader()
        w.writerows(out_rows)

    total_pop = sum(int(r["pop"]) for r in out_rows)
    print(f"\n写入 {OUT}: {len(out_rows)} 条，合计 {total_pop / 1e8:.2f} 亿人")
    if miss:
        print("未入库：" + "、".join(miss[:15]) + (f" …共 {len(miss)}" if len(miss) > 15 else ""))


if __name__ == "__main__":
    main()
