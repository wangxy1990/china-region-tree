#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键更新全国省市区结构树：抓最新民政部代码 → 生成 CSV → 跑 Java → 生成页面。

用法:
    python tools/update.py              # 自动探测最新年份并更新
    python tools/update.py --year 2024  # 指定年份
    python tools/update.py --dry-run    # 只检测，不覆盖文件

退出码: 0=成功 1=失败 2=没有找到可用数据
"""
import argparse
import csv
import html
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}

LEVEL_CN = {1: "province", 2: "city", 3: "area"}


def url_for(year):
    """民政部的年度文件发布在下一年目录里，例如 2024 版在 /2025/202401xzqh.html。"""
    return f"https://www.mca.gov.cn/mzsj/xzqh/{year + 1}/{year}01xzqh.html"


def fetch(url, timeout=60):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")


def cells(doc):
    out = []
    for m in re.finditer(r"<td[^>]*>(.*?)</td>", doc, re.S | re.I):
        text = re.sub(r"<[^>]+>", "", m.group(1))
        text = html.unescape(text).replace("\u00a0", " ").strip()
        if text:
            out.append(re.sub(r"\s+", " ", text))
    return out


def parse(doc):
    records, pending = [], None
    for text in cells(doc):
        if re.fullmatch(r"\d{6}", text):
            pending = text
            continue
        if pending and not re.search(r"\d", text) and len(text) <= 40:
            records.append((pending, text))
            pending = None
    return records


def build_rows(records):
    codes = {c for c, _ in records}
    rows = []
    for code, name in records:
        prov = code[:2] + "0000"
        city = code[:4] + "00"
        if code.endswith("0000"):
            rows.append((code, name, "province", ""))
        elif code.endswith("00"):
            rows.append((code, name, "city", prov))
        else:
            parent = city if city in codes else prov   # 直辖市 / 省直辖县级单位挂省
            rows.append((code, name, "area", parent))
    return rows


def probe_years(start=2026, stop=2020):
    """从新到旧探测可用的年度文件，返回 (year, doc)。"""
    for year in range(start, stop - 1, -1):
        url = url_for(year)
        try:
            doc = fetch(url, timeout=30)
        except urllib.error.HTTPError as e:
            print(f"  {year}: HTTP {e.code}")
            continue
        except Exception as e:
            print(f"  {year}: {type(e).__name__}")
            continue
        recs = parse(doc)
        if len(recs) < 2500:
            print(f"  {year}: 页面可访问但仅解析到 {len(recs)} 条，跳过")
            continue
        print(f"  {year}: OK，解析 {len(recs)} 条  {url}")
        return year, doc
    return None, None


def write_csv(rows, path):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["code", "name", "level", "parent_code"])
        w.writerows(rows)


def run(cmd, cwd=ROOT):
    print("  $ " + " ".join(cmd))
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    out = (p.stdout or "") + (p.stderr or "")
    print("\n".join("    " + line for line in out.strip().splitlines()[:12]))
    return p.returncode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, help="指定数据年份，如 2024")
    ap.add_argument("--dry-run", action="store_true", help="只检测不写文件")
    args = ap.parse_args()

    print("[1/5] 探测民政部最新年度代码")
    if args.year:
        year, doc = args.year, fetch(url_for(args.year))
        recs = parse(doc)
        print(f"  {year}: 解析 {len(recs)} 条")
    else:
        year, doc = probe_years()
    if not doc:
        print("没有取到可用数据，更新中止（保留现有文件）")
        return 2

    recs = parse(doc)
    rows = build_rows(recs)
    counts = {}
    for r in rows:
        counts[r[2]] = counts.get(r[2], 0) + 1
    print(f"[2/5] 解析完成：共 {len(rows)} 条 {counts}（{year} 年数据）")

    csv_path = os.path.join(ROOT, "data", "regions.csv")
    old_total = None
    if os.path.exists(csv_path):
        with open(csv_path, encoding="utf-8") as f:
            old_total = max(0, len(f.readlines()) - 1)
    print(f"  现有数据 {old_total} 条 → 新数据 {len(rows)} 条")

    if args.dry_run:
        print("dry-run：未写入任何文件")
        return 0

    write_csv(rows, csv_path)
    with open(os.path.join(ROOT, "data", "data-version.json"), "w", encoding="utf-8") as f:
        json.dump({"year": year, "records": len(rows), "updatedAt": time.strftime("%Y-%m-%d %H:%M:%S")},
                  f, ensure_ascii=False, indent=2)

    print("[3/5] 更新各市常住人口（红黑人口库 + 公报兜底）")
    if run([sys.executable, "tools/build_population.py"]) != 0:
        print("  人口更新失败，沿用现有 data/population.csv（不阻断后续步骤）")

    print("[4/5] 运行 Java 生成 JSON / 文本树")
    if run(["java", "-Dfile.encoding=UTF-8", "-Dstdout.encoding=UTF-8", "src/RegionTree.java"]) != 0:
        print("Java 运行失败，更新中止")
        return 1

    print("[5/5] 生成单文件页面（完整版 + 云版）")
    rc = run([sys.executable, "tools/build_html.py", "web/template.html",
              "out/china-region-tree.json", "out/index.html"])
    if rc != 0:
        return 1
    rc = run([sys.executable, "tools/build_cloud.py",
              "out/china-region-tree.json", "out/cloud.html"])
    if rc != 0:
        return 1
    print(f"更新完成：{year} 年版数据 {len(rows)} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
