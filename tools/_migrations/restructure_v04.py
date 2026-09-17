"""
一次性重构 v0.4：把 framework.md 改成「三轴清晰版」。

只从旧文件**逐字保留**：
    · §1~§3     治理维度            （与本次改动无关）
    · §4        术语表
    · §6~§10    五个要素
    · §14 起    契约正文及之后      （编号不变，保护全仓引用）

重写 / 删除：
    · §0、§5   重写（架构图 + 四个正交维度）
    · §12、§13 旧「分层视图」两节正文 —— 彻底删除
    · 附录 A   分层视图 —— 彻底删除

用法：
    python tools/_migrations/restructure_v04.py           # 干跑
    python tools/_migrations/restructure_v04.py --apply
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from v04_content import CONTENT  # noqa: E402

ROOT = HERE.parent.parent
FW = ROOT / "docs" / "framework.md"


def find(lines: list[str], pat: str, start: int = 0) -> int:
    for i in range(start, len(lines)):
        if lines[i].startswith(pat):
            return i
    raise SystemExit(f"定位失败：{pat!r}")


def main() -> int:
    apply = "--apply" in sys.argv
    apply = "--apply" in sys.argv
    old = FW.read_text(encoding="utf-8").split("\n")

    p1 = find(old, "# 第一部分 · 治理维度")
    p2 = find(old, "# 第二部分")
    s4 = find(old, "## 4. 术语表")
    s5 = find(old, "## 5. ")
    s6 = find(old, "## 6. 对象")
    p3 = find(old, "# 第三部分")
    appx_a = find(old, "## 附录 A · 分层视图")

    # §12/§13 是旧分层正文；§14 起才是契约
    s14 = find(old, "## 14. ")

    P1 = old[p1:p2]
    S4 = old[s4:s5]
    ELEMS = old[s6:p3]
    TAIL = old[s14:appx_a]

    out: list[str] = []

    def add(text: str) -> None:
        out.extend(text.strip("\n").split("\n"))
        out.append("")

    add(CONTENT["NEW_HEAD"])
    add(CONTENT["NEW_S0"])
    out.extend(P1)
    add(CONTENT["NEW_P2_HEAD"])
    out.extend(S4)
    add(CONTENT["NEW_S5"])
    out.extend(ELEMS)
    add(CONTENT["NEW_S11"])
    out.extend(TAIL)
    add(CONTENT["QUICK_NEW"])

    # ---- 校验 ----
    errs: list[str] = []
    text = "\n".join(out)
    # 注意：「六层架构」会出现在变更记录与附录 B（说明"删掉了它"），所以只禁正文标题
    for banned in ("## 12. 六层架构", "## 13. 三条流", "## 附录 A · 分层视图"):
        if banned in text:
            errs.append(f"残留已删章节：{banned}")
    for need in ("## 0. 语义治理是什么", "### 0.4 【架构】东西都放在哪",
                 "## 5. 四个正交维度", "## 11. 纪律条款",
                 "## 4. 术语表", "## 6. 对象", "## 10. 动作",
                 "## 14. 六个契约", "## 15. I1 语义契约",
                 "## 25. MUST", "## 28. 尚未解决的问题",
                 "## 附录 A · 一页速查", "## 附录 B ·"):
        if need not in text:
            errs.append(f"缺内容：{need}")

    nums = [int(m.group(1)) for l in out if (m := re.match(r"^## (\d+)\.", l))]
    print(f"保留：治理 {len(P1)} · 术语表 {len(S4)} · 五要素 {len(ELEMS)} · 契约起 {len(TAIL)} 行")
    print(f"新文件 {len(out)} 行；一级节号：{sorted(set(nums))}")
    # §12/§13 是**故意留空**的：契约从 §14 起，编号不变以保护全仓引用
    exp = sorted(set(list(range(0, 12)) + list(range(14, 29))))
    if sorted(set(nums)) != exp:
        errs.append(f"节号不符预期\n  实际 {sorted(set(nums))}\n  预期 {exp}")
    if errs:
        print("\n❌ 校验失败：")
        for e in errs:
            print("  -", e)
        return 1
    print("✅ 校验通过")
    if not apply:
        print("（干跑；加 --apply 落盘）")
        return 0
    FW.write_text(text + "\n", encoding="utf-8", newline="\n")
    print("✅ 已写入")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
