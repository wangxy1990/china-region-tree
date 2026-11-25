import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 全国省-市-区县 行政区划结构树（递归构建 + 递归输出）。
 *
 * <p>数据源：data/regions.csv（code,name,level,parent_code），由
 * tools/flatten_pca.py 从 china-division 最新包生成，含 34 个省级单位。
 *
 * <p>用法：
 * <pre>
 *   java RegionTree.java                    # 打印统计 + 第一个省的树 + 生成完整 JSON
 *   java RegionTree.java --tree             # 打印全部省市区树（约 3800 行）
 *   java RegionTree.java --lookup 320115    # 按编码/名称查一条记录的全路径
 *   java RegionTree.java --json out/tree.json --tree
 * </pre>
 *
 * <p>核心只有一个递归函数 buildTree：给定节点编码，递归挂载其所有子节点；
 * 序列化和打印同样按递归实现，因此层级加深（如再往下加街道）无需改代码。
 */
public class RegionTree {

    /** 层级，按树深度定义：省(1) - 市(2) - 区县(3)。 */
    public enum Level {
        PROVINCE("province"), CITY("city"), AREA("area");

        final String key;

        Level(String key) {
            this.key = key;
        }

        static Level of(int depth) {
            return switch (depth) {
                case 1 -> PROVINCE;
                case 2 -> CITY;
                default -> AREA;
            };
        }

        /** 从数据文件的 level 字段解析（直辖市所辖区县、东莞等不设区市都靠它保真）。 */
        static Level fromKey(String key) {
            for (Level l : values()) {
                if (l.key.equalsIgnoreCase(key)) {
                    return l;
                }
            }
            return AREA;
        }
    }

    /** 树节点。 */
    public static final class Node {
        final String code;
        final String name;
        final Level level;
        String plate;      // 车牌发牌代号，如 苏A
        String plateAlt;   // 增补号段，如 苏E 城市的 苏U
        Long pop;          // 常住人口（人），来自 data/population.csv
        Integer popYear;   // 人口数据所属年份
        final List<Node> children = new ArrayList<>();
        Node parent;

        Node(String code, String name, Level level) {
            this.code = code;
            this.name = name;
            this.level = level;
        }

        String fullPath() {
            return parent == null ? name : parent.fullPath() + " / " + name;
        }
    }

    /** 扁平记录。 */
    record Region(String code, String name, String level, String parentCode) {}

    public static void main(String[] args) throws IOException {
        String csvPath = "data/regions.csv";
        String platesPath = "data/plates.csv";
        String popPath = "data/population.csv";
        String jsonOut = "out/china-region-tree.json";
        String lookupKey = null;
        boolean printAll = false;

        for (int i = 0; i < args.length; i++) {
            switch (args[i]) {
                case "--csv" -> csvPath = args[++i];
                case "--plates" -> platesPath = args[++i];
                case "--pop" -> popPath = args[++i];
                case "--json" -> jsonOut = args[++i];
                case "--lookup" -> lookupKey = args[++i];
                case "--tree", "--all" -> printAll = true;
                case "-h", "--help" -> {
                    System.out.println("""
                            全国省市区结构树
                              --csv <path>      扁平数据文件，默认 data/regions.csv
                              --plates <path>   车牌映射，默认 data/plates.csv（不存在则跳过）
                              --pop <path>      常住人口，默认 data/population.csv（不存在则跳过）
                              --json <path>     输出的嵌套 JSON，默认 out/china-region-tree.json
                              --tree            打印完整树（不加则只打印第一个省）
                              --lookup <key>    按行政区划编码或名称查询全路径
                            """);
                    return;
                }
                default -> throw new IllegalArgumentException("未知参数: " + args[i]);
            }
        }

        // 1. 读扁平数据
        List<Region> records = loadCsv(Paths.get(csvPath));

        // 2. 建立 父->子 索引（保持数据原始顺序）
        Map<String, List<Region>> childrenOf = new LinkedHashMap<>();
        List<Region> roots = new ArrayList<>();
        for (Region r : records) {
            if (r.parentCode() == null || r.parentCode().isEmpty()) {
                roots.add(r);
            } else {
                childrenOf.computeIfAbsent(r.parentCode(), k -> new ArrayList<>()).add(r);
            }
        }

        // 3. 递归建树
        List<Node> forest = new ArrayList<>();
        for (Region root : roots) {
            forest.add(buildTree(root, childrenOf));
        }

        // 3.5 挂车牌代号（可选，来自 data/plates.csv）
        Map<String, String[]> plates = loadPlates(Paths.get(platesPath));
        for (Node root : forest) {
            attachPlates(root, plates);
        }

        // 3.6 挂常住人口（可选，来自 data/population.csv）
        Map<String, Object[]> pops = loadPopulation(Paths.get(popPath));
        for (Node root : forest) {
            attachPopulation(root, pops);
        }

        // 4. 统计
        Map<Level, Integer> counts = new LinkedHashMap<>();
        for (Level l : Level.values()) {
            counts.put(l, 0);
        }
        int maxDepth = countRecursively(forest, 1, counts);
        System.out.printf("数据文件 : %s%n", csvPath);
        System.out.printf("省级单位 : %d%n市级单位 : %d%n区县单位 : %d%n合计 %d 条，最大深度 %d%n",
                counts.get(Level.PROVINCE), counts.get(Level.CITY), counts.get(Level.AREA),
                records.size(), maxDepth);

        // 5. 查询
        if (lookupKey != null) {
            System.out.println();
            boolean found = false;
            for (Node root : forest) {
                List<Node> path = new ArrayList<>();
                if (findPath(root, lookupKey, path)) {
                    Node target = path.get(path.size() - 1);
                    System.out.println("命中: " + target.code + " " + target.name
                            + " [" + target.level.key + "]");
                    System.out.println("全路径: " + target.fullPath());
                    found = true;
                    break;
                }
            }
            if (!found) {
                System.out.println("未找到: " + lookupKey);
            }
        }

        // 6. 打印树
        System.out.println();
        if (printAll) {
            for (Node root : forest) {
                printTree(root, "", true, 1);
            }
        } else {
            printTree(forest.get(0), "", true, 1);
            System.out.println("... 其余 " + (forest.size() - 1) + " 个省级单位略，用 --tree 查看全部");
        }

        // 7. 递归序列化为嵌套 JSON
        Path out = Paths.get(jsonOut);
        if (out.getParent() != null) {
            Files.createDirectories(out.getParent());
        }
        StringBuilder sb = new StringBuilder(1 << 20);
        sb.append("{\n");
        sb.append("  \"generatedBy\": \"RegionTree.java\",\n");
        sb.append("  \"generatedAt\": \"").append(java.time.LocalDate.now()).append("\",\n");
        sb.append("  \"source\": \"民政部《2024年中华人民共和国县以上行政区划代码》\",\n");
        sb.append("  \"levels\": [\"province\", \"city\", \"area\"],\n");
        sb.append("  \"total\": ").append(records.size()).append(",\n");
        sb.append("  \"provinces\": [\n");
        for (int i = 0; i < forest.size(); i++) {
            writeJson(forest.get(i), sb, "    ", i == forest.size() - 1);
        }
        sb.append("  ]\n}\n");
        Files.writeString(out, sb.toString(), StandardCharsets.UTF_8);
        System.out.printf("%n已写出 JSON: %s (%d 字节)%n", out.toAbsolutePath(),
                Files.size(out));
    }

    /**
     * 递归建树：为当前记录创建节点，并把它所有直接子记录递归挂到 children 上。
     */
    private static Node buildTree(Region record, Map<String, List<Region>> childrenOf) {
        Node node = new Node(record.code(), record.name(), Level.fromKey(record.level()));
        List<Region> children = childrenOf.get(record.code());
        if (children != null) {
            for (Region child : children) {
                Node childNode = buildTree(child, childrenOf);
                childNode.parent = node;
                node.children.add(childNode);
            }
        }
        return node;
    }

    /** 递归统计各层级数量并返回最大深度。 */
    private static int countRecursively(List<Node> nodes, int depth, Map<Level, Integer> counts) {
        int max = depth;
        for (Node node : nodes) {
            counts.merge(node.level, 1, Integer::sum);
            if (!node.children.isEmpty()) {
                max = Math.max(max, countRecursively(node.children, depth + 1, counts));
            }
        }
        return max;
    }

    /** 递归按编码或名称查找，命中时 path 里是从省到目标的完整链路。 */
    private static boolean findPath(Node node, String key, List<Node> path) {
        if (node.code.equals(key) || node.name.equals(key)) {
            path.add(node);
            return true;
        }
        for (Node child : node.children) {
            path.add(node);
            if (findPath(child, key, path)) {
                return true;
            }
            path.remove(path.size() - 1);
        }
        return false;
    }

    /** 递归打印缩进树。 */
    private static void printTree(Node node, String prefix, boolean isTail, int depth) {
        String connector = depth == 1 ? "" : (isTail ? "└─ " : "├─ ");
        String plate = node.plate == null ? "" : " [" + node.plate
                + (node.plateAlt == null ? "" : "/" + node.plateAlt) + "]";
        String pop = node.pop == null ? "" : " 常住 " + formatPop(node.pop)
                + (node.popYear == null ? "" : "(" + node.popYear + ")");
        System.out.printf("%s%s%s%s%s (%s, %s)%n", prefix, connector, node.name, plate, pop, node.code, node.level.key);
        String childPrefix = depth == 1 ? "" : prefix + (isTail ? "   " : "│  ");
        for (int i = 0; i < node.children.size(); i++) {
            printTree(node.children.get(i), childPrefix, i == node.children.size() - 1, depth + 1);
        }
    }

    /** 递归序列化节点为 JSON。 */
    private static void writeJson(Node node, StringBuilder sb, String indent, boolean last) {
        sb.append(indent).append("{\"code\": \"").append(escape(node.code))
                .append("\", \"name\": \"").append(escape(node.name))
                .append("\", \"level\": \"").append(node.level.key).append("\"");
        if (node.plate != null) {
            sb.append(", \"plate\": \"").append(escape(node.plate)).append("\"");
        }
        if (node.plateAlt != null) {
            sb.append(", \"plateAlt\": \"").append(escape(node.plateAlt)).append("\"");
        }
        if (node.pop != null) {
            sb.append(", \"pop\": ").append(node.pop);
            if (node.popYear != null) {
                sb.append(", \"popYear\": ").append(node.popYear);
            }
        }
        if (node.children.isEmpty()) {
            sb.append("}");
        } else {
            sb.append(", \"children\": [\n");
            for (int i = 0; i < node.children.size(); i++) {
                writeJson(node.children.get(i), sb, indent + "  ", i == node.children.size() - 1);
            }
            sb.append(indent).append("]}");
        }
        sb.append(last ? "\n" : ",\n");
    }

    /** 读取车牌映射 code,name,plate,alt（文件不存在时返回空表）。 */
    private static Map<String, String[]> loadPlates(Path path) throws IOException {
        Map<String, String[]> map = new LinkedHashMap<>();
        if (!Files.exists(path)) {
            return map;
        }
        for (String line : Files.readAllLines(path, StandardCharsets.UTF_8)) {            if (line.isBlank() || line.startsWith("code,")) {
                continue;
            }
            List<String> f = splitCsv(line);
            if (f.size() < 3) {
                continue;
            }
            String code = f.get(0).replace("\uFEFF", "").trim();
            String plate = f.get(2).trim();
            String alt = f.size() > 3 ? f.get(3).trim() : "";
            if (!code.isEmpty() && !plate.isEmpty()) {
                map.put(code, new String[]{plate, alt.isEmpty() ? null : alt});
            }
        }
        return map;
    }

    /** 递归把车牌代号挂到对应节点。 */
    private static void attachPlates(Node node, Map<String, String[]> plates) {
        String[] p = plates.get(node.code);
        if (p != null) {
            node.plate = p[0];
            node.plateAlt = p[1];
        }
        for (Node child : node.children) {
            attachPlates(child, plates);
        }
    }

    /** 读取常住人口表 code,name,pop,pop_year,source（文件不存在时返回空表）。 */
    private static Map<String, Object[]> loadPopulation(Path path) throws IOException {
        Map<String, Object[]> map = new LinkedHashMap<>();
        if (!Files.exists(path)) {
            return map;
        }
        for (String line : Files.readAllLines(path, StandardCharsets.UTF_8)) {
            if (line.isBlank() || line.startsWith("code,")) {
                continue;
            }
            List<String> f = splitCsv(line);
            if (f.size() < 3) {
                continue;
            }
            String code = f.get(0).replace("\uFEFF", "").trim();
            String pop = f.get(2).trim();
            String year = f.size() > 3 ? f.get(3).trim() : "";
            if (code.isEmpty() || pop.isEmpty()) {
                continue;
            }
            try {
                map.put(code, new Object[]{Long.parseLong(pop),
                        year.isEmpty() ? null : Integer.valueOf(year)});
            } catch (NumberFormatException ignored) {
                // 跳过异常行
            }
        }
        return map;
    }

    /** 递归把常住人口挂到对应节点。 */
    @SuppressWarnings("unchecked")
    private static void attachPopulation(Node node, Map<String, Object[]> pops) {
        Object[] p = pops.get(node.code);
        if (p != null) {
            node.pop = (Long) p[0];
            node.popYear = (Integer) p[1];
        }
        for (Node child : node.children) {
            attachPopulation(child, pops);
        }
    }

    /** 人口格式化为“xx 万”便于阅读。 */
    private static String formatPop(Long pop) {
        if (pop == null) {
            return "";
        }
        double wan = pop / 10000.0;
        return wan >= 100 ? String.format("%.0f 万", wan) : String.format("%.2f 万", wan);
    }

    private static String escape(String s) {
        StringBuilder out = new StringBuilder(s.length());
        for (char c : s.toCharArray()) {
            switch (c) {
                case '"' -> out.append("\\\"");
                case '\\' -> out.append("\\\\");
                case '\n' -> out.append("\\n");
                case '\r' -> out.append("\\r");
                case '\t' -> out.append("\\t");
                default -> {
                    if (c < 0x20) {
                        out.append(String.format("\\u%04x", (int) c));
                    } else {
                        out.append(c);
                    }
                }
            }
        }
        return out.toString();
    }

    /** 读取扁平 CSV（表头 code,name,level,parent_code），支持双引号包裹字段。 */
    private static List<Region> loadCsv(Path path) throws IOException {
        List<String> lines = Files.readAllLines(path, StandardCharsets.UTF_8);
        // 兼容 UTF-8 BOM
        if (!lines.isEmpty() && lines.get(0).startsWith("\uFEFF")) {
            lines.set(0, lines.get(0).substring(1));
        }
        List<Region> records = new ArrayList<>(lines.size());
        for (int i = 1; i < lines.size(); i++) {
            String line = lines.get(i);
            if (line.isBlank()) {
                continue;
            }
            List<String> fields = splitCsv(line);
            if (fields.size() < 4) {
                continue;
            }
            String code = fields.get(0).trim();
            String name = fields.get(1).trim();
            if (code.isEmpty() || name.isEmpty()) {
                continue;
            }
            records.add(new Region(code, name, fields.get(2).trim(), fields.get(3).trim()));
        }
        return records;
    }

    private static List<String> splitCsv(String line) {
        List<String> fields = new ArrayList<>(4);
        StringBuilder cur = new StringBuilder();
        boolean inQuotes = false;
        for (int i = 0; i < line.length(); i++) {
            char c = line.charAt(i);
            if (inQuotes) {
                if (c == '"') {
                    if (i + 1 < line.length() && line.charAt(i + 1) == '"') {
                        cur.append('"');
                        i++;
                    } else {
                        inQuotes = false;
                    }
                } else {
                    cur.append(c);
                }
            } else if (c == '"') {
                inQuotes = true;
            } else if (c == ',') {
                fields.add(cur.toString());
                cur.setLength(0);
            } else {
                cur.append(c);
            }
        }
        fields.add(cur.toString());
        return fields;
    }
}


