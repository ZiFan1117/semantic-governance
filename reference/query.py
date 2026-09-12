"""
I3 查询接口 —— 最小实现。

实现 spec/i3-query-minimal.md。

本模块首次实现 Ossie 的 `derived_by`：
  · 路径型表达式   <概念>.<关系1>[.<关系2>...](<角色名>)
  · 前向链到不动点（框架 §14）
  · 每条派生事实带 `via` 溯源（规范 D-2 / 框架 A-4）

不支持的形式（布尔组合/比较/聚合）**会明确报错**，不静默忽略（规范 D-3）。
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from ossie_model import OssieModel
from store import Store

# 规范 D-4：迭代上限。超限 MUST 报错，MUST NOT 静默停止。
MAX_ITERATIONS = 64

# 默认预算
DEFAULT_MAX_ITEMS = 200


class QueryError(Exception):
    """查询或派生求值失败。"""


class UnsupportedDerivation(QueryError):
    """derived_by 使用了本实现不支持的形式（规范 D-3）。"""


class DerivationLimitExceeded(QueryError):
    """派生求值超过迭代上限（规范 D-4）。"""


# --------------------------------------------------------------------------
# 派生规则
# --------------------------------------------------------------------------

_PATH_RE = re.compile(r"^\s*([A-Za-z_]\w*)\s*\.\s*"
                      r"((?:[A-Za-z_]\w*\s*\.\s*)*[A-Za-z_]\w*)\s*"
                      r"\(\s*([A-Za-z_]\w*)\s*\)\s*$")

# 不支持的语法特征 —— 命中即报错，不静默当空结果
_UNSUPPORTED_MARKERS = (" AND ", " OR ", " NOT ", "EXISTS", "COUNT",
                        "SUM(", ">", "<", "==", "!=")


@dataclass(frozen=True)
class DerivedRule:
    concept: str          # 声明它的概念
    relation: str         # 被派生的关系名
    case: int             # derived_by 的第几条（从 0 计）
    expression: str
    path: list[str]       # 关系路径
    role: str             # 目标角色名

    @property
    def qualified(self) -> str:
        return f"{self.concept}.{self.relation}"


def parse_derived_by(model: OssieModel) -> list[DerivedRule]:
    """
    从本体里抽出所有 derived_by 规则。

    D-3：遇到不支持的形式 **MUST 报错**。
    """
    rules: list[DerivedRule] = []
    for cname in sorted(model.concepts):
        concept = model.concepts[cname]
        for rel in concept.relationships:
            for case_idx, expr in enumerate(rel.derived_by):
                for marker in _UNSUPPORTED_MARKERS:
                    if marker in expr:
                        raise UnsupportedDerivation(
                            f"`{rel.qualified}` 的第 {case_idx} 条 derived_by "
                            f"包含不支持的形式（命中 {marker!r}）：{expr}")
                m = _PATH_RE.match(expr)
                if not m:
                    raise UnsupportedDerivation(
                        f"`{rel.qualified}` 的第 {case_idx} 条 derived_by "
                        f"不是路径型表达式：{expr!r}")
                head, path_text, role = m.groups()
                path = [p.strip() for p in path_text.split(".") if p.strip()]
                if head != cname:
                    raise UnsupportedDerivation(
                        f"`{rel.qualified}` 的表达式主语 `{head}` "
                        f"与声明概念 `{cname}` 不一致：{expr}")
                if not path:
                    raise UnsupportedDerivation(
                        f"`{rel.qualified}` 的表达式没有关系路径：{expr}")
                # 注意：**不要求** path[-1] 等于被派生的关系名。
                # Ossie 的 base case 就是这样：
                #     ancestor_of 的 base case 是 "Person.parent_of(descendant)"
                # 路径只负责"走到角色扮演者"，末位关系与被派生关系无关。
                role_names = {r.name or r.concept for r in rel.roles}
                if role not in role_names:
                    raise UnsupportedDerivation(
                        f"`{rel.qualified}` 的表达式角色 `{role}` "
                        f"不在声明的角色 {sorted(role_names)} 中：{expr}")
                rules.append(DerivedRule(
                    concept=cname, relation=rel.name, case=case_idx,
                    expression=expr, path=path, role=role))
    return rules


# --------------------------------------------------------------------------
# 事实与溯源
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class FactRef:
    subject: str
    relation: str
    object: str

    def as_dict(self) -> dict[str, str]:
        return {"subject": self.subject, "relation": self.relation,
                "object": self.object}


@dataclass
class DerivedFact:
    fact: FactRef
    rule: str
    case: int
    expression: str
    premises: list[FactRef] = field(default_factory=list)

    def as_item(self) -> dict[str, Any]:
        return {
            "subject": self.fact.subject,
            "relation": self.fact.relation,
            "object": self.fact.object,
            "derived": True,
            "via": {
                "rule": self.rule,
                "case": self.case,
                "expression": self.expression,
                "premises": [p.as_dict() for p in self.premises],
            },
        }


# 权限过滤：签名 (actor, subject, relation, object) -> 可见?
FactFilter = Callable[[str, str, str, str], bool]


def visible_all(actor: str, subject: str, relation: str, obj: str) -> bool:
    """⚠️ 默认放行一切。生产 MUST 注入真实过滤器（I3-G3）。"""
    return True


# --------------------------------------------------------------------------
# 查询引擎
# --------------------------------------------------------------------------

class QueryEngine:

    def __init__(self, model: OssieModel, store: Store,
                 visible: FactFilter = visible_all):
        self.model = model
        self.store = store
        self.visible = visible
        self.rules = parse_derived_by(model)

    # ------------------------------------------------------------ 事实索引

    def _base_facts(self, snapshot: int) -> list[FactRef]:
        rows = self.store.conn.execute(
            """
            SELECT subject, relation, object FROM facts
             WHERE valid_from <= ?
               AND (valid_to IS NULL OR valid_to > ?)
               AND relation != ?
             ORDER BY id
            """, (snapshot, snapshot,
                  Store.RESERVED_CONCEPT_RELATION)).fetchall()
        return [FactRef(r["subject"], r["relation"], r["object"])
                for r in rows]

    def _subjects_of(self, concept: str, snapshot: int) -> list[str]:
        """概念及其所有子类型的实例（Ossie 的子类关系是传递的）。"""
        subs = [c for c in self.model.concepts
                if self.model.is_subtype(c, concept)]
        out: list[str] = []
        for c in sorted(subs):
            out.extend(self.store.instances_of_concept(c, snapshot))
        return sorted(set(out))

    # ------------------------------------------------------------ 派生求值

    def derive(self, snapshot: int | None = None) -> dict[FactRef, DerivedFact]:
        """
        求值到不动点（规范 D-1）。

        每轮用当前（基础 + 已派生）事实重建索引，应用全部规则，
        直到一轮没有新事实。超过 MAX_ITERATIONS 报错（D-4）。
        """
        snap = self.store.current_snapshot() if snapshot is None else snapshot
        base = self._base_facts(snap)
        index: dict[str, list[FactRef]] = defaultdict(list)
        for f in base:
            index[f.relation].append(f)

        derived: dict[FactRef, DerivedFact] = {}
        subjects_cache = {r.concept: self._subjects_of(r.concept, snap)
                          for r in self.rules}

        for iteration in range(MAX_ITERATIONS):
            new_count = 0
            for rule in self.rules:
                for subj in subjects_cache.get(rule.concept, []):
                    for target, premises in self._walk(subj, rule.path, index):
                        f = FactRef(subj, rule.relation, target)
                        if f in derived:
                            continue
                        if any(x.subject == subj and x.relation == rule.relation
                               and x.object == target for x in index[rule.relation]):
                            continue          # 基础事实已存在，不算派生
                        derived[f] = DerivedFact(
                            fact=f, rule=rule.qualified, case=rule.case,
                            expression=rule.expression, premises=premises)
                        index[rule.relation].append(f)
                        new_count += 1
            if new_count == 0:
                return derived
        raise DerivationLimitExceeded(
            f"派生求值超过 {MAX_ITERATIONS} 轮仍未收敛。"
            f"这通常意味着递归规则不终止（框架 §14）")

    def _walk(self, start: str, path: list[str],
              index: dict[str, list[FactRef]]
              ) -> Iterable[tuple[str, list[FactRef]]]:
        """沿关系路径行走，返回 (终点, 所依据的事实)。"""
        frontier: list[tuple[str, list[FactRef]]] = [(start, [])]
        for rel in path:
            nxt: list[tuple[str, list[FactRef]]] = []
            for node, premises in frontier:
                for f in index.get(rel, ()):
                    if f.subject == node:
                        nxt.append((f.object, premises + [f]))
            frontier = nxt
            if not frontier:
                return
        yield from frontier

    # ------------------------------------------------------------ 操作

    def query(self, *, subject: str | None = None, relation: str | None = None,
              object: str | None = None, actor: str = "user:anonymous",
              max_items: int = DEFAULT_MAX_ITEMS) -> dict[str, Any]:
        """Q：模式查询。只返回**存储的**事实（不派生）。"""
        snap = self.store.current_snapshot()
        items = []
        for f in self._base_facts(snap):
            if subject and f.subject != subject:
                continue
            if relation and f.relation != relation:
                continue
            if object and f.object != object:
                continue
            if not self.visible(actor, f.subject, f.relation, f.object):
                continue
            items.append({"subject": f.subject, "relation": f.relation,
                          "object": f.object, "derived": False})
        return self._envelope(items, snap, max_items, actor)

    def traverse(self, start: str, path: list[str], *, max_depth: int = 3,
                 actor: str = "user:anonymous",
                 max_items: int = DEFAULT_MAX_ITEMS) -> dict[str, Any]:
        """T：多跳遍历。T-2 检测环；T-3 返回到达路径。"""
        snap = self.store.current_snapshot()
        index: dict[str, list[FactRef]] = defaultdict(list)
        for f in self._base_facts(snap):
            index[f.relation].append(f)

        seen = {start}
        frontier = [(start, [])]
        results: list[dict[str, Any]] = []
        for _ in range(max(0, max_depth)):
            nxt = []
            for node, trail in frontier:
                relations = path or sorted(index)
                for rel in relations:
                    for f in index.get(rel, ()):
                        if f.subject != node:
                            continue
                        if f.object in seen:          # T-2：环终止
                            continue
                        seen.add(f.object)
                        new_trail = trail + [f.as_dict()]
                        results.append({
                            "instance": f.object,
                            "hops": len(new_trail),
                            "path": new_trail,
                        })
                        nxt.append((f.object, new_trail))
            frontier = nxt
            if not frontier:
                break
        return self._envelope(results, snap, max_items, actor)

    def infer(self, *, subject: str | None = None,
              relation: str | None = None, object: str | None = None,
              actor: str = "user:anonymous",
              max_items: int = DEFAULT_MAX_ITEMS) -> dict[str, Any]:
        """D：含派生事实的查询。每条派生事实带 via（规范 §3.2）。"""
        snap = self.store.current_snapshot()
        derived = self.derive(snap)
        items = []
        for f, d in derived.items():
            if subject and f.subject != subject:
                continue
            if relation and f.relation != relation:
                continue
            if object and f.object != object:
                continue
            if not self.visible(actor, f.subject, f.relation, f.object):
                continue
            items.append(d.as_item())
        # Q-3：顺序确定
        items.sort(key=lambda i: (i["subject"], i["relation"], i["object"]))
        return self._envelope(items, snap, max_items, actor)

    def search(self, text: str, *, actor: str = "user:anonymous",
               max_items: int = DEFAULT_MAX_ITEMS) -> dict[str, Any]:
        """S：字面匹配。S-2 标明命中字段。"""
        snap = self.store.current_snapshot()
        needle = (text or "").strip().lower()
        items = []
        if needle:
            for f in self._base_facts(snap):
                field = None
                if needle in f.object.lower():
                    field = "object"
                elif needle in f.subject.lower():
                    field = "subject"
                elif needle in f.relation.lower():
                    field = "relation"
                if field is None:
                    continue
                if not self.visible(actor, f.subject, f.relation, f.object):
                    continue
                items.append({"subject": f.subject, "relation": f.relation,
                              "object": f.object, "derived": False,
                              "matched_field": field})
        return self._envelope(items, snap, max_items, actor)

    # ------------------------------------------------------------ 信封

    @staticmethod
    def _envelope(items: list[dict], snapshot: int, max_items: int,
                  actor: str) -> dict[str, Any]:
        """
        Q-1：截断 MUST 显式。
        Q-3：结果顺序确定。
        """
        items = sorted(items, key=lambda i: (i.get("subject", ""),
                                             i.get("relation", ""),
                                             str(i.get("object", ""))))
        total = len(items)
        truncated = total > max_items
        shown = items[:max_items]
        return {
            "items": shown,
            "truncated": truncated,
            "snapshot": snapshot,
            "budget": {"max_items": max_items, "returned": len(shown),
                       "total": total},
        }

    # ------------------------------------------------------------ 诊断

    def describe_rules(self) -> str:
        if not self.rules:
            return "本体内没有 derived_by 规则"
        lines = [f"派生规则 ({len(self.rules)} 条):"]
        for r in self.rules:
            lines.append(f"  {r.qualified} case#{r.case}: "
                         f"{' → '.join(r.path)}  (role={r.role})")
        return "\n".join(lines)
