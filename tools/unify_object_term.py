"""
一次性脚本：把 framework.md 正文里的"概念"统一为"对象"。

五要素里这个要素叫 **对象**（§4 术语表已定义"对象 = 本框架对概念的称谓"），
但第一、四、六~九部分还大量沿用 v0.2 的"概念"称谓。

**保留**（必须）：
  - §4 / §5 的"Ossie 载体"表（那里 `concept` 是 Ossie 的真实字段名）
  - I1 的操作名 `GetConcept` / `ListConcepts` / `GetMappings(concept)` 等接口签名
  - §19 里"概念与存储必须分层"这种转述 Ossie/理论原话的句子

用法：
    python tools/unify_object_term.py           # 干跑
    python tools/unify_object_term.py --apply
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FW = ROOT / "docs" / "framework.md"

# 含这些片段的行**整行跳过**（Ossie 载体名、接口签名、理论转述）
SKIP_FRAGMENTS = (
    "`concept`", "GetConcept", "ListConcepts", "GetMappings", "GetActions",
    "GetConstraints", "GetDerivations", "ListRelations",
    "概念与存储必须分层",          # 转述理论原话
    "这是本框架对",                # §4 术语桥接行
    "**概念**",                    # 术语桥接的另一处写法
    "实体是语义概念",              # 这里"概念"= notion（术语义），不是要素名
)


def main() -> int:
    apply = "--apply" in sys.argv
    lines = FW.read_text(encoding="utf-8").split("\n")
    changed: list[tuple[int, str, str]] = []

    for i, s in enumerate(lines):
        if "概念" not in s:
            continue
        if any(frag in s for frag in SKIP_FRAGMENTS):
            continue
        new = s.replace("概念", "对象")
        changed.append((i + 1, s.strip(), new.strip()))

    for ln, old, new in changed:
        print(f"  {ln}")
        print(f"    - {old}")
        print(f"    + {new}")

    print(f"\n{'已写入' if apply else '（干跑）'}：{len(changed)} 行")
    if apply:
        for i, _old, _new in changed:
            lines[i - 1] = lines[i - 1].replace("概念", "对象")
        FW.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    else:
        print("加 --apply 落盘")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
