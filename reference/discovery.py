"""
I6 发现接口 —— 最小实现。

实现 spec/i6-discovery-minimal.md。

关键点：**目录不是手写的，是从 Ossie 本体 + 动作定义自动生成的。**
这保证了发现结果与 L3 的定义永不脱节（框架 I1-2『可自检』的延伸）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from engine import ActionDef
from ossie_model import Concept, OssieModel


# --------------------------------------------------------------------------
# 动作注册表
# --------------------------------------------------------------------------

class ActionRegistry:
    """已加载的动作定义。真实实现应支持热加载与版本共存。"""

    def __init__(self) -> None:
        self._by_qualified: dict[str, ActionDef] = {}

    def register(self, action: ActionDef) -> None:
        self._by_qualified[action.qualified] = action

    def all(self) -> list[ActionDef]:
        return [self._by_qualified[k] for k in sorted(self._by_qualified)]

    def get(self, qualified: str) -> ActionDef | None:
        return self._by_qualified.get(qualified)

    def __len__(self) -> int:
        return len(self._by_qualified)


# --------------------------------------------------------------------------
# 权限过滤（I3-3 / I6-3）
# --------------------------------------------------------------------------

CapabilityFilter = Callable[[str, str], bool]
"""签名: (actor, concept_name) -> 可见?"""


def allow_all(actor: str, concept: str) -> bool:
    """
    ⚠️ 默认过滤器：**放行一切**。

    这个默认值是**不安全的**，保留它只是为了让参考实现能零配置跑起来。
    规范 `G2` 要求结果 MUST 按权限过滤 —— 生产实现 **MUST** 注入真实过滤器。
    """
    return True


# --------------------------------------------------------------------------
# 目录
# --------------------------------------------------------------------------

@dataclass
class CapabilityMatch:
    qualified: str
    version: str
    description: str | None
    target_concept: str
    score: float
    matched_on: list[dict[str, str]]


class Catalog:
    """I6 的门面。"""

    def __init__(self, model: OssieModel, registry: ActionRegistry,
                 visible: CapabilityFilter = allow_all):
        self.model = model
        self.registry = registry
        self.visible = visible

    # ------------------------------------------------------------ 枚举

    def list_concepts(self, actor: str = "user:anonymous", *,
                      kind: str | None = None,
                      domain: str | None = None,
                      keyword: str | None = None) -> list[dict[str, Any]]:
        """I6-1：可完整枚举（顺序确定由 §15 保证 G4 承担）。"""
        out = []
        for name in sorted(self.model.concepts):
            c = self.model.concepts[name]
            if not self.visible(actor, name):
                continue
            if kind and c.type != kind:
                continue
            if keyword and not _text_hit(keyword, c.name, c.description):
                continue
            out.append({
                "name": c.name,
                "type": c.type,
                "description": c.description,
                "identify_by": list(c.identify_by),
                "extends": list(c.extends),
                "relation_count": len(c.relationships),
            })
        return out

    def get_concept_detail(self, name: str,
                           actor: str = "user:anonymous") -> dict[str, Any]:
        c = self.model.concept(name)
        if not self.visible(actor, name):
            raise PermissionError(f"主体 `{actor}` 不可见概念 `{name}`")
        return {
            "name": c.name,
            "type": c.type,
            "description": c.description,
            "extends": list(c.extends),
            "identify_by": list(c.identify_by),
            "requires": list(c.requires),
            "ai_context": c.ai_context,
            "relationships": [
                {
                    "name": r.name,
                    "qualified": r.qualified,
                    "roles": [{"concept": ro.concept, "name": ro.name}
                              for ro in r.roles],
                    "multiplicity": r.multiplicity,
                    "verbalizes": list(r.verbalizes),
                    "derived_by": list(r.derived_by),
                }
                for r in c.relationships
            ],
        }

    # ------------------------------------------------------------ 动作

    def list_actions(self, actor: str = "user:anonymous",
                     concept: str | None = None) -> list[dict[str, Any]]:
        out = []
        for a in self.registry.all():
            if concept and a.target_concept != concept:
                continue
            if not self.visible(actor, a.target_concept):
                continue
            out.append(self._summary(a))
        return out

    def describe_action(self, qualified: str,
                        actor: str = "user:anonymous") -> dict[str, Any]:
        """I6-E-2：返回足以构造提交请求的完整契约。"""
        a = self.registry.get(qualified)
        if a is None:
            raise KeyError(f"未注册的动作 `{qualified}`")
        if not self.visible(actor, a.target_concept):
            raise PermissionError(f"主体 `{actor}` 不可见动作 `{qualified}`")
        return {
            "name": a.name,
            "qualified": a.qualified,
            "namespace": a.namespace,
            "version": a.version,
            "description": a.description,
            "ai_context": a.ai_context,
            "definition_hash": a.definition_hash,
            "target": {"concept": a.target_concept, "reads": list(a.reads)},
            "parameters": [
                {"name": p.name, "type": p.type, "required": p.required,
                 "description": p.description, "constraints": list(p.constraints)}
                for p in a.parameters
            ],
            "permissions": {"relation": a.permission_relation},
            "preconditions": [
                {"id": p.id, "expression": p.expression, "message": p.message}
                for p in a.preconditions
            ],
            "effects": [{"path": e.path, "value": e.expression}
                        for e in a.effects],
            "idempotency": {"key": a.idempotency_key},
            "side_effects": [],
            "async": False,
        }

    # ------------------------------------------------------------ 按需查找

    def find_by_capability(self, need: str, actor: str = "user:anonymous", *,
                           concept: str | None = None,
                           limit: int = 5) -> list[dict[str, Any]]:
        """
        I6-F：按需求找能力。

        F-3  MUST 给出 matched_on
        F-6  无匹配 MUST 返回空列表，MUST NOT 兜底
        G4   顺序确定
        """
        scored: list[CapabilityMatch] = []
        for a in self.registry.all():
            if concept and a.target_concept != concept:
                continue
            if not self.visible(actor, a.target_concept):
                continue
            score, matched = self._score(a, need)
            if score > 0:
                scored.append(CapabilityMatch(
                    qualified=a.qualified, version=a.version,
                    description=a.description, target_concept=a.target_concept,
                    score=score, matched_on=matched))

        # 分数降序；同分按名字升序 —— 保证 G4 确定性
        scored.sort(key=lambda m: (-m.score, m.qualified))
        top = scored[:limit]

        return [{
            "qualified": m.qualified,
            "version": m.version,
            "description": m.description,
            "target_concept": m.target_concept,
            "score": round(m.score, 4),
            "matched_on": m.matched_on,
        } for m in top]

    # ------------------------------------------------------------ 内部

    @staticmethod
    def _summary(a: ActionDef) -> dict[str, Any]:
        return {
            "name": a.name,
            "qualified": a.qualified,
            "version": a.version,
            "description": a.description,
            "ai_context": a.ai_context,
            "target_concept": a.target_concept,
            "parameter_names": [p.name for p in a.parameters],
            "precondition_ids": [p.id for p in a.preconditions],
        }

    def _score(self, a: ActionDef, need: str) -> tuple[float, list[dict]]:
        """
        关键词匹配。权重：ai_context > description > name > concept。

        ⚠️ 这是 I6-F-2 的最低要求（关键词匹配）。
           F-5 的语义检索（向量）是 SHOULD，本实现未做。
        """
        fields = (
            ("ai_context", a.ai_context or "", 3.0),
            ("description", a.description or "", 2.0),
            ("name", a.name, 1.5),
            ("target_concept", a.target_concept, 1.0),
            ("concept_description",
             (self.model.concept(a.target_concept).description or "")
             if self.model.has_concept(a.target_concept) else "", 1.0),
        )
        matched: list[dict[str, str]] = []
        total = 0.0
        for fname, text, weight in fields:
            hit = _text_hit_evidence(need, text)
            if hit:
                total += weight * hit["ratio"]
                matched.append({"field": fname, "evidence": hit["evidence"]})
        # 归一化到 0~1（权重和 = 8.5）
        return (total / 8.5 if total else 0.0), matched


# --------------------------------------------------------------------------
# 匹配工具（CJK 友好：空格分词 + 2-gram 回退）
# --------------------------------------------------------------------------

_CJK = re.compile(r"[\u4e00-\u9fff]")


def _tokens(text: str) -> set[str]:
    text = (text or "").strip().lower()
    if not text:
        return set()
    parts = {p for p in re.split(r"[\s,，。、;；:：()（）]+", text) if p}
    if not _CJK.search(text):
        return parts
    grams = set(parts)
    for p in list(parts):
        if len(p) >= 2:
            grams.update(p[i:i + 2] for i in range(len(p) - 1))
    return grams


def _text_hit(need: str, *texts: str | None) -> bool:
    return _text_hit_evidence(need, *texts) is not None


def _text_hit_evidence(need: str, *texts: str | None) -> dict | None:
    want = _tokens(need)
    if not want:
        return None
    hay = _tokens(" ".join(t for t in texts if t))
    if not hay:
        return None
    hit = want & hay
    if not hit:
        return None
    return {
        "ratio": len(hit) / len(want),
        "evidence": "、".join(sorted(hit)),
    }
