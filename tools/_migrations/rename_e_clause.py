"""
一次性脚本：把框架 §25.2 的要素条款编号 E-1~E-8 改名为 ELE-1~ELE-8。

为什么改
--------
i4 规范有一组**老的、被本规范反复引用**的表达式语言条款也叫 `E-1`~`E-4`。
两套同号会造成"读者只看到 E-2 不知道是哪份文档的"。
框架这组是新加的、引用面小，所以改框架这组。

顺带：修正 i6 头部的 `E-4`~`E-6` 引用（改为按标题引用），避免跨文档撞号。

用法：
    python tools/rename_e_clause.py           # 干跑
    python tools/rename_e_clause.py --apply
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FW = ROOT / "docs" / "framework.md"
I6 = ROOT / "spec" / "i6-discovery-minimal.md"


def main() -> int:
    apply = "--apply" in sys.argv
    total = 0

    # ---- framework.md：E-n → ELEn（只动 §25.2 那一段与指向它的引用） ----
    text = FW.read_text(encoding="utf-8")
    # 保护边界：本文件里 E-n 只可能是要素条款（i4 的 E 组不在本文件）
    new, n = re.subn(r"\bE-([1-8])\b", r"ELE-\1", text)
    print(f"  docs/framework.md: E-n → ELEn  {n} 处")
    total += n
    if apply:
        FW.write_text(new, encoding="utf-8", newline="\n")

    # ---- i6：把指向框架 E 组的引用改成按节引用（无编号可撞） ----
    t6 = I6.read_text(encoding="utf-8")
    old = "框架 §25.2 `E-4`~`E-6` 是条件式"
    new6 = "框架 §25.2 的**策略条款是条件式**"
    if old in t6:
        t6 = t6.replace(old, new6)
        print("  spec/i6-discovery-minimal.md: 1 处（改为按节引用）")
        total += 1
        if apply:
            I6.write_text(t6, encoding="utf-8", newline="\n")
    else:
        print("  ⚠ i6 的锚点未命中，请人工确认")

    print(f"\n{'已写入' if apply else '（干跑）'}：共 {total} 处")
    if not apply:
        print("加 --apply 落盘")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
