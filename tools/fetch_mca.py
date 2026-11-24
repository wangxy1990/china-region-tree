#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓取民政部“县以上行政区划代码”页面并解析为 code,name,level,parent_code 的 CSV。

民政部页面是 Excel 导出的 HTML，单元格被拆得很碎，因此采用“线性扫描单元格”：
凡是纯 6 位数字的单元格作为编码，其后第一个非空且不含数字的单元格作为名称。

用法: python tools/fetch_mca.py <页面URL> <输出CSV>
"""
import csv
import html
import re
import sys
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    raw = urllib.request.urlopen(req, timeout=60).read()
    return raw.decode("utf-8", "ignore")


def cells(doc):
    """按顺序返回所有单元格纯文本。"""
    out = []
    for m in re.finditer(r"<td[^>]*>(.*?)</td>", doc, re.S | re.I):
        text = re.sub(r"<[^>]+>", "", m.group(1))
        text = html.unescape(text).replace("\u00a0", " ").strip()
        if text:
            out.append(re.sub(r"\s+", " ", text))
    return out


def parse(doc):
    records = []      # (code, name)
    pending = None
    for text in cells(doc):
        if re.fullmatch(r"\d{6}", text):
            pending = text
            continue
        if pending and not re.search(r"\d", text) and len(text) <= 40:
            records.append((pending, text))
            pending = None
    return records


def build_rows(records):
    """按编码前缀挂层级，兼容直辖市（无地级）与省直辖县级单位。"""
    codes = {c for c, _ in records}
    rows = []
    names = dict(records)
    for code, name in records:
        prov = code[:2] + "0000"
        city = code[:4] + "00"
        if code.endswith("0000"):
            rows.append((code, name, 1, ""))
        elif code.endswith("00"):
            rows.append((code, name, 2, prov))
        else:
            # 县级：优先挂地级，地级不存在则挂省级（直辖市 / 省直辖县）
            parent = city if city in codes else prov
            rows.append((code, name, 3, parent))
    # 只用 1/2/3 层级，level 由深度决定
    return [(c, n, {1: "province", 2: "city", 3: "area"}[lv], p) for c, n, lv, p in rows]


def main(url, dst):
    doc = fetch(url)
    recs = parse(doc)
    print(f"解析记录: {len(recs)}")
    rows = build_rows(recs)
    with open(dst, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["code", "name", "level", "parent_code"])
        w.writerows(rows)
    counts = {}
    for r in rows:
        counts[r[2]] = counts.get(r[2], 0) + 1
    print(f"写出 {len(rows)} 行 {counts}")
    for code, name, lv, parent in rows:
        if lv == "province":
            print(" ", code, name)
    # 抽样检查
    for code, name, lv, parent in rows[:8]:
        print("  样本:", code, name, lv, parent)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
