#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 china-division 的嵌套 pca-code.json（省-市-区县）压平为
code,name,level,parent_code 四列的 CSV，供 Java 程序读取。

说明:
  - 层级按“树的深度”判定（1=省 2=市 3=区县），而不是按编码长度。
    因为东莞、中山等不设区的地级市，第三级直接是镇/街道（9 位编码）。
  - 额外合并 HK-MO-TW.json，补齐台湾省、香港、澳门三个省级单位，
    其编码为占位编码（无官方 GB/T 2260 码），前缀 71/81/82 与国标省级前缀一致。

用法: python tools/flatten_pca.py <pca-code.json> <HK-MO-TW.json> <regions.csv>
"""
import csv
import json
import sys

LEVELS = {1: "province", 2: "city", 3: "area"}


def walk(node, parent_code, depth, out):
    code = str(node["code"])
    out.append((code, node["name"], LEVELS.get(depth, "area"), parent_code or ""))
    for child in node.get("children") or []:
        walk(child, code, depth + 1, out)


def merge_hk_mo_tw(hk_mo_tw, out):
    """把 {省: {市/区域: [区县...]}} 结构补成同样的扁平记录。"""
    prefix = {"台湾省": "71", "香港特别行政区": "81", "澳门特别行政区": "82"}
    for province, cities in hk_mo_tw.items():
        p_code = prefix[province]
        out.append((p_code, province, "province", ""))
        for i, (city, areas) in enumerate(cities.items(), start=1):
            c_code = f"{p_code}{i:02d}"
            out.append((c_code, city, "city", p_code))
            for j, area in enumerate(areas, start=1):
                out.append((f"{c_code}{j:02d}", area, "area", c_code))


def main(pca_path, hkmt_path, dst):
    with open(pca_path, encoding="utf-8") as f:
        data = json.load(f)
    rows = []
    for prov in data:
        walk(prov, None, 1, rows)

    try:
        with open(hkmt_path, encoding="utf-8") as f:
            merge_hk_mo_tw(json.load(f), rows)
    except FileNotFoundError:
        pass

    with open(dst, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["code", "name", "level", "parent_code"])
        writer.writerows(rows)

    counts = {}
    for r in rows:
        counts[r[2]] = counts.get(r[2], 0) + 1
    print(f"rows={len(rows)} {counts}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
