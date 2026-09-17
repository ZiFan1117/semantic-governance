"""
一次性脚本：消解条款编号跨文档撞号。

问题
----
框架的 Agent-first 组用 `A-1`~`A-5`，而《模块纪律》与 I4 规范各有一组
自己的 `A-1`~`A-4`（原子纪律 / 原子性）。三处都短到无法自辨。

处置
----
1. 框架的 Agent-first 组改名 `A-n` → `AG-n`（agent），全局唯一。
2. 三处**未限定**的跨文档引用补上文档名（i4 / i6 / module-discipline）。
3. 框架 §20.9 补一句"本组编号为 `AG-n`"的说明。

治理组 `G-n` 不改名（改动外部引用风险大于收益），改为在引用处一律限定文档名。

用法：
    python tools/disambiguate_clause_ids.py           # 干跑
    python tools/disambiguate_clause_ids.py --apply
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FW = ROOT / "docs" / "framework.md"

# 跨文档引用：补限定词（必须在 A-n 改名之前做，否则锚点就变了）
EXTERNAL = [
    (ROOT / "spec" / "i4-action-minimal.md",
     "框架 `A-2` 要求", "框架 `AG-2` 要求"),
    (ROOT / "spec" / "i6-discovery-minimal.md",
     "框架 `A-2` 要求", "框架 `AG-2` 要求"),
    (ROOT / "spec" / "module-discipline.md",
     "这正是框架 `A-2`「拒绝可自纠」的前提。",
     "这正是框架 `AG-2`「拒绝可自纠」的前提。"),
]


def main() -> int:
    apply = "--apply" in sys.argv
    total = 0

    for path, old, new in EXTERNAL:
        t = path.read_text(encoding="utf-8")
        if old not in t:
            print(f"  ⚠ {path.name}: 锚点未命中 → {old!r}")
            continue
        print(f"  {path.name}: {old[:24]}… → {new[:26]}…")
        total += 1
        if apply:
            path.write_text(t.replace(old, new), encoding="utf-8", newline="\n")

    # 框架内 A-n → AG-n（Agent-first 组；本文件里 A-n 只可能是这一组）
    t = FW.read_text(encoding="utf-8")
    new_t, n = re.subn(r"(?<![A-Za-z-])\bA-([1-5])\b", r"AG-\1", t)
    print(f"  docs/framework.md: A-n → AG-n  {n} 处")
    total += n
    if apply:
        FW.write_text(new_t, encoding="utf-8", newline="\n")

    print(f"\n{'已写入' if apply else '（干跑）'}：共 {total} 处")
    if not apply:
        print("加 --apply 落盘")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
