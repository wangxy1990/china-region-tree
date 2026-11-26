"""抓取各地 GDP（亿元），生成 data/gdp.csv

数据源：红黑人口库（hongheiku.com）各页面头部「XXXX年GDP数据」卡片，
与人口脚本共用同一批页面与缓存（data/_cache_hhk），因此建议在 build_population.py 之后运行。

输出：data/gdp.csv (code,name,gdp,gdp_year,source)，gdp 单位为亿元。
用法：
  python tools/build_gdp.py            # 抓取（命中缓存的页面不重复请求）
  python tools/build_gdp.py --offline  # 只用缓存
"""
import argparse
import csv
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from build_population import (  # noqa: E402
    AREA_LINK_RE, MUNICIPAL, OPTION_RE, PROV_PAGES, Matcher,
    collect_city_urls, fetch, load_regions, parse_name,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "gdp.csv")

GDP_RE = re.compile(
    r"<span>\s*([0-9]+(?:\.[0-9]+)?)\s*亿\s*</span>\s*(?:</a>)?[^<]{0,40}<b>\s*(\d{4})年GDP数据",
    re.S,
)
GDP_RE_ALT = re.compile(r"<span>\s*([0-9]+(?:\.[0-9]+)?)\s*亿\s*</span>\s*(?:</a>)?[^<]{0,40}<b>[^<]{0,6}GDP数据")


def parse_gdp(html):
    if not html:
        return None, None
    m = GDP_RE.search(html)
    if m:
        return float(m.group(1)), int(m.group(2))
    m = GDP_RE_ALT.search(html)
    if m:
        return float(m.group(1)), None
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--only", help="只处理指定省份，逗号分隔")
    args = ap.parse_args()
    only = set(x.strip() for x in args.only.split(",")) if args.only else None

    regions = load_regions()
    m = Matcher(regions)
    rows = []

    # 1) 省级
    for prov, pid in PROV_PAGES.items():
        if not pid or (only and prov not in only):
            continue
        html = fetch(f"https://www.hongheiku.com/sjrk/{pid}.html", args.offline)
        gdp, year = parse_gdp(html)
        code = m.resolve(prov, prov)
        if gdp and code:
            rows.append((code, prov, gdp, year, f"https://www.hongheiku.com/sjrk/{pid}.html"))

    # 2) 市级
    city_urls = collect_city_urls(args.offline, False, only)
    print(f"市级页面 {len(city_urls)} 个，抓取中…")
    area_targets = []

    def work_city(u):
        html = fetch(u, args.offline)
        name = parse_name(html)
        gdp, year = parse_gdp(html)
        return u, name, gdp, year, html

    with ThreadPoolExecutor(max_workers=8) as ex:
        for u, name, gdp, year, html in ex.map(work_city, sorted(city_urls)):
            if name and gdp:
                code = m.resolve(name, None)
                if code:
                    rows.append((code, name, gdp, year, u))
            if name:
                for au, an in OPTION_RE.findall(html):
                    if "/xianjirank/" in au:
                        area_targets.append((au, name))

    for prov in MUNICIPAL:
        if only and prov not in only:
            continue
        pid = PROV_PAGES.get(prov)
        if not pid:
            continue
        html = fetch(f"https://www.hongheiku.com/sjrk/{pid}.html", args.offline)
        for au, an in OPTION_RE.findall(html):
            if "/xianjirank/" in au:
                area_targets.append((au, prov))

    # 3) 区县
    area_targets = sorted(set(area_targets))
    print(f"区县页面 {len(area_targets)} 个，抓取中…")
    ok = 0

    def work_area(t):
        u, parent = t
        html = fetch(u, args.offline)
        name = parse_name(html)
        gdp, year = parse_gdp(html)
        return u, parent, name, gdp, year

    with ThreadPoolExecutor(max_workers=8) as ex:
        for i, (u, parent, name, gdp, year) in enumerate(ex.map(work_area, area_targets), 1):
            if name and gdp:
                code = m.resolve_child(name, parent)
                if code:
                    rows.append((code, name, gdp, year, u))
                    ok += 1
            if i % 200 == 0:
                print(f"  ...{i}/{len(area_targets)}  成功 {ok}")
    print(f"  区县成功 {ok}/{len(area_targets)}")

    seen = {}
    for code, name, gdp, year, src in rows:
        if code in seen:
            continue
        seen[code] = (name, gdp, year, src)

    out_rows = [
        {"code": c, "name": v[0], "gdp": ("%g" % v[1]) if v[1] is not None else "",
         "gdp_year": v[2] or "", "source": v[3]}
        for c, v in sorted(seen.items())
    ]
    with open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["code", "name", "gdp", "gdp_year", "source"])
        w.writeheader()
        w.writerows(out_rows)

    total = sum(float(r["gdp"]) for r in out_rows if r["gdp"])
    print(f"\n写入 {OUT}: {len(out_rows)} 条，GDP 合计 {total / 10000:.2f} 万亿元")


if __name__ == "__main__":
    main()
