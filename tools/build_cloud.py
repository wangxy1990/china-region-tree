#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成可云托管的单文件页面：数据用 deflate-raw 压缩 + base64 内联，浏览器端解压。

用法: python tools/build_cloud.py out/china-region-tree.json out/cloud.html
"""
import base64
import json
import os
import re
import sys
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(ROOT, "web", "template.html")

DECODER = """const DATA = await (async () => {
  const bytes = Uint8Array.from(atob(window.__PAYLOAD__), c => c.charCodeAt(0));
  const text = await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('deflate-raw'))).text();
  return JSON.parse(text);
})();"""


def compact(node):
    """[code, name, plate, pop, popYear, gdp, gdpYear, urban, urbanYear, rural, ruralYear,
       urbanRank, ruralRank, children?]
    plate 形如 "苏E" 或 "苏E/苏U"，无车牌为空串；pop 为常住人口（人），gdp 为亿元，
    urban/rural 为元/人，*Rank 为该市范围内 1~3 名（其余 0），无数据为 0。"""
    plate = node.get("plate") or ""
    if node.get("plateAlt"):
        plate += "/" + node["plateAlt"]
    kids = node.get("children")
    item = [
        node["code"],
        node["name"],
        plate,
        node.get("pop") or 0,
        node.get("popYear") or 0,
        round(node.get("gdp") or 0, 2),
        node.get("gdpYear") or 0,
        round(node.get("urban") or 0, 2),
        node.get("urbanYear") or 0,
        round(node.get("rural") or 0, 2),
        node.get("ruralYear") or 0,
        node.get("urbanRank") or 0,
        node.get("ruralRank") or 0,
    ]
    if kids:
        item.append([compact(c) for c in kids])
    return item


def main(json_path, out_path):
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    payload = {"y": re.search(r"(\d{4})", data.get("source", "")) and int(re.search(r"(\d{4})", data["source"]).group(1)),
               "s": data.get("source", ""), "p": [compact(p) for p in data["provinces"]]}
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    # 注意：浏览器 DecompressionStream('deflate-raw') 只接受裸 deflate，需 wbits=-15
    comp = zlib.compressobj(9, zlib.DEFLATED, -15)
    packed = base64.b64encode(comp.compress(raw) + comp.flush()).decode("ascii")

    with open(TEMPLATE, encoding="utf-8") as f:
        html = f.read()

    html = html.replace("<script>\nconst DATA = __DATA__;",
                        f'<script>window.__PAYLOAD__ = "{packed}";</script>\n<script type="module">\n'
                        "const RAW = await (async () => {\n"
                        "  const bytes = Uint8Array.from(atob(window.__PAYLOAD__), c => c.charCodeAt(0));\n"
                        "  const text = await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('deflate-raw'))).text();\n"
                        "  return JSON.parse(text);\n"
                        "})();\n"
                        "const DATA = { source: RAW.s, levels: ['province','city','area'],\n"
                        "  generatedAt: new Date().toISOString().slice(0,10),\n"
                        "  provinces: RAW.p.map(n => revive(n, 1)) };\n"
                        "function revive(n, depth) {\n"
                        "  const code = n[0];\n"
                        "  const level = depth === 1 || code.endsWith('0000') ? 'province'\n"
                        "    : code.endsWith('00') ? 'city' : 'area';\n"
                        "  const node = { code, name: n[1], level };\n"
                        "  const plate = typeof n[2] === 'string' ? n[2] : '';\n"
                        "  if (plate) {\n"
                        "    const parts = plate.split('/');\n"
                        "    node.plate = parts[0];\n"
                        "    if (parts[1]) node.plateAlt = parts[1];\n"
                        "  }\n"
                        "  if (n[3]) { node.pop = n[3]; if (n[4]) node.popYear = n[4]; }\n"
                        "  if (n[5]) { node.gdp = n[5]; if (n[6]) node.gdpYear = n[6]; }\n"
                        "  if (n[7]) { node.urban = n[7]; if (n[8]) node.urbanYear = n[8]; }\n"
                        "  if (n[9]) { node.rural = n[9]; if (n[10]) node.ruralYear = n[10]; }\n"
                        "  if (n[11]) node.urbanRank = n[11];\n"
                        "  if (n[12]) node.ruralRank = n[12];\n"
                        "  const kids = Array.isArray(n[13]) ? n[13] : null;\n"
                        "  if (kids) node.children = kids.map(c => revive(c, depth + 1));\n"
                        "  return node;\n"
                        "}")
    html = html.replace("</script>\n</body>", "</script>\n</body>")

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"生成 {out_path}: {os.path.getsize(out_path)} 字节（payload {len(packed)} 字符，原始数据 {len(raw)} 字节）")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
