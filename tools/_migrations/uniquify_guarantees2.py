"""一次性（补齐）：上一脚本只匹配了 `**G1**` 加粗形式，漏掉未加粗的 `G1`。"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
FW = ROOT / "docs" / "framework.md"

SECTIONS = [
    ("## 15. I1 语义契约", "I1"), ("## 16. I2 事实契约", "I2"),
    ("## 17. I3 查询契约", "I3"), ("## 18. I4 动作契约", "I4"),
    ("## 19. I5 接入契约", "I5"), ("## 20. I6 发现契约", "I6"),
]
# 行首是 | G1 | 或 | **G1** | 或 | `G1` |
ROW = re.compile(r"^\|\s*(\*{0,2})(G[1-4])\1\s*\|")

lines = FW.read_text(encoding="utf-8").split("\n")
marks = []
for title, cid in SECTIONS:
    for i, l in enumerate(lines):
        if l.startswith(title):
            marks.append((i, cid))
            break
marks.sort()

fixed = 0
for k, (start, cid) in enumerate(marks):
    end = marks[k + 1][0] if k + 1 < len(marks) else len(lines)
    for i in range(start, end):
        m = ROW.match(lines[i])
        if m and not lines[i].startswith(f"| {cid}-"):
            lines[i] = lines[i].replace(m.group(2), f"{cid}-{m.group(2)}", 1)
            fixed += 1

FW.write_text("\n".join(lines), encoding="utf-8", newline="\n")
print(f"补齐 {fixed} 行")

t = "\n".join(lines)
left = [f"{i+1}: {l.strip()[:70]}" for i, l in enumerate(lines)
        if re.match(r"^\|\s*\*{0,2}G[1-4]", l)]
print(f"仍未加契约号的保证行：{len(left)}")
for x in left:
    print("   ", x)
