"""
一次性脚本：消解 spec 之间剩余的条款前缀撞号。

背景
----
`tools/audit.py` 的登记表检查发现 8 个前缀被多份 spec 共用：
    S- Q- D-  （三份：i3 / i4 / module-discipline）
    G- A- C- E- F-  （两份）

已确认**零跨文档条款引用**（没有任何 spec 引用另一份 spec 的条款），
所以改名不会破坏引用。只改 spec 自身的编号 + 登记表。

不改的
------
框架的 `G-`（治理）保留：外部（Issue/讨论）可能已引用，改动代价大于收益，
改为在 §25 与 CONTRIBUTING 用文字限定文档名。

用法：
    python tools/_migrations/disambiguate_spec_prefixes.py           # 干跑
    python tools/_migrations/disambiguate_spec_prefixes.py --apply
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SPEC = ROOT / "spec"

# 文件 → [(旧前缀, 新前缀), ...]
RENAMES: dict[str, list[tuple[str, str]]] = {
    "i3-query-minimal.md": [("T", "TR"), ("D", "DV"), ("V", "DF"), ("Q", "BG"), ("S", "SR")],
    "i4-action-minimal.md": [("S", "ST"), ("A", "AT"), ("I", "ID"), ("C", "CC"),
                             ("R", "AU"), ("E", "EX"), ("B", "BD"), ("Q", "RP"),
                             ("M", "MI"), ("N", "NL"), ("X", "XAD"), ("D", "DF"), ("F", "FD")],
    "i6-discovery-minimal.md": [("G", "DG"), ("E", "EN"), ("F", "FC")],
    "module-discipline.md": [("A", "AC"), ("G", "BG"), ("S", "SV"), ("C", "CR"),
                             ("R", "RJ"), ("L", "LN")],
}


def main() -> int:
    apply = "--apply" in sys.argv
    total = 0

    for name, pairs in RENAMES.items():
        p = SPEC / name
        if not p.exists():
            print(f"  ⚠ 找不到 {name}")
            continue
        text = p.read_text(encoding="utf-8")
        n_file = 0

        for old, new in pairs:
            # 1) 条款编号本体：`X-12` 或 *X-12*（表格首列）
            pat = re.compile(rf"(?<![A-Za-z-]){re.escape(old)}-(\d+[a-z]?)\b")
            text, n1 = pat.subn(rf"{new}-\1", text)
            n_file += n1

        # 2) 登记表行
        m = re.search(r"<!--\s*clauses:\s*([^>]*?)-->", text)
        if m:
            prefs = m.group(1).split()
            mapping = dict(pairs)
            new_prefs = [mapping.get(x, x) for x in prefs if x != "（无自有条款；第三节逐字引用框架"]
            text = text[:m.start()] + "<!-- clauses: " + " ".join(new_prefs) + " -->" + text[m.end():]
            n_file += 1

        print(f"  {name}: {n_file} 处")
        total += n_file
        if apply:
            p.write_text(text, encoding="utf-8", newline="\n")

    print(f"\n{'已写入' if apply else '（干跑）'}：共 {total} 处")
    if not apply:
        print("加 --apply 落盘")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
