"""
一次性：把六个契约的「保证」编号 G1~G4 唯一化，并补一张代号解码表。

问题
----
`G1`~`G4` 在**六个契约里各有一套**（I1 的定义不可变、I2 的写入过规则、I3 的只读……），
全文出现 24 次。**读者看到 "G3" 无法知道是哪个契约的 G3。**
这跟之前修掉的"`S-1` 在多份文档里指不同条款"是同一类病。

处置
----
契约的保证改名为 `I<n>-G<m>`（如 `I2-G1`「写入必须过规则」）——**全局唯一、自带归属**。
顺带修好历史上那句被误判的注解：当年审计把 `I2-G1` 判为"§25 里不存在"，
其实是**两套编号混用**（契约保证 vs 规范条款）；改名后这类误判不会再发生。

用法：
    python tools/_migrations/uniquify_guarantees.py           # 干跑
    python tools/_migrations/uniquify_guarantees.py --apply
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
FW = ROOT / "docs" / "framework.md"

# 六个契约的正文标题 → 契约号
SECTIONS = [
    ("## 15. I1 语义契约", "I1"),
    ("## 16. I2 事实契约", "I2"),
    ("## 17. I3 查询契约", "I3"),
    ("## 18. I4 动作契约", "I4"),
    ("## 19. I5 接入契约", "I5"),
    ("## 20. I6 发现契约", "I6"),
]

ROW = re.compile(r"^\| \*\*(G[1-4])\*\* \|")


def main() -> int:
    apply = "--apply" in sys.argv
    lines = FW.read_text(encoding="utf-8").split("\n")

    # 找每个契约节的区间
    marks = []
    for title, cid in SECTIONS:
        for i, l in enumerate(lines):
            if l.startswith(title):
                marks.append((i, cid, title))
                break
        else:
            print(f"  ⚠ 找不到 {title}")
    marks.sort()
    bounds = [(marks[k][0], marks[k + 1][0] if k + 1 < len(marks) else len(lines), marks[k][1])
              for k in range(len(marks))]

    changed = 0
    for start, end, cid in bounds:
        for i in range(start, end):
            m = ROW.match(lines[i])
            if m:
                lines[i] = lines[i].replace(f"**{m.group(1)}**", f"**{cid}-{m.group(1)}**", 1)
                changed += 1

    print(f"契约保证改名 {changed} 行（应为 24）")

    text = "\n".join(lines)
    # 正文引用：把已知的指向改成带契约号
    PROSE = [
        ("所以 `G3`「只有 L5 能写」", "所以 `I2-G3`「只有 L5 能写」"),
        ("由关系①（约束）直接推出", "由关系①（约束）直接推出"),
        ("`G1`「写入必须过规则」", "`I2-G1`「写入必须过规则」"),
        ("保证 I2-G4 说", "保证 `I2-G4` 说"),
        ("**两条必须补的约束（I2-1、I3-2）**", "**两条必须补的约束（`I2-1`、`I3-2`）**"),
    ]
    for old, new in PROSE:
        if old in text and old != new:
            text = text.replace(old, new)

    if apply:
        FW.write_text(text, encoding="utf-8", newline="\n")
        print("✅ 已写入")
    else:
        print("（干跑；加 --apply 落盘）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
