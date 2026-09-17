"""
一次性脚本：框架节号顺延 +5 之后，修正**指向框架**的交叉引用。

安全边界
--------
只改以下三种显式指向框架的写法：
  1. `框架 §N` / `框架 §N.M`
  2. `framework.md` §N / `framework.md`（…）§N
  3. 形如 `§20.2` / `§24.2` / `§8.1` 的**带小数点**引用
     （这些在 spec 里只可能指框架——各 spec 自己的子节编号都 ≤ §10）

**不动**裸的 `§8` / `§3.2`（spec 内部节号），避免误伤。

用法：
    python tools/fix_section_refs.py           # 干跑
    python tools/fix_section_refs.py --apply   # 落盘
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 旧节号 → 新节号（只含被顺延的部分；§1~§6 不变）
SHIFT = {
    "7": "12", "8": "13", "9": "14", "10": "15", "11": "16", "12": "17",
    "13": "18", "14": "19", "15": "20", "16": "21", "17": "22", "18": "23",
    "19": "24", "20": "25", "21": "26", "22": "27", "24": "28",
}
# 带小数的子节：由父节号顺延
SUB = {
    "8.1": "13.1", "8.2": "13.2",
    "13.1": "18.1", "13.2": "18.2", "13.3": "18.3", "13.4": "18.4",
    "13.5": "18.5", "13.6": "18.6",
    "12.1": "17.1", "11.1": "16.1", "14.1": "19.1",
    "19.0": "24.0", "19.1": "24.1", "19.2": "24.2",
    "20.1": "25.1", "20.2": "25.2", "20.3": "25.3", "20.4": "25.4",
    "20.5": "25.5", "20.6": "25.6", "20.7": "25.7", "20.8": "25.8",
    "20.9": "25.9",
    "24.1": "28.1", "24.2": "28.2",
    "5.1": "5.1", "5.2": "5.2", "5.3": "5.3", "5.4": "5.4",
}
# 反向：新节号里被写错的历史引用（§5.3 曾指"理论根基"，现指"切割线"）
# —— 这些由人工在主文档里处理，脚本不猜。

FILES = [
    "README.md", "CODE_OF_CONDUCT.md", "CONTRIBUTING.md",
    "docs/framework.md", "docs/rationale.md",
    "docs/open-questions", "proposals",
    "spec", "conformance", "reference",
]

SKIP_DIRS = {".git", "__pycache__", "docs/reviews", "tools"}

# 形如 `框架 §8.1`、`framework.md` §13、`（框架 §19）`
PAT_FRAMEWORK = re.compile(r"(框架\s*§|framework\.md[`）)]*\s*§)(\d+)(?:\.(\d+))?")
# 带小数的裸引用
PAT_SUB = re.compile(r"§(\d+)\.(\d+)")


def new_num(parent: str, sub: str | None) -> str | None:
    if sub is not None:
        key = f"{parent}.{sub}"
        if key in SUB:
            return SUB[key]
        return None
    return SHIFT.get(parent)


def fix_line(s: str) -> tuple[str, list[str]]:
    hits: list[str] = []

    def rep_fw(m: re.Match) -> str:
        got = new_num(m.group(2), m.group(3))
        if got is None:
            return m.group(0)
        hits.append(f"{m.group(2)}.{m.group(3)}→{got}" if m.group(3) else f"{m.group(2)}→{got}")
        return f"{m.group(1)}{got}"

    s2 = PAT_FRAMEWORK.sub(rep_fw, s)

    def rep_sub(m: re.Match) -> str:
        got = new_num(m.group(1), m.group(2))
        if got is None:
            return m.group(0)
        hits.append(f"§{m.group(1)}.{m.group(2)}→§{got}")
        return f"§{got}"

    s2 = PAT_SUB.sub(rep_sub, s2)
    return s2, hits


def main() -> int:
    apply = "--apply" in sys.argv
    targets: list[Path] = []
    for f in FILES:
        p = ROOT / f
        if p.is_dir():
            targets += [q for q in p.rglob("*")
                        if q.suffix in (".md", ".py")
                        and not any(sd in str(q) for sd in SKIP_DIRS)]
        elif p.exists():
            targets.append(p)

    total_files = total_hits = 0
    for p in sorted(set(targets)):
        if p.name.startswith("fix_section_refs"):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        lines = text.split("\n")
        n_hits = 0
        for i, s in enumerate(lines):
            s2, hits = fix_line(s)
            if hits:
                lines[i] = s2
                n_hits += len(hits)
        if n_hits:
            total_files += 1
            total_hits += n_hits
            rel = p.relative_to(ROOT)
            print(f"  {rel}: {n_hits} 处")
            if apply:
                p.write_text("\n".join(lines), encoding="utf-8", newline="\n")

    print(f"\n{'已写入' if apply else '（干跑）'}：{total_files} 个文件，{total_hits} 处引用")
    if not apply:
        print("加 --apply 落盘")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
