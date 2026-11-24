# 全国省市区行政区划结构树（Java 实现）

纯 JDK、零第三方依赖的 Java 程序，读取扁平行政区划数据，**递归构建**「省 → 市 → 区县」结构树，并递归输出为嵌套 JSON 和缩进文本树。

## 数据规模

| 层级 | 数量 | 说明 |
| --- | --- | --- |
| province 省级 | 34 | 22 省 + 台湾省 + 5 自治区 + 4 直辖市 + 2 特别行政区 |
| city 地级 | 333 | 含省直辖县级单位（济源、仙桃、石河子等，按民政部口径直接挂在省下） |
| area 区县级 | 2846 | 市辖区、县级市、县、自治县、旗等 |
| 合计 | 3213 | 最大深度 3 |

数据源为**民政部《2024年中华人民共和国县以上行政区划代码》**（`mca.gov.cn`，2025 年发布的最新年度代码表），已包含 2024 年 11 月新公布的三沙市西沙区（460302）、南沙区（460303）等变更。

## 目录结构

```
china-region-tree/
├── src/RegionTree.java             # 主程序（单文件，可直接 java 运行）
├── data/regions.csv                # 主数据：code,name,level,parent_code（民政部 2024 版）
├── data/regions_china_division.csv # 备用数据：含港澳台区县与东莞/中山镇街（统计局 2023 版，3840 条）
├── data/pca-code-2023.json         # 备用数据的原始省市区嵌套 JSON
├── data/HK-MO-TW.json              # 港澳台区县原始数据
├── data/plates.csv                 # 车牌发牌代号：code,name,plate,alt（357 条）
├── data/data-version.json          # 当前数据版本（年份、来源 URL、生成时间）
├── tools/fetch_mca.py              # 抓取并解析民政部代码页面 → CSV
├── tools/flatten_pca.py            # 统计用区划代码嵌套 JSON → 扁平 CSV
├── tools/build_plates.py           # 各省字母表 → 车牌映射 CSV（含旧地名别名、前缀兜底）
├── tools/build_html.py             # 把 JSON 内联进模板，生成单文件浏览页面
├── tools/build_cloud.py            # 生成压缩内联的云托管版页面
├── tools/update.py                 # 探测最新年份 → 抓取 → 重建 CSV / JSON / 页面
├── web/template.html               # 页面模板（样式 + 交互）
├── out/index.html                  # 交付：可双击打开的结构树浏览页（离线、单文件）
├── out/cloud.html                  # 云端精简版（deflate-raw + base64 内联，约 52 KB）
├── out/china-region-tree.json      # 输出：嵌套结构树（约 230 KB）
└── out/china-region-tree.txt        # 输出：缩进文本树（全量 3213 条）
```

## 浏览页面

`out/index.html` 是自包含单文件（数据内联，无需服务器，双击即可打开），由 `tools/build_html.py` 生成：

```powershell
python tools\build_html.py web\template.html out\china-region-tree.json out\index.html
```

页面能力：省市县三级可逐级展开／收起（点名称或箭头都行）、按名称、编码或**车牌代号**搜索并自动定位高亮、点击节点显示「省 › 市 › 区县」面包屑并可复制、一键展开全部／收起全部，顶部显示各层级数量统计。

## 车牌代号

每个市级节点名称后面跟一枚仿蓝牌的小牌子，显示该市发牌机关代号（如 南京 `苏A`、深圳 `粤B`），直辖市与省同名前缀的节点用橙牌（京A/津A/沪A/渝A）；有增补号段的城市（如 苏州 `苏E` + `苏U`、青岛 `鲁B` + `鲁U`）在蓝牌后面再跟一枚浅色印章。搜索框直接输入 `苏A`、`粤B`、`苏U` 都能命中。

数据由 `tools/build_plates.py` 生成到 `data/plates.csv`（357 条，覆盖 333 个地级节点中的绝大多数 + 省直辖县级单位）：内置 31 个省级单位的字母对照表，处理了「襄樊→襄阳」「思茅→普洱」「铜仁地区→铜仁」等旧地名别名，并对「白沙黎族自治县」这类名称做前缀兜底匹配。Java 侧在 `attachPlates` 递归里按 6 位编码回填，`--plates` 可换映射文件，文件缺失时自动跳过。

```powershell
python tools\build_plates.py     # 重新生成 data\plates.csv
```

目前唯一没有车牌的是三沙市（发牌归属待确认），省级节点除直辖市外不显示车牌。

## 运行

```powershell
cd D:\agent-workspace\china-region-tree
java -Dfile.encoding=UTF-8 src\RegionTree.java                    # 统计 + 北京市树 + 生成 JSON
java -Dfile.encoding=UTF-8 src\RegionTree.java --tree             # 打印全国完整树
java -Dfile.encoding=UTF-8 src\RegionTree.java --lookup 320115    # 按编码/名称查全路径
java -Dfile.encoding=UTF-8 src\RegionTree.java --plates 其他车牌表.csv --tree
java -Dfile.encoding=UTF-8 src\RegionTree.java --csv data\regions_china_division.csv --tree   # 换备用数据
```

Windows 控制台如出现乱码，先执行 `[Console]::OutputEncoding = [System.Text.Encoding]::UTF8`。

## 递归设计

核心只有一个递归函数，层级深浅变化无需改代码：

```java
private static Node buildTree(Region record, Map<String, List<Region>> childrenOf) {
    Node node = new Node(record.code(), record.name(), Level.fromKey(record.level()));
    List<Region> children = childrenOf.get(record.code());
    if (children != null) {
        for (Region child : children) {
            Node childNode = buildTree(child, childrenOf);   // 递归挂载子树
            childNode.parent = node;
            node.children.add(childNode);
        }
    }
    return node;
}
```

- `buildTree` 递归建树（自顶向下挂载，`parent` 指针同时回填，`fullPath()` 可递归得到「江苏省 / 南京市 / 江宁区」）
- `countRecursively` 递归统计各层级数量与最大深度
- `writeJson` 递归序列化嵌套 JSON
- `printTree` 递归打印 `├─` / `└─` 缩进树
- `findPath` 递归按编码或名称定位并返回全链路

层级取自数据文件的 `level` 字段而不是树深度，因此能正确表达两类特殊情况：直辖市所辖区县直接挂在省下（深度 2 却是区县级），东莞/中山/儋州/嘉峪关等不设区的地级市没有区县子节点。

## 数据口径与边界

- 民政部《县以上行政区划代码》只到县级，不含乡级（镇/街道）；需要镇街请用 `data/regions_china_division.csv`（含东莞、中山的 9 位编码镇街）。
- 港澳台在民政部代码表中只有省级节点（710000 / 810000 / 820000），无可信的下级代码；需要港澳台区县的展示数据可用备用 CSV（其编码是按前缀规则生成的占位码，仅用于建树展示）。
- 区县名称保留原文，含「*」是民政部表中标注的省直辖县级单位。
- 数据为静态快照，行政区划调整后需重跑 `tools/fetch_mca.py` 更新 CSV。

## JSON 格式

```json
{
  "generatedBy": "RegionTree.java",
  "levels": ["province", "city", "area"],
  "total": 3213,
  "provinces": [
    {
      "code": "320000", "name": "江苏省", "level": "province",
      "children": [
        { "code": "320100", "name": "南京市", "level": "city", "plate": "苏A",
          "children": [
            { "code": "320115", "name": "江宁区", "level": "area" }
          ]
        }
      ]
    }
  ]
}
```
