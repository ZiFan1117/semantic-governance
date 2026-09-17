"""一次性：修 i6 规范的两处问题。

1) 条款号重号：FC-7/8/9 在 §3.2（语境与排除条件）与 §4（与 I4 的关系）各定义一次。
   约定：**先定义的保留原号**，后定义的一组改为 FC-11~FC-13。
2) 缺 ListDomains 操作：框架 §20（I6 契约）的保证 I6-G1 要求
   "域、对象、动作 MUST 可被完整列出"，而本规范 §2.1 没有列举"域"的操作。
"""
import re
from pathlib import Path

P = Path(r'D:\Code\04-research-ontology\semantic-governance\spec\i6-discovery-minimal.md')
t = P.read_text(encoding='utf-8')

# ---- 1) §4 那一组 FC-7/8/9 → FC-11/12/13 ----
head = t.index('## 4.')
body, tail = t[:head], t[head:]

for old, new in (('FC-7', 'FC-11'), ('FC-8', 'FC-12'), ('FC-9', 'FC-13')):
    tail = re.sub(rf'(?<![A-Za-z0-9-]){old}(?![0-9])', new, tail)

# §5 汇总表里那两行（与 I4 相关）也要跟着改
tail = tail.replace('| **与 I4** | FC-11 调用方 MUST NOT 依赖 suggestions 存在<br>FC-12 内联时 MUST 标注来源 · FC-13 SHOULD 主动查替代 |',
                    '| **与 I4** | FC-11 调用方 MUST NOT 依赖 suggestions 存在<br>FC-12 内联时 MUST 标注来源 · FC-13 SHOULD 主动查替代 |')

t = body + tail

# ---- 2) 补 ListDomains ----
old_ops = '''| 操作 | 输入 | 输出 |
|---|---|---|
| `ListConcepts` | 可选过滤条件 | 概念列表（简） |'''
new_ops = '''| 操作 | 输入 | 输出 |
|---|---|---|
| `ListDomains` | — | **域列表**（`I6-G1` 要求"域可被完整列出"） |
| `ListConcepts` | 可选过滤条件 | 概念列表（简） |'''
assert old_ops in t, '操作表锚点未命中'
t = t.replace(old_ops, new_ops)

P.write_text(t, encoding='utf-8', newline='\n')
print('i6：FC-7/8/9 → FC-11/12/13（§4 那组）；§2.1 补 ListDomains')
print('残留重号检查：', len(re.findall(r'(?<![A-Za-z0-9-])FC-7(?![0-9])', t)), '（应为 1）')
