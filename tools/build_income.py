"""抓取城镇/农村居民人均可支配收入（元），并按「每个市的区县」排名，生成 data/income.csv

数据源：红黑人口库各页面头部「XXXX年城镇居民可支配收入 / 农村居民可支配收入」卡片。
与人口、GDP 脚本共用页面缓存（data/_cache_hhk），建议在 build_population.py 之后运行。

输出字段：code,name,urban,urban_year,rural,rural_year,urban_rank,rural_rank,source
  - urban/rural 单位：元/人
  - urban_rank/rural_rank：在该市（父节点）范围内的名次，仅填 1~3，其余留空

用法：
  python tools/build_income.py
  python tools/build_income.py --offline
"""
import argparse
import csv
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from build_population import (  # noqa: E402
    MUNICIPAL, OPTION_RE, PROV_PAGES, Matcher,
    collect_city_urls, fetch, load_regions, parse_name,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "income.csv")

URBAN_RE = re.compile(
    r"<span>\s*([0-9]+(?:\.[0-9]+)?)\s*元\s*</span>\s*(?:</a>)?[^<]{0,40}<b>\s*(\d{4})年城镇居民可支配收入",
    re.S,
)
RURAL_RE = re.compile(
    r"<span>\s*([0-9]+(?:\.[0-9]+)?)\s*元\s*</span>\s*(?:</a>)?[^<]{0,40}<b>\s*(\d{4})年农村居民可支配收入",
    re.S,
)
URBAN_ALT = re.compile(r"<span>\s*([0-9]+(?:\.[0-9]+)?)\s*元\s*</span>\s*(?:</a>)?[^<]{0,40}<b>[^<]{0,8}城镇居民可支配收入")
RURAL_ALT = re.compile(r"<span>\s*([0-9]+(?:\.[0-9]+)?)\s*元\s*</span>\s*(?:</a>)?[^<]{0,40}<b>[^<]{0,8}农村居民可支配收入")


def parse_pair(html, rx, rx_alt):
    m = rx.search(html)
    if m:
        return float(m.group(1)), int(m.group(2))
    m = rx_alt.search(html)
    if m:
        return float(m.group(1)), None
    return None, None


def parse_income(html):
    urban, uy = parse_pair(html, URBAN_RE, URBAN_ALT)
    rural, ry = parse_pair(html, RURAL_RE, RURAL_ALT)
    return urban, uy, rural, ry


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--only", help="只处理指定省份，逗号分隔")
    args = ap.parse_args()
    only = set(x.strip() for x in args.only.split(",")) if args.only else None

    regions = load_regions()
    m = Matcher(regions)
    rows = []   # (code, name, urban, uy, rural, ry, url)

    # 省
    for prov, pid in PROV_PAGES.items():
        if not pid or (only and prov not in only):
            continue
        html = fetch(f"https://www.hongheiku.com/sjrk/{pid}.html", args.offline)
        urban, uy, rural, ry = parse_income(html)
        code = m.resolve(prov, prov)
        if code and (urban or rural):
            rows.append((code, prov, urban, uy, rural, ry, f"https://www.hongheiku.com/sjrk/{pid}.html"))

    # 市
    city_urls = collect_city_urls(args.offline, False, only)
    print(f"市级页面 {len(city_urls)} 个…")
    area_targets = []

    def work_city(u):
        html = fetch(u, args.offline)
        name = parse_name(html)
        return u, name, parse_income(html), html

    with ThreadPoolExecutor(max_workers=8) as ex:
        for u, name, inc, html in ex.map(work_city, sorted(city_urls)):
            if name and (inc[0] or inc[2]):
                code = m.resolve(name, None)
                if code:
                    rows.append((code, name, *inc, u))
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

    # 区县
    area_targets = sorted(set(area_targets))
    print(f"区县页面 {len(area_targets)} 个…")
    ok = 0

    def work_area(t):
        u, parent = t
        html = fetch(u, args.offline)
        return u, parent, parse_name(html), parse_income(html)

    with ThreadPoolExecutor(max_workers=8) as ex:
        for i, (u, parent, name, inc) in enumerate(ex.map(work_area, area_targets), 1):
            if name and (inc[0] or inc[2]):
                code = m.resolve_child(name, parent)
                if code:
                    rows.append((code, name, *inc, u))
                    ok += 1
            if i % 200 == 0:
                print(f"  ...{i}/{len(area_targets)}  成功 {ok}")
    print(f"  区县成功 {ok}/{len(area_targets)}")

    # 去重
    seen = {}
    for code, name, urban, uy, rural, ry, src in rows:
        if code in seen:
            continue
        seen[code] = (name, urban, uy, rural, ry, src)

    # 按父节点排名（仅区县参与，取前 3）
    parent_of = {r["code"]: r["parent_code"] for r in regions}
    level_of = {r["code"]: r["level"] for r in regions}
    ranks_u, ranks_r = {}, {}

    def rank(items):
        """items: [(code, value)] → {code: rank}，只给区县（level=area）排名"""
        by_parent = {}
        for code, val in items:
            if level_of.get(code) != "area":
                continue
            p = parent_of.get(code)
            if p:
                by_parent.setdefault(p, []).append((code, val))
        out = {}
        for p, arr in by_parent.items():
            arr.sort(key=lambda x: -x[1])
            last = None
            rank_no = 0
            pos = 0
            for code, val in arr[:3]:
                pos += 1
                if val != last:
                    rank_no = pos
                    last = val
                out[code] = rank_no
        return out

    urban_items = [(c, v[1]) for c, v in seen.items() if v[1]]
    rural_items = [(c, v[3]) for c, v in seen.items() if v[3]]
    ranks_u = rank(urban_items)
    ranks_r = rank(rural_items)

    out_rows = []
    for code, v in sorted(seen.items()):
        out_rows.append({
            "code": code,
            "name": v[0],
            "urban": ("%.2f" % v[1]) if v[1] else "",
            "urban_year": v[2] or "",
            "rural": ("%.2f" % v[3]) if v[3] else "",
            "rural_year": v[4] or "",
            "urban_rank": ranks_u.get(code, ""),
            "rural_rank": ranks_r.get(code, ""),
            "source": v[5],
        })

    with open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["code", "name", "urban", "urban_year", "rural",
                                          "rural_year", "urban_rank", "rural_rank", "source"])
        w.writeheader()
        w.writerows(out_rows)

    n_u = sum(1 for r in out_rows if r["urban_rank"])
    n_r = sum(1 for r in out_rows if r["rural_rank"])
    print(f"\n写入 {OUT}: {len(out_rows)} 条；城镇 TOP3 标记 {n_u} 个，农村 TOP3 标记 {n_r} 个")


if __name__ == "__main__":
    main()
