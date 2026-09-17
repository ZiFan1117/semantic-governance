"""一次性：v0.4 之后，把 spec 里指向框架的"接口"措辞改成"契约"。

只改**指向框架节**的引用（`framework.md` §N（I… 接口）），不动 spec 自己的用词。
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SPEC = ROOT / "spec"

RULES = [
    ("[`../docs/framework.md`](../docs/framework.md) §17（I3 查询接口）",
     "[`../docs/framework.md`](../docs/framework.md) §17（I3 查询契约）"),
    ("[`../docs/framework.md`](../docs/framework.md) §18（I4 动作接口）",
     "[`../docs/framework.md`](../docs/framework.md) §18（I4 动作契约）"),
    ("[`../docs/framework.md`](../docs/framework.md) §20（I6 发现能力）",
     "[`../docs/framework.md`](../docs/framework.md) §20（I6 发现契约）"),
    ("框架 §18 给出了 I4 的**候选设计**（要素清单）",
     "框架 §18 给出了 I4 的**候选设计**（契约要素清单）"),
    ("框架 §20 定义了 I6 的五条保证",
     "框架 §20 定义了 I6 的五条保证"),
]

for p in sorted(SPEC.glob("*.md")):
    t = p.read_text(encoding="utf-8")
    n = 0
    for old, new in RULES:
        if old in t and old != new:
            t = t.replace(old, new)
            n += 1
    if n:
        p.write_text(t, encoding="utf-8", newline="\n")
        print(f"  {p.name}: {n} 处")
print("完成")
