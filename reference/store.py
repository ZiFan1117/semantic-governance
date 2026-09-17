"""
事实层 —— 框架 L2（ABox 的载体）。

最小实现选 SQLite：零运维、单文件、支持事务。
框架 §23『最小实现』建议 Postgres 两张表（实体表 + 边表）；
本实现合并为一张 facts 表，用 append-only + 有效区间实现快照读。

关键机制（规范依据 spec/i4-action-minimal.md §3.3）：

  A-1  阶段 6~9 在同一事务内        → sqlite3 的 BEGIN IMMEDIATE
  A-2  前置条件基于同一快照         → tx 号 + valid_from/valid_to 区间
  A-3  快照标识记录进审计           → audit.snapshot
  A-4  事务失败不部分生效           → 回滚

⚠️ 派生事实不落库（框架 I2-4）：本实现**不实现派生**，
   派生规则（Ossie 的 derived_by）会被记录为"未支持"，不静默忽略。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- 事实表：append-only，用有效区间支持快照读
CREATE TABLE IF NOT EXISTS facts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    subject    TEXT NOT NULL,
    relation   TEXT NOT NULL,
    object     TEXT NOT NULL,
    kind       TEXT NOT NULL CHECK (kind IN ('instance', 'literal')),
    valid_from INTEGER NOT NULL,
    valid_to   INTEGER,
    source     TEXT
);
CREATE INDEX IF NOT EXISTS idx_facts_subject
    ON facts(subject, relation, valid_from);

-- 触发本表的动作（用于 I2-3『写入必须带来源』）
CREATE TABLE IF NOT EXISTS versions (
    instance TEXT PRIMARY KEY,
    version  INTEGER NOT NULL DEFAULT 0
);

-- 审计：框架 I4-3 / 规范 §5
CREATE TABLE IF NOT EXISTS audit (
    record_id        TEXT PRIMARY KEY,
    ts               TEXT NOT NULL,
    action           TEXT NOT NULL,
    action_version   TEXT,
    definition_hash  TEXT,
    target           TEXT,
    parameters       TEXT,
    actor            TEXT,
    outcome          TEXT NOT NULL,
    stage            TEXT,
    code             TEXT,
    violations       TEXT,
    snapshot         INTEGER,
    read_concepts    TEXT,
    applied          TEXT,
    before_version   INTEGER,
    after_version    INTEGER,
    trace_id         TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_target ON audit(target, ts);

-- 幂等（规范 §3.4）
CREATE TABLE IF NOT EXISTS idempotency (
    scope_key TEXT PRIMARY KEY,
    record_id TEXT NOT NULL,
    result    TEXT NOT NULL,
    created   TEXT NOT NULL
);
"""


@dataclass
class Fact:
    subject: str
    relation: str
    object: str
    kind: str = "literal"          # instance | literal
    source: str | None = None


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Store:
    """事实层。"""

    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        self.conn = sqlite3.connect(self.path, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self._init_meta()

    def _init_meta(self) -> None:
        with self.transaction():
            row = self.conn.execute(
                "SELECT value FROM meta WHERE key = 'tx'").fetchone()
            if row is None:
                self.conn.execute(
                    "INSERT INTO meta(key, value) VALUES ('tx', '1')")

    def close(self) -> None:
        self.conn.close()

    # ------------------------------------------------------------ 事务

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """独占事务。规范 A-1：效果写入与审计同事务。"""
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")

    # ------------------------------------------------------------ 快照

    def current_snapshot(self) -> int:
        """当前快照号。规范 R-5：审计记录快照标识。"""
        row = self.conn.execute(
            "SELECT value FROM meta WHERE key = 'tx'").fetchone()
        return int(row["value"])

    def bump_snapshot(self) -> int:
        """
        开启一个新的写快照并返回其编号。

        新写入的事实 valid_from = 新编号，因此在旧快照上不可见 ——
        这就是规范 A-2『前置条件基于同一快照』的实现基础。
        """
        cur = self.current_snapshot() + 1
        self.conn.execute(
            "UPDATE meta SET value = ? WHERE key = 'tx'", (str(cur),))
        return cur

    # ------------------------------------------------------------ 读

    def get_objects(self, subject: str, relation: str,
                    snapshot: int | None = None) -> list[str]:
        """取 subject 在 relation 上的所有 object（快照读）。"""
        at = self.current_snapshot() if snapshot is None else snapshot
        rows = self.conn.execute(
            """
            SELECT object FROM facts
             WHERE subject = ? AND relation = ?
               AND valid_from <= ?
               AND (valid_to IS NULL OR valid_to > ?)
             ORDER BY id
            """, (subject, relation, at, at)).fetchall()
        return [r["object"] for r in rows]

    def get_one(self, subject: str, relation: str,
                snapshot: int | None = None) -> str | None:
        """取单值关系。多值时报错（ManyToOne 被违反）。"""
        vals = self.get_objects(subject, relation, snapshot)
        if not vals:
            return None
        if len(vals) > 1:
            raise ValueError(
                f"关系 `{relation}` 在 `{subject}` 上有 {len(vals)} 个值，"
                f"但它被声明为单值（ManyToOne）。数据不一致")
        return vals[0]

    def coerced(self, subject: str, relation: str, concept: str,
                snapshot: int | None = None) -> Any:
        """取值并按 Ossie 声明的值类型做基础类型转换。"""
        raw = self.get_one(subject, relation, snapshot)
        if raw is None:
            return None
        return _coerce(raw, concept)

    def instances_of(self, kind: str = "instance") -> list[str]:
        rows = self.conn.execute(
            """
            SELECT DISTINCT subject FROM facts
             WHERE kind = ? AND valid_to IS NULL
            """, (kind,)).fetchall()
        return [r["subject"] for r in rows]

    # -------------------------------------------------- 类型断言
    # ⚠️ 参考实现暴露的规范缺口：
    #    Ossie 用 `ontology mappings` 描述"物理字段 → 概念"的映射，
    #    但**没有定义运行时的类型断言**（"这个实例属于哪个概念"）。
    #    派生规则的求值需要它来限定主语范围，所以本实现引入保留关系
    #    `__concept`。这应写进 L3/I1 的规范，而不是每个实现自己发明。

    RESERVED_CONCEPT_RELATION = "__concept"

    def set_concept(self, instance: str, concept: str, snapshot: int,
                    source: str | None = None) -> None:
        """断言一个实例所属的概念。"""
        self.set_fact(instance, self.RESERVED_CONCEPT_RELATION, concept,
                      "literal", snapshot, single_valued=True, source=source)

    def concept_of(self, instance: str,
                   snapshot: int | None = None) -> str | None:
        return self.get_one(instance, self.RESERVED_CONCEPT_RELATION, snapshot)

    def instances_of_concept(self, concept: str,
                             snapshot: int | None = None) -> list[str]:
        at = self.current_snapshot() if snapshot is None else snapshot
        rows = self.conn.execute(
            """
            SELECT subject FROM facts
             WHERE relation = ? AND object = ?
               AND valid_from <= ?
               AND (valid_to IS NULL OR valid_to > ?)
             ORDER BY subject
            """, (self.RESERVED_CONCEPT_RELATION, concept, at, at)).fetchall()
        return [r["subject"] for r in rows]

    def exists(self, instance: str, snapshot: int | None = None) -> bool:
        at = self.current_snapshot() if snapshot is None else snapshot
        row = self.conn.execute(
            """
            SELECT 1 FROM facts
             WHERE subject = ? AND valid_from <= ?
               AND (valid_to IS NULL OR valid_to > ?)
             LIMIT 1
            """, (instance, at, at)).fetchone()
        return row is not None

    # ------------------------------------------------------------ 写

    def assert_fact(self, fact: Fact, snapshot: int) -> None:
        """断言一条事实（追加）。用于多值关系。"""
        self.conn.execute(
            """
            INSERT INTO facts(subject, relation, object, kind,
                              valid_from, source)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (fact.subject, fact.relation, fact.object, fact.kind,
                  snapshot, fact.source))

    def set_fact(self, subject: str, relation: str, obj: str, kind: str,
                 snapshot: int, single_valued: bool,
                 source: str | None = None) -> None:
        """
        写入一条事实，**并在写入路径上强制 multiplicity 约束**。

        规范依据：框架 I2-1『写入必须过规则』。

        ⚠️ 这是参考实现暴露出的一个真实教训：
           最初的实现把 multiplicity 只在**读取时**检查，
           结果是「脏数据能写进去，读取时才炸」——
           正好违反了 I2-1 的立意。规则必须在写入路径上。

        single_valued=True  单值关系（Ossie 的 ManyToOne / OneToOne）
                            → 旧值在 snapshot 处失效，新值生效
        single_valued=False 多值关系
                            → 追加
        """
        if single_valued:
            self.replace_fact(subject, relation, obj, kind, snapshot, source)
        else:
            self.assert_fact(Fact(subject, relation, obj, kind, source), snapshot)

    def replace_fact(self, subject: str, relation: str, obj: str,
                     kind: str, snapshot: int, source: str | None = None) -> None:
        """
        替换单值关系上的值：旧值在 snapshot 处失效，新值从 snapshot 起有效。
        这是"改属性"在 append-only 事实层里的正确做法 —— 保留历史。
        """
        self.conn.execute(
            """
            UPDATE facts SET valid_to = ?
             WHERE subject = ? AND relation = ? AND valid_to IS NULL
            """, (snapshot, subject, relation))
        self.assert_fact(
            Fact(subject, relation, obj, kind, source), snapshot)

    # ------------------------------------------------------------ 版本

    def get_version(self, instance: str) -> int:
        row = self.conn.execute(
            "SELECT version FROM versions WHERE instance = ?",
            (instance,)).fetchone()
        return int(row["version"]) if row else 0

    def bump_version(self, instance: str) -> int:
        cur = self.get_version(instance)
        nxt = cur + 1
        self.conn.execute(
            """
            INSERT INTO versions(instance, version) VALUES (?, ?)
            ON CONFLICT(instance) DO UPDATE SET version = excluded.version
            """, (instance, nxt))
        return nxt

    # ------------------------------------------------------------ 审计

    def write_audit(self, record: dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT INTO audit(
                record_id, ts, action, action_version, definition_hash,
                target, parameters, actor, outcome, stage, code,
                violations, snapshot, read_concepts, applied,
                before_version, after_version, trace_id
            ) VALUES (
                :record_id, :ts, :action, :action_version, :definition_hash,
                :target, :parameters, :actor, :outcome, :stage, :code,
                :violations, :snapshot, :read_concepts, :applied,
                :before_version, :after_version, :trace_id
            )
            """, {
                "record_id": record["record_id"],
                "ts": record["ts"],
                "action": record["action"],
                "action_version": record.get("action_version"),
                "definition_hash": record.get("definition_hash"),
                "target": record.get("target"),
                "parameters": json.dumps(record.get("parameters"),
                                         ensure_ascii=False),
                "actor": json.dumps(record.get("actor"), ensure_ascii=False),
                "outcome": record["outcome"],
                "stage": record.get("stage"),
                "code": record.get("code"),
                "violations": json.dumps(record.get("violations", []),
                                         ensure_ascii=False),
                "snapshot": record.get("snapshot"),
                "read_concepts": json.dumps(record.get("read_concepts", []),
                                            ensure_ascii=False),
                "applied": json.dumps(record.get("applied", []),
                                      ensure_ascii=False),
                "before_version": record.get("before_version"),
                "after_version": record.get("after_version"),
                "trace_id": record.get("trace_id"),
            })

    def audit_records(self, target: str | None = None) -> list[dict]:
        if target:
            rows = self.conn.execute(
                "SELECT * FROM audit WHERE target = ? ORDER BY ts",
                (target,)).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM audit ORDER BY ts").fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------ 幂等

    @staticmethod
    def scope_key(action: str, target: str, key: str) -> str:
        """规范 I-3：作用域 MUST 至少覆盖 动作名 + 目标实例 + 幂等键值。"""
        return f"{action}|{target}|{key}"

    def idempotent_lookup(self, scope_key: str) -> dict | None:
        row = self.conn.execute(
            "SELECT result FROM idempotency WHERE scope_key = ?",
            (scope_key,)).fetchone()
        return json.loads(row["result"]) if row else None

    def idempotent_store(self, scope_key: str, record_id: str,
                         result: dict) -> None:
        self.conn.execute(
            """
            INSERT INTO idempotency(scope_key, record_id, result, created)
            VALUES (?, ?, ?, ?)
            """, (scope_key, record_id,
                  json.dumps(result, ensure_ascii=False), utcnow()))

    # ------------------------------------------------------------ 工具

    @staticmethod
    def new_record_id() -> str:
        return uuid.uuid4().hex[:26]

    def stats(self) -> dict:
        return {
            "facts": self.conn.execute(
                "SELECT COUNT(*) c FROM facts").fetchone()["c"],
            "live_facts": self.conn.execute(
                "SELECT COUNT(*) c FROM facts WHERE valid_to IS NULL"
            ).fetchone()["c"],
            "instances": self.conn.execute(
                "SELECT COUNT(DISTINCT subject) c FROM facts").fetchone()["c"],
            "audit": self.conn.execute(
                "SELECT COUNT(*) c FROM audit").fetchone()["c"],
            "snapshot": self.current_snapshot(),
        }


# --------------------------------------------------------------------------
# 值类型转换（按 Ossie 的 extends 链）
# --------------------------------------------------------------------------

_BUILTIN_CAST = {
    "String": str,
    "Integer": int,
    "Float": float,
    "Decimal": float,
    "Boolean": lambda v: (str(v).lower() in ("true", "1", "yes")
                          if not isinstance(v, bool) else v),
}


def _coerce(raw: str, concept: str, model=None) -> Any:
    """把事实层的字面量转成 Ossie 声明的值类型。"""
    if model is not None:
        try:
            chain = [concept, *model.all_supertypes(concept)]
        except Exception:
            chain = [concept]
    else:
        chain = [concept]

    for name in chain:
        cast = _BUILTIN_CAST.get(name)
        if cast is not None:
            try:
                return cast(raw)
            except (ValueError, TypeError):
                return raw
    return raw
