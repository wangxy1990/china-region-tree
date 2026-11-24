#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 RegionTree 输出的嵌套 JSON 内联进 template.html，生成可双击打开的单文件页面。

用法: python tools/build_html.py web/template.html out/china-region-tree.json out/index.html
"""
import json
import os
import sys


def main(template, data_path, out_path):
    with open(template, encoding="utf-8") as f:
        html = f.read()
    with open(data_path, encoding="utf-8") as f:
        data = json.load(f)

    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # 防止字符串里出现 </script> 提前闭合标签
    payload = payload.replace("</", "<\\/")

    html = html.replace("__DATA__", payload)

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"生成 {out_path}: {os.path.getsize(out_path)} 字节, {data['total']} 个节点")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
