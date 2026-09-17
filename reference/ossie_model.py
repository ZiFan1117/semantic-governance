"""
Ossie 本体加载器 —— 框架 L3（TBox 载体）/ 接口 I1 的最小实现。

严格按 Apache Ossie 本体规范读取：
    https://github.com/apache/ossie/blob/main/ontology/ontology.md

只支持参考实现需要的子集。**不支持的字段会被显式记录，不静默忽略。**
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Ossie 规范 §Enumerations / Built-in concepts
BUILTIN_CONCEPTS = {
    "Any", "Boolean", "Date", "DateTime",
    "Decimal", "Float", "Integer", "String",
}

# Ossie 规范 §Multiplicities
VALID_MULTIPLICITY = {"ManyToOne", "OneToOne"}


class OssieError(Exception):
    """本体定义不合法。对应框架 I1-2『可自检』。"""


# --------------------------------------------------------------------------
# 数据模型
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Role:
    """关系中的一个角色。"""
    concept: str
    name: str | None = None

    @property
    def key(self) -> str:
        """表达式中引用该角色所用的名字。"""
        return self.name or self.concept


@dataclass
class Relationship:
    """关系。在 Ossie 中由声明它的 concept 限定，全名为 `<Concept>.<name>`。"""
    concept: str
    name: str
    roles: list[Role] = field(default_factory=list)
    multiplicity: str | None = None
    requires: list[str] = field(default_factory=list)
    derived_by: list[str] = field(default_factory=list)
    verbalizes: list[str] = field(default_factory=list)
    description: str | None = None

    @property
    def qualified(self) -> str:
        return f"{self.concept}.{self.name}"

    @property
    def value_concept(self) -> str | None:
        """最后一个角色的概念名 —— 即该关系的『值域』。"""
        return self.roles[-1].concept if self.roles else None


@dataclass
class Concept:
    """概念。EntityType（实体）或 ValueType（值类型）。"""
    name: str
    type: str
    extends: list[str] = field(default_factory=list)
    description: str | None = None
    requires: list[str] = field(default_factory=list)
    derived_by: list[str] = field(default_factory=list)
    identify_by: list[str] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    ai_context: Any = None

    @property
    def is_entity(self) -> bool:
        return self.type == "EntityType"

    @property
    def is_value(self) -> bool:
        return self.type == "ValueType"

    def relation(self, name: str) -> Relationship | None:
        for r in self.relationships:
            if r.name == name:
                return r
        return None


@dataclass
class Unsupported:
    """记录遇到但本实现不支持的 Ossie 特性。**不静默忽略。**"""
    where: str
    field: str
    detail: str = ""

    def __str__(self) -> str:
        tail = f" ({self.detail})" if self.detail else ""
        return f"{self.where}: 不支持字段 `{self.field}`{tail}"


# --------------------------------------------------------------------------
# 加载器
# --------------------------------------------------------------------------

class OssieModel:
    """一份 Ossie 本体。"""

    #: 本实现支持的概念字段
    SUPPORTED_CONCEPT_FIELDS = {
        "concept", "type", "extends", "description",
        "requires", "derived_by", "identify_by", "relationships",
        "ai_context",
    }
    #: 本实现支持的关系字段
    SUPPORTED_RELATION_FIELDS = {
        "name", "roles", "multiplicity", "requires",
        "derived_by", "verbalizes", "description",
    }

    def __init__(self, name: str, concepts: dict[str, Concept],
                 unsupported: list[Unsupported]):
        self.name = name
        self.concepts = concepts
        self.unsupported = unsupported
        self._super_cache: dict[str, set[str]] = {}

    # ---------------------------------------------------------------- 加载

    @classmethod
    def from_file(cls, path: str | Path) -> "OssieModel":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(raw, source=str(path))

    @classmethod
    def from_dict(cls, raw: dict, source: str = "<dict>") -> "OssieModel":
        if not isinstance(raw, dict):
            raise OssieError(f"{source}: 顶层必须是 mapping")
        if "ontology" not in raw:
            raise OssieError(f"{source}: 缺少 `ontology` 字段")

        concepts: dict[str, Concept] = {}
        unsupported: list[Unsupported] = []

        for entry in raw["ontology"] or []:
            concept = cls._parse_concept(entry, source, unsupported)
            if concept.name in concepts:
                raise OssieError(f"{source}: 概念 `{concept.name}` 重复声明")
            concepts[concept.name] = concept

        model = cls(raw.get("name", "<unnamed>"), concepts, unsupported)
        model.validate()
        return model

    @classmethod
    def _parse_concept(cls, entry: dict, source: str,
                       unsupported: list[Unsupported]) -> Concept:
        if "concept" not in entry:
            raise OssieError(f"{source}: ontology 条目缺少 `concept`")
        name = entry["concept"]

        for key in entry:
            if key not in cls.SUPPORTED_CONCEPT_FIELDS:
                unsupported.append(Unsupported(name, key))

        ctype = entry.get("type")
        if ctype not in ("EntityType", "ValueType"):
            raise OssieError(
                f"{source}: 概念 `{name}` 的 type 必须是 EntityType 或 ValueType，"
                f"实为 {ctype!r}"
            )

        rels: list[Relationship] = []
        for rentry in entry.get("relationships") or []:
            rels.append(cls._parse_relationship(name, rentry, source, unsupported))

        return Concept(
            name=name,
            type=ctype,
            extends=list(entry.get("extends") or []),
            description=entry.get("description"),
            requires=list(entry.get("requires") or []),
            derived_by=list(entry.get("derived_by") or []),
            identify_by=list(entry.get("identify_by") or []),
            relationships=rels,
            ai_context=entry.get("ai_context"),
        )

    @classmethod
    def _parse_relationship(cls, owner: str, entry: dict, source: str,
                            unsupported: list[Unsupported]) -> Relationship:
        if "name" not in entry:
            raise OssieError(f"{source}: `{owner}` 下的关系缺少 `name`")

        for key in entry:
            if key not in cls.SUPPORTED_RELATION_FIELDS:
                unsupported.append(Unsupported(f"{owner}.{entry['name']}", key))

        roles: list[Role] = []
        for r in entry.get("roles") or []:
            if "concept" not in r:
                raise OssieError(
                    f"{source}: `{owner}.{entry['name']}` 的角色缺少 `concept`")
            roles.append(Role(concept=r["concept"], name=r.get("name")))

        mult = entry.get("multiplicity")
        if mult is not None and mult not in VALID_MULTIPLICITY:
            raise OssieError(
                f"{source}: `{owner}.{entry['name']}` 的 multiplicity "
                f"必须是 {sorted(VALID_MULTIPLICITY)}，实为 {mult!r}"
            )

        return Relationship(
            concept=owner,
            name=entry["name"],
            roles=roles,
            multiplicity=mult,
            requires=list(entry.get("requires") or []),
            derived_by=list(entry.get("derived_by") or []),
            verbalizes=list(entry.get("verbalizes") or []),
            description=entry.get("description"),
        )

    # ---------------------------------------------------------------- 自检
    # 对应框架 I1-2『可自检』：环、悬空引用、冲突

    def validate(self) -> None:
        errors: list[str] = []

        for c in self.concepts.values():
            # 悬空引用：extends
            for parent in c.extends:
                if parent not in self.concepts and parent not in BUILTIN_CONCEPTS:
                    errors.append(f"概念 `{c.name}` extends 了未声明的 `{parent}`")

            # 悬空引用：关系的角色
            for r in c.relationships:
                if not r.roles:
                    errors.append(f"关系 `{r.qualified}` 没有任何角色")
                for role in r.roles:
                    if (role.concept not in self.concepts
                            and role.concept not in BUILTIN_CONCEPTS):
                        errors.append(
                            f"关系 `{r.qualified}` 的角色引用了未声明的 "
                            f"`{role.concept}`")

            # ValueType 必须（直接或间接）继承内置值类型
            if c.is_value:
                supers = self.all_supertypes(c.name)
                if not (supers & BUILTIN_CONCEPTS):
                    errors.append(
                        f"值类型 `{c.name}` 未（直接或间接）继承任何内置值类型")

            # identify_by 必须是自身声明的关系
            for ident in c.identify_by:
                if c.relation(ident) is None:
                    errors.append(
                        f"概念 `{c.name}` 的 identify_by 引用了未声明的关系 "
                        f"`{ident}`")

        # 环检测
        for name in self.concepts:
            if self._has_cycle(name):
                errors.append(f"概念 `{name}` 的 extends 链上存在环")

        if errors:
            raise OssieError("本体自检失败:\n  - " + "\n  - ".join(sorted(set(errors))))

    def _has_cycle(self, start: str) -> bool:
        seen, stack = set(), [start]
        while stack:
            cur = stack.pop()
            c = self.concepts.get(cur)
            if not c:
                continue
            for parent in c.extends:
                if parent == start:
                    return True
                if parent not in seen:
                    seen.add(parent)
                    stack.append(parent)
        return False

    # ---------------------------------------------------------------- 查询

    def concept(self, name: str) -> Concept:
        try:
            return self.concepts[name]
        except KeyError:
            raise OssieError(f"未声明的概念 `{name}`") from None

    def has_concept(self, name: str) -> bool:
        return name in self.concepts

    def all_supertypes(self, name: str) -> set[str]:
        """传递闭包：所有祖先概念（不含自身）。"""
        if name in self._super_cache:
            return self._super_cache[name]
        out: set[str] = set()
        stack = [name]
        while stack:
            cur = stack.pop()
            c = self.concepts.get(cur)
            if not c:
                continue
            for p in c.extends:
                if p not in out:
                    out.add(p)
                    stack.append(p)
        self._super_cache[name] = out
        return out

    def is_subtype(self, child: str, parent: str) -> bool:
        """child 是否（直接或间接）是 parent 的子类型。子类关系是传递的。"""
        if child == parent:
            return True
        return parent in self.all_supertypes(child)

    def find_relation(self, concept: str, name: str) -> Relationship:
        """按概念名找关系，会沿 extends 向上查找（子类继承父类的关系）。"""
        chain, cur = [], concept
        while cur and cur not in chain:
            chain.append(cur)
            c = self.concepts.get(cur)
            if c is None:
                break
            r = c.relation(name)
            if r is not None:
                return r
            cur = c.extends[0] if c.extends else None
        raise OssieError(f"概念 `{concept}` 上没有关系 `{name}`")

    def describe(self) -> str:
        lines = [f"Ossie 本体: {self.name}",
                 f"  概念数: {len(self.concepts)}"]
        ent = [c.name for c in self.concepts.values() if c.is_entity]
        val = [c.name for c in self.concepts.values() if c.is_value]
        lines.append(f"  实体类型 ({len(ent)}): {', '.join(sorted(ent))}")
        lines.append(f"  值类型   ({len(val)}): {', '.join(sorted(val))}")
        if self.unsupported:
            lines.append(f"  ⚠️ 不支持的字段 ({len(self.unsupported)}):")
            for u in self.unsupported:
                lines.append(f"      - {u}")
        return "\n".join(lines)
