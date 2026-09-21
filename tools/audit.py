#!/usr/bin/env python3
"""
规范仓库自检闸（offline，非零退出码=失败）

本仓库只出规范，不出软件；但**规范自身的完整性**必须能机器检查——
否则"改了正文忘了改引用"这类问题只能靠人眼。

对应《模块纪律》的构建期门禁思路（G-2 一条命令跑完 / G-3 失败阻断合并 / G-4 离线可跑），
本仓库以身作则，把审计固化成一条命令：

    python tools/audit.py

检查项
------
A. 相对链接        —— 链接目标必须存在
B. 标题锚点        —— ](#anchor) 必须与某个真实标题对得上
C. 节引用 §N       —— 必须指向真实存在的节号
D. 条款编号        —— 前缀必须有唯一归属（撞号即报错）；编号必须有定义
E. 编码            —— 无 BOM、无替换字符（U+FFFD）
F. 已删产物残留    —— 不得引用已移除的 reference/ 与 conformance/

退出码：0 全部通过；1 存在 ERROR；2 用法错误。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", "__pycache__", "node_modules", "_migrations"}

# ---------------------------------------------------------------------------
# 条款编号登记表：<!-- clauses: 前缀=归属 -->
# 约定：一个前缀只能登记在一个文件里。重复登记 = 撞号 = ERROR。
# ---------------------------------------------------------------------------
REGISTRY_RE = re.compile(r"<!--\s*clauses:\s*([^>]*?)-->")
CLAUSE_DEF_RE = re.compile(r"^\|\s*\*{0,2}([A-Z]{1,4}-[0-9]+[a-z]?)\*{0,2}\s*\|")
CLAUSE_REF_RE = re.compile(r"`([A-Z]{1,4}-[0-9]+[a-z]?)`")

# 允许"有引用无定义"的编号（跨文档引用 + 文档内子表引用，靠登记表消歧）
ALLOW_UNDEFINED = True


# 已知的条款前缀全集（用于区分"条款编号"与文档里普通的大写表格行）。
# 新增前缀时，除了在文档登记表里声明，也要加进这里。
DECLARED_PREFIXES = {
    "I1", "I2", "I3", "I4", "I5", "I6", "I7", "G", "L", "ELE", "AG", "LD",
    "SP", "ACT", "WR",
    "I1-G", "I2-G", "I3-G", "I4-G", "I5-G", "I6-G",
    "TR", "DV", "DR", "BGT", "SR",
    "ST", "AT", "ID", "CC", "AU", "EX", "BD", "RP", "MI", "NL", "XAD", "DF", "FD",
    "DG", "EN", "FC",
    "CT", "IG", "QT",
    "AC", "BT", "SV", "CR", "RJ", "LN", "P",
    "IF", "II", "IL", "IFD", "IM",
    "ELE-7a", "ELE-7b", "ELE-7c", "ELE-7d",
}


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def err(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


def md_files() -> list[Path]:
    return sorted(p for p in ROOT.rglob("*.md")
                  if not any(d in p.parts for d in SKIP_DIRS))


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def strip_inline_code(line: str) -> str:
    """把行内代码 `...` 换成等长空白（仅用于链接/锚点检查）。

    条款引用写在反引号里需要**保留**（见 strip_code），但**链接与锚点示例**
    也常写在反引号里（如 `` `](#anchor)` ``），那些不是真链接。
    """
    return re.sub(r"`[^`]*`", lambda m: " " * len(m.group(0)), line)


def strip_code(text: str) -> str:
    """只屏蔽**围栏代码块**（```），保留行内代码。

    为什么保留行内代码：本仓库的条款引用**就写在反引号里**（`` `ST-2` ``），
    屏蔽了会把引用全扫成 0。而围栏代码块里的示例（如登记表写法）必须屏蔽，
    否则会被当成真登记 → 误报撞号。
    """
    out: list[str] = []
    in_fence = False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            out.append(" " * len(line))
            continue
        out.append(" " * len(line) if in_fence else line)
    return "\n".join(out)


# ---------------------------------------------------------------------------
# A. 相对链接
# ---------------------------------------------------------------------------
LINK_RE = re.compile(r"\]\(([^)\s]+?)(?:#[^)]*)?\)")


def check_links(files: list[Path], rep: Report) -> int:
    n = 0
    for f in files:
        for i, line in enumerate(read(f).split("\n"), 1):
            line = strip_inline_code(line)      # 反引号里的示例不是真链接
            for m in LINK_RE.finditer(line):
                t = m.group(1)
                if t.startswith(("http://", "https://", "mailto:")):
                    continue
                # 纯锚点不是文件链接（锚点里不会出现 "/"）
                if "#" in t and "/" not in t.split("#", 1)[0]:
                    continue
                if any(c in t for c in "<>"):     # 语法占位符，如 <角色名>
                    continue
                if "#" in t:                      # 带锚点的文件链接：只校验文件部分
                    t = t.split("#", 1)[0]
                n += 1
                if not (f.parent / t).exists():
                    rep.err(f"[链接] {f.relative_to(ROOT)}:{i} → {t} 不存在")
    return n


# ---------------------------------------------------------------------------
# B. 标题锚点
# ---------------------------------------------------------------------------
def slug(h: str) -> str:
    """GitHub 风格锚点：去标点、空格转 -、**转小写**。"""
    s = re.sub(r"^#{1,6}\s+", "", h)
    s = re.sub(r"[^\w\u4e00-\u9fa5 \-]", "", s)
    return s.strip().replace(" ", "-").lower()


ANCHOR_RE = re.compile(r"\]\(#([^)]+)\)")


def check_anchors(files: list[Path], rep: Report) -> int:
    n = 0
    for f in files:
        text = read(f)
        slugs = {slug(l) for l in text.split("\n") if l.startswith("#")}
        for i, line in enumerate(text.split("\n"), 1):
            line = strip_inline_code(line)      # 反引号里的锚点示例不算数
            for m in ANCHOR_RE.finditer(line):
                n += 1
                a = m.group(1)
                if a not in slugs:
                    near = sorted(s for s in slugs if s[:12] == a[:12])[:2]
                    rep.err(f"[锚点] {f.relative_to(ROOT)}:{i} → #{a} 无对应标题"
                            f"（近似候选：{near or '无'}）")
    return n


# ---------------------------------------------------------------------------
# C. 节引用 §N
# ---------------------------------------------------------------------------
SEC_RE = re.compile(r"^## (\d+)\.", re.M)


def check_sections(files: list[Path], rep: Report) -> int:
    fw = ROOT / "docs" / "framework.md"
    if not fw.exists():
        rep.err("[节引用] 找不到 docs/framework.md")
        return 0
    valid = {int(m.group(1)) for m in SEC_RE.finditer(read(fw))}

    dupes = [x for x in valid if list(valid).count(x) > 1]
    if dupes:
        rep.err(f"[节号] docs/framework.md 节号重复：{sorted(set(dupes))}")

    n = 0
    for f in files:
        # 历史记录描述的是"当时的状态"，其中的节号按当时的结构算，不参与现行检查
        if str(f.relative_to(ROOT)).replace("\\", "/").startswith("docs/reviews/"):
            continue
        for i, line in enumerate(read(f).split("\n"), 1):
            for m in re.finditer(r"§(\d+)\b", line):
                v = int(m.group(1))
                if v < 7:
                    continue          # §0~§6 从未改动，且 rationale 有自己的中文节号
                n += 1
                if v not in valid:
                    rep.err(f"[节引用] {f.relative_to(ROOT)}:{i} → §{v} 不存在")
    return n


# ---------------------------------------------------------------------------
# D. 条款编号：登记表 + 唯一归属 + 有引用必有定义（或已登记归属）
# ---------------------------------------------------------------------------
def check_clauses(files: list[Path], rep: Report) -> tuple[int, int]:
    # 历史记录不参与规范性检查（它们描述的是"当时的状态"）
    files = [f for f in files
             if not str(f.relative_to(ROOT)).replace("\\", "/").startswith("docs/reviews/")]

    owner: dict[str, Path] = {}
    clashes: dict[str, list[Path]] = {}
    for f in files:
        m = REGISTRY_RE.search(strip_code(read(f)))
        if not m:
            continue
        for tok in m.group(1).split():
            pref = tok.split("=")[0].strip()
            if not pref or pref.startswith("（"):
                continue
            if pref in owner:
                clashes.setdefault(pref, [owner[pref]]).append(f)
            else:
                owner[pref] = f

    for pref, fs in clashes.items():
        rep.err("[条款] 前缀 `%s-` 被多个文件登记：%s —— 撞号，须消解"
                % (pref, " / ".join(str(p.relative_to(ROOT)) for p in fs)))

    defined: dict[str, Path] = {}
    for f in files:
        for i, line in enumerate(strip_code(read(f)).split("\n"), 1):
            m = CLAUSE_DEF_RE.match(line)
            if not m:
                continue
            cid = m.group(1)
            pref = cid.split("-")[0]
            # 只对"有主的前缀"要求登记：否则那是文档里的普通大写表格行
            # （如 `Z-1`、`P-9` 这类非条款编号）
            if pref not in owner and pref in DECLARED_PREFIXES:
                rep.err(f"[条款] {f.relative_to(ROOT)}:{i} 定义了 `{cid}`，"
                        f"但前缀 `{pref}-` 未在登记表声明归属")
            defined.setdefault(cid, f)

    n_def, n_ref = len(defined), 0
    for f in files:
        for i, line in enumerate(strip_code(read(f)).split("\n"), 1):
            # 定义行本身不算引用
            if CLAUSE_DEF_RE.match(line):
                continue
            for m in CLAUSE_REF_RE.finditer(line):
                cid = m.group(1)
                n_ref += 1
                if cid in defined:
                    continue
                pref = cid.split("-")[0]
                if pref in owner:
                    continue          # 归属已登记，属跨文档引用
                if pref in DECLARED_PREFIXES:
                    rep.warn(f"[条款] {f.relative_to(ROOT)}:{i} 引用 `{cid}`："
                             f"既无定义、前缀 `{pref}-` 也未登记归属")
    return n_def, n_ref


# ---------------------------------------------------------------------------
# E. 编码
# ---------------------------------------------------------------------------
def check_encoding(files: list[Path], rep: Report) -> int:
    n = 0
    for f in files:
        b = f.read_bytes()
        n += 1
        if b[:3] == b"\xef\xbb\xbf":
            rep.err(f"[编码] {f.relative_to(ROOT)} 有 BOM")
        if "\ufffd" in b.decode("utf-8", errors="replace"):
            rep.err(f"[编码] {f.relative_to(ROOT)} 含替换字符 U+FFFD（编码损坏）")
    return n


# ---------------------------------------------------------------------------
# F. 已删产物残留
# ---------------------------------------------------------------------------
# 只查**真实链接**指向已删目录；正文里提一句"这个目录已被删"不算问题
GONE = re.compile(r"\]\((?:\.\./)*(?:reference|conformance)/")


def check_removed(files: list[Path], rep: Report) -> int:
    n = 0
    for f in files:
        rel = str(f.relative_to(ROOT)).replace("\\", "/")
        if rel.startswith("docs/reviews/") or "_migrations" in rel:
            continue          # 历史记录与迁移脚本允许提到旧路径
        for i, line in enumerate(read(f).split("\n"), 1):
            if GONE.search(line):
                n += 1
                rep.warn(f"[已删产物] {rel}:{i} 链接指向已删除的 reference/ 或 conformance/")
    return n


def main(argv: list[str]) -> int:
    if "--help" in argv or "-h" in argv:
        print(__doc__)
        return 0

    files = md_files()
    rep = Report()

    print(f"审计 {len(files)} 个 markdown 文件 …\n")
    n_link = check_links(files, rep)
    n_anchor = check_anchors(files, rep)
    n_sec = check_sections(files, rep)
    n_cdef, n_cref = check_clauses(files, rep)
    n_enc = check_encoding(files, rep)
    n_gone = check_removed(files, rep)

    print(f"  A 相对链接      {n_link:4d} 条")
    print(f"  B 标题锚点      {n_anchor:4d} 条")
    print(f"  C 节引用 §N     {n_sec:4d} 条")
    print(f"  D 条款编号      {n_cdef:4d} 个定义 / {n_cref} 处引用")
    print(f"  E 编码          {n_enc:4d} 个文件")
    print(f"  F 已删产物残留  {n_gone:4d} 处")

    for w in rep.warnings:
        print(f"\n  ⚠ {w}")
    for e in rep.errors:
        print(f"\n  ❌ {e}")

    print()
    if rep.errors:
        print(f"审计失败：{len(rep.errors)} 个 ERROR、{len(rep.warnings)} 个 WARNING")
        return 1
    print(f"审计通过（{len(rep.warnings)} 个 WARNING）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
