"""一次性：消掉最后一处前缀撞号 BD-（i3 预算 vs i4 判据绑定）。

实测教训：两轮各自"按语义缩写"必然撞车——所以命名后必须**对着全表查重**，
而不是逐个判断"这个名字应该没人用"。
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

# i3 的 BD（budget）→ BGT
p = ROOT / "spec" / "i3-query-minimal.md"
t = p.read_text(encoding="utf-8")
t = re.sub(r"(?<![A-Za-z-])BD-(\d+)", r"BGT-\1", t)
t = t.replace("<!-- clauses: TR DV DR BD SR -->", "<!-- clauses: TR DV DR BGT SR -->")
p.write_text(t, encoding="utf-8", newline="\n")
print("i3: BD→BGT（budget）")
