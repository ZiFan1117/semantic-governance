"""
一次性：把「分层视图」从"第三部分"降为"附录 A"。

为什么
------
文档里有三根轴在抢主轴：
    五要素（§5~§10，431 行）  ← 声明的主轴
    契约视图（§14~§21，347 行）← 标题写着 "★核心"
    分层视图（§12~§13，154 行）← 自己都说"实现参考，非主轴"，却与主轴平级

处置
----
1. 分层视图（现 §12~§13）**整块搬到文末**，成为「附录 A · 分层视图（实现参考）」。
   **节号保持 §12/§13 不变** —— 这样 §13.1/§13.2 的四处引用不需要改。
2. 第四部分去掉 "★核心"；「接口视图」→「契约视图」（I 这个字母容易被误读成"层级"）。
3. 目录同步。

用法：
    python tools/_migrations/demote_layer_view.py           # 干跑
    python tools/_migrations/demote_layer_view.py --apply
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
FW = ROOT / "docs" / "framework.md"

NEW_TOC = """## 目录

**第零部分 · 理念与定位**
- [0. 语义治理是什么](#0-语义治理是什么)
- [0.5 【关键】形态选择：中央式权威及其代价](#05-关键形态选择中央式权威及其代价)

**第一部分 · 治理维度**（一等公民）
- [1. 治理的六件事](#1-治理的六件事)
- [2. 三类角色与权责](#2-三类角色与权责)
- [3. 三种剖面（Profile）](#3-三种剖面profile)

**第二部分 · 五要素** ★主轴
- [4. 术语表](#4-术语表)
- [5. 五要素总览与理论根基](#5-五要素总览与理论根基)
- [6. 对象](#6-对象)
- [7. 关系](#7-关系)
- [8. 规则](#8-规则)
- [9. 策略](#9-策略)
- [10. 动作](#10-动作)

**第三部分 · 契约视图**（谁能读写；**不是主轴**）
- [14. 六个契约](#14-六个契约)
- [15. I1 语义契约](#15-i1-语义契约)
- [16. I2 事实契约](#16-i2-事实契约)
- [17. I3 查询契约](#17-i3-查询契约)
- [18. I4 动作契约](#18-i4-动作契约)
- [19. I5 接入契约](#19-i5-接入契约)
- [20. I6 发现契约](#20-i6-发现契约)
- [21. 契约 × 现有标准对照](#21-契约--现有标准对照)

**第四部分 · 模块视图**
- [22. 模块清单与可替换性](#22-模块清单与可替换性)

**第五部分 · 合规等级**
- [23. 五级阶梯 × 三种剖面](#23-五级阶梯--三种剖面)
- [24. 验收标准](#24-验收标准)

**第六部分 · 规范条款（Normative）**
- [25. MUST / MUST NOT / SHOULD 清单](#25-must--must-not--should-清单)

**第七部分 · 实施指南（Informative）**
- [26. 四阶段路线](#26-四阶段路线)
- [27. Agent-first 设计原则](#27-agent-first-设计原则)

**第八部分 · 开放问题**
- [28. 尚未解决的问题](#28-尚未解决的问题)

**附录（实现参考）**
- [附录 A · 分层视图](#附录-a--分层视图实现参考)
- [附录 B · 一页速查](#附录-一页速查)
"""


def main() -> int:
    apply = "--apply" in sys.argv
    lines = FW.read_text(encoding="utf-8").split("\n")

    def find(pat: str, start: int = 0) -> int:
        for i in range(start, len(lines)):
            if lines[i].startswith(pat):
                return i
        raise SystemExit(f"定位失败：{pat!r}")

    L_TOC = find("## 目录")
    # ⚠️ "第零部分 · 理念与定位" 在目录里也出现一次！
    #    正文起点用**一级标题行**定位（`# 第零部分`），不依赖目录结尾分隔符
    #    —— 目录与正文之间有没有 `---` 是不确定的。
    L_P2 = find("# 第零部分 · 理念与定位", L_TOC)
    L_LAYER = find("# 第三部分 · 分层视图")
    L_IFACE = find("# 第四部分 ·")
    L_APPX = find("## 附录：一页速查")

    print(f"目录 {L_TOC+1}（正文起点 {L_P2+1}）· 第三部分(分层) {L_LAYER+1} · "
          f"第四部分(契约) {L_IFACE+1} · 速查 {L_APPX+1}")

    A = lines[: L_TOC]                      # 文件头（到目录前一行）
    B = NEW_TOC.rstrip("\n").split("\n")    # 新目录
    C = lines[L_P2:L_LAYER]                 # 第零~二部分 + 契约视图（到分层视图前）
    D = lines[L_LAYER:L_IFACE]              # 分层视图整块（将被搬走）
    E = lines[L_IFACE:L_APPX]               # 契约视图 ~ 开放问题
    F = lines[L_APPX:]                      # 速查

    # ---- 分层视图块：改标题为附录 A ----
    D2 = list(D)
    for i, s in enumerate(D2):
        if s.startswith("# 第三部分 · 分层视图"):
            D2[i] = "## 附录 A · 分层视图（实现参考）"
            # 紧跟其后补一段定位说明
            D2.insert(i + 1, "")
            D2.insert(i + 2, "> **本附录是实现参考，不是框架主轴。** 主轴是第二部分·五要素。")
            D2.insert(i + 3, "> 它给出一种可行的落地方案（六层 + 三条流），**别的实现可以不同**；")
            D2.insert(i + 4, "> 但五要素与第三部分的契约是**强制的**。")
            break
    # 去掉块首多余的分隔线与空行（原来是 `---\n# 第三部分…`）
    while D2 and D2[0].strip() in ("", "---"):
        D2.pop(0)
    D2 = ["", "---", ""] + D2

    # ---- 契约视图：去 ★核心；接口→契约；节标题同步 ----
    def retitle(s: str) -> str:
        if s.startswith("# 第四部分 · 契约视图"):
            return "# 第三部分 · 契约视图"
        if s.startswith("# 第五部分 · 模块视图"):
            return "# 第四部分 · 模块视图"
        if s.startswith("# 第六部分 · 合规等级"):
            return "# 第五部分 · 合规等级"
        if s.startswith("# 第七部分 · 规范条款"):
            return "# 第六部分 · 规范条款（Normative）"
        if s.startswith("# 第八部分 · 实施指南"):
            return "# 第七部分 · 实施指南（Informative）"
        if s.startswith("# 第九部分 · 开放问题"):
            return "# 第八部分 · 开放问题"
        if s.startswith("## 14. 五个接口 + 一个能力"):
            return "## 14. 六个契约"
        if s.startswith("## 15. I1 语义接口"):
            return "## 15. I1 语义契约"
        if s.startswith("## 16. I2 事实接口"):
            return "## 16. I2 事实契约"
        if s.startswith("## 17. I3 查询接口"):
            return "## 17. I3 查询契约"
        if s.startswith("## 18. I4 动作接口"):
            return "## 18. I4 动作契约"
        if s.startswith("## 19. I5 接入接口"):
            return "## 19. I5 接入契约"
        if s.startswith("## 20. I6 发现能力"):
            return "## 20. I6 发现契约"
        if s.startswith("## 21. 接口 × 现有标准对照"):
            return "## 21. 契约 × 现有标准对照"
        if s.startswith("## 附录：一页速查"):
            return "## 附录 B · 一页速查"
        return s

    C2 = [retitle(s) for s in C]
    E2 = [retitle(s) for s in E]
    F2 = [retitle(s) for s in F]

    out = A + B + C2 + E2 + D2 + F2

    # ---- 校验 ----
    errs = []
    nums = [int(m.group(1)) for s in out if (m := re.match(r"^## (\d+)\.", s))]
    expected = sorted(set(list(range(0, 11)) + list(range(12, 29))))
    if sorted(nums) != expected:
        errs.append(f"节号不符预期\n  实际 {sorted(nums)}\n  预期 {expected}")
    order = [s for s in out if re.match(r"^# 第|^## 附录", s)]
    print("骨架顺序：")
    for s in order:
        print("   ", s)
    if not any(s.startswith("## 附录 A") for s in out):
        errs.append("附录 A 未生成")
    if any("★核心" in s for s in out):
        for i, s in enumerate(out):
            if "★核心" in s:
                errs.append(f"仍有 ★核心 标注 → out[{i}]: {s!r}")
                break

    if errs:
        print("\n❌ 校验失败：")
        for e in errs:
            print("  -", e)
        return 1
    print("\n✅ 校验通过")
    if not apply:
        print("（干跑，加 --apply 落盘）")
        return 0
    FW.write_text("\n".join(out), encoding="utf-8", newline="\n")
    print(f"✅ 已写入（{len(out)} 行）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
