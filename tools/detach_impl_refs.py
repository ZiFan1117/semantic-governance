"""
一次性脚本：删掉 reference/ 与 conformance/ 之后，把规范里**指向已删产物**的措辞降级为自洽表述。

原则：**保留"这条来自实现反馈"的事实，去掉指向已删代码的指针。**
      —— 证据的价值在条款里，不在被删的代码里。

用法：
    python tools/detach_impl_refs.py           # 干跑
    python tools/detach_impl_refs.py --apply   # 落盘
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 按序替换（长的先跑，避免子串被短规则先吃掉）
RULES: list[tuple[str, str]] = [
    # ---- 指向已删目录的指针 ----
    ("。参考实现见 [`../reference/`](../reference/)。",
     "。这些缺口的**条款与理由都保留在正文里**，不需要读实现才能理解。"),
    ("（`reference/expr.py`）用的是 **CEL 子集**", "曾用 **CEL 子集**"),
    # ---- "参考实现" → 中性的"实现反馈 / 实践"（保留事实，去掉指向） ----
    ("依据 bazidiy 参考实现第二次回写", "依据 bazidiy 实战实现第二次回写"),
    ("来自 bazidiy 参考实现 S1", "来自 bazidiy 实战实现 S1"),
    ("## 9. 参考实现反馈", "## 9. 实现反馈"),
    ("**参考实现反馈**", "**实现反馈**"),
    ("依据参考实现反馈修正", "依据实现反馈修正"),
    ("写参考实现时才暴露出来的", "写实现时才暴露出来的"),
    ("这是参考实现**实际踩到的坑**", "这是实现**实际踩到的坑**"),
    ("**参考实现的临时选择**", "**实现反馈中的临时选择**"),
    ("**参考实现的判断**", "**实现反馈中的判断**"),
    ("参考实现的做法是给审计记录", "一种做法是给审计记录"),
    ("参考实现的做法：人读面由生成器产出", "实践做法：人读面由生成器产出"),
    ("参考实现过程中，同一份 UTF-8 文件在不同终端下",
     "实现过程中，同一份 UTF-8 文件在不同终端下"),
    ("某参考实现里有两个文件", "某实现里有两个文件"),
    ("**参考实现的权重（可调，但负号不可省）：**",
     "**建议权重（可调，但负号不可省）：**"),
    ("参考实现里恒为空", "实现里恒为空"),
    ("（参考实现用 `no_match_in`）", "（如用保留谓词 `no_match_in`）"),
    ("参考实现的第一版探针给未知关系留了个 `: true` 的兜底",
     "有一版实现的探针给未知关系留了个 `: true` 的兜底"),
    ("（参考实现用 `change_record_id`）", "（如用 `change_record_id`）"),
    ("框架 §5 中标注为\"Ossie 覆盖但参考实现未支持\"",
     "框架 §5 中标注为\"Ossie 覆盖但早期实现未支持\""),
]

# 允许落空的规则（键可能已被前面的规则改掉）
TEXT_FILES = [
    "spec/i4-action-minimal.md", "spec/i3-query-minimal.md",
    "spec/i6-discovery-minimal.md", "spec/module-discipline.md",
    "README.md", "CONTRIBUTING.md",
    "docs/framework.md", "docs/rationale.md",
    "docs/open-questions",
]


def main() -> int:
    apply = "--apply" in sys.argv
    targets: list[Path] = []
    for f in TEXT_FILES:
        p = ROOT / f
        if p.is_dir():
            targets += [q for q in p.rglob("*.md")]
        elif p.exists():
            targets.append(p)

    hit_count = 0
    for p in sorted(set(targets)):
        text = p.read_text(encoding="utf-8")
        orig = text
        hits = 0
        for old, new in RULES:
            c = text.count(old)
            if c:
                text = text.replace(old, new)
                hits += c
        if hits:
            rel = p.relative_to(ROOT)
            print(f"  {rel}: {hits} 处")
            hit_count += hits
            if apply:
                p.write_text(text, encoding="utf-8", newline="\n")

    print(f"\n{'已写入' if apply else '（干跑）'}：共 {hit_count} 处")
    if not apply:
        print("加 --apply 落盘")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
