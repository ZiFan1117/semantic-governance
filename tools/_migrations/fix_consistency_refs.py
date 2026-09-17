"""一次性：修跨文档失效引用与过时描述（按一致性审阅报告的 A/B/C/D/H/I/K 项）。

A. §18.1.1 悬空（3 处）
B. §18.2 指向错（候选解法在 §18.1）
C. I1-2 被当成"定义不可变"（实为"定义自检"；不可变是 I1-G1/G-2）
D. §18 对 i4 规范的描述过时（说 v0.1 / 单实例，实为 v0.2.4 且已加多实例）
H. spec 对框架的引用多处失效
I. 附录 A 速查重复两行
K. rationale.md 速查仍是已删的六层表述
"""
import re
from pathlib import Path

ROOT = Path(r'D:\Code\04-research-ontology\semantic-governance')
total = 0


def fix(path, pairs, label):
    global total
    p = ROOT / path
    t = p.read_text(encoding='utf-8')
    n = 0
    for old, new in pairs:
        if old in t:
            c = t.count(old)
            t = t.replace(old, new)
            n += c
        else:
            print(f'    ⚠ 未命中: {old[:60]}')
    if n:
        p.write_text(t, encoding='utf-8', newline='\n')
    print(f'  {label}: {n} 处')
    total += n


# ---- A/B/C/D：framework 自身 ----
fix('docs/framework.md', [
    # A. §18.1.1 → §18.1
    ('| I4-7 | 动作的读 **MUST** 使用满足 §18.1.1 R1~R4 的一致性读路径 |',
     '| I4-7 | 动作的读 **MUST** 使用满足 §18.1 `R1`~`R4` 的一致性读路径 |'),
    ('| 4 | 「L5 直调 L2」掩盖难点 | ✅ 已在 §18.1.1 修正为专用一致性读路径（`R1`~`R4`） |',
     '| 4 | 「动作直调事实层」掩盖难点 | ✅ 已在 §18.1 修正为专用一致性读路径（`R1`~`R4`） |'),
    # B. 候选解法指向
    ('**候选解法（尚无定论，见 §18）：**', '**候选解法（尚无定论，见 §18.1）：**'),
    # C. I1-2 的误用：定义不可变是 I1-G1 / G-2
    ('定义一经发布不可原地修改（`I1-2`、`G-2`）', '定义一经发布不可原地修改（`I1-G1`、`G-2`）'),
    ('❌ 只读——定义不可原地改（`I1-2`）', '❌ 只读——定义不可原地改（`I1-G1`）'),
    # D. §18 对 i4 规范的过时描述
    ('> 📄 **实现规范见 [`spec/i4-action-minimal.md`](../spec/i4-action-minimal.md)（v0.1）。**',
     '> 📄 **实现规范见 [`spec/i4-action-minimal.md`](../spec/i4-action-minimal.md)（v0.2.4）。**'),
    ('> 该规范刻意收窄范围：**单实例 · 同步 · 无副作用 · 有审计**。\n> 多实例事务、异步、副作用、补偿留给下一版。',
     '> 该规范**逐步收窄范围**：v0.1 只做**单实例 · 同步 · 无副作用 · 有审计**；\n> v0.2 已加入**多实例原子效果**；异步执行、声明式副作用、长事务补偿仍留给后续版本。'),
], 'framework')

# ---- H. spec 对框架的失效引用 ----
fix('spec/i3-query-minimal.md', [
    ('框架 §25.8 `A-2`', '框架 §25.9 `AG-2`'),
    ('框架 §19', '框架 §19'),
], 'i3')

fix('spec/i4-action-minimal.md', [
    ('框架 §25.8 `A-1`', '框架 §25.9 `AG-1`'),
    ('框架 §25.8 `A-2`', '框架 §25.9 `AG-2`'),
    ('框架 §25.8 `AT-1`', '框架 §25.9 `AG-1`'),
    ('框架 §25.8 `AT-2`', '框架 §25.9 `AG-2`'),
    ('框架 §28.1 的', '框架 §24.1 的'),
], 'i4')

fix('spec/module-discipline.md', [
    ('框架 §17（模块视图）', '框架 §22（模块视图）'),
    ('| §19 验收标准 | **构建期门禁**（原只有运行期） |', '| §24 验收标准 | **构建期门禁**（原只有运行期） |'),
    ('| `AC-2` 拒绝可自纠 |', '| 框架 `AG-2` 拒绝可自纠 |'),
], 'module-discipline')

print(f'\n合计 {total} 处')
