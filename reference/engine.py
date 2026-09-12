"""
I4 动作引擎 —— 本参考实现的核心。

严格实现 spec/i4-action-minimal.md 定义的 10 个阶段与全部 MUST 条款。

    S-1  阶段顺序固定，权限 MUST 早于前置条件
    S-2  前置条件求值 MUST 在同一快照
    S-3  参数校验失败 MUST NOT 读取目标实例
    A-1  阶段 6~9 在同一事务
    A-4  失败不部分生效
    I-1..I-4  幂等
    C-1..C-3  乐观并发
    R-1..R-6  审计
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from expr import ExpressionError, compile_expr, evaluate, DictResolver
from ossie_model import OssieError, OssieModel
from store import Fact, Store, utcnow

# --------------------------------------------------------------------------
# 动作定义
# --------------------------------------------------------------------------


class ActionError(Exception):
    """动作定义不合法。"""


@dataclass
class Parameter:
    name: str
    type: str
    required: bool = True
    description: str | None = None
    constraints: list[str] = field(default_factory=list)


@dataclass
class Precondition:
    id: str
    expression: str
    message: str


@dataclass
class Effect:
    path: str
    expression: str
    on: str = "default"          # v0.2：作用于哪个目标（默认主目标）


@dataclass
class TargetSpec:
    """
    v0.2 附属目标：从主目标出发，沿关系路径到达的另一个实例。

    存在意义：一次动作常常需要**原子地**改多个实例
    （如"取消订单"同时要改订单和它的发货单）。
    """
    name: str
    concept: str
    via: list[str]               # 从主目标出发的关系路径


@dataclass
class ActionDef:
    name: str
    namespace: str
    version: str
    target_concept: str
    reads: list[str]
    parameters: list[Parameter]
    permission_relation: str
    preconditions: list[Precondition]
    effects: list[Effect]
    idempotency_key: str
    description: str | None = None
    ai_context: str | None = None
    definition_hash: str = ""
    # --- v0.2 ---
    extra_targets: list[TargetSpec] = field(default_factory=list)

    @property
    def target_names(self) -> list[str]:
        return ["default"] + [t.name for t in self.extra_targets]

    @property
    def qualified(self) -> str:
        return f"{self.namespace}:{self.name}"

    @property
    def qualified_versioned(self) -> str:
        return f"{self.qualified}@{self.version}"

    def parameter(self, name: str) -> Parameter | None:
        for p in self.parameters:
            if p.name == name:
                return p
        return None


class ActionLoader:
    """加载动作定义，并校验它对 Ossie 本体的引用（规范 D-1）。"""

    @staticmethod
    def load(path: str | Path, model: OssieModel) -> ActionDef:
        raw_bytes = Path(path).read_bytes()
        raw = yaml.safe_load(raw_bytes.decode("utf-8"))
        if not isinstance(raw, dict) or "action" not in raw:
            raise ActionError(f"{path}: 顶层缺少 `action`")
        a = raw["action"]

        for required in ("name", "namespace", "version", "target",
                         "effects", "idempotency"):
            if required not in a:
                raise ActionError(f"{path}: 缺少必填字段 `{required}`")

        # --- D-3：最小 I4 排除项 ---
        if a.get("side_effects"):
            raise ActionError(
                "`side_effects` 必须为空数组 —— 最小 I4 不支持副作用")
        if a.get("async"):
            raise ActionError("`async` 必须为 false —— 最小 I4 不支持异步")

        target = a["target"]
        concept = target["concept"]
        # --- D-1：MUST 引用 L3 中已声明的概念 ---
        if not model.has_concept(concept):
            raise ActionError(
                f"target.concept `{concept}` 未在 Ossie 本体中声明")
        for c in target.get("reads", []):
            if not model.has_concept(c):
                raise ActionError(f"target.reads 中的 `{c}` 未在 Ossie 本体中声明")
        if not model.concept(concept).is_entity:
            raise ActionError(f"target.concept `{concept}` 必须是 EntityType")

        # --- 参数 ---
        params: list[Parameter] = []
        for p in a.get("parameters") or []:
            ptype = p["type"]
            if not model.has_concept(ptype):
                raise ActionError(
                    f"参数 `{p['name']}` 的类型 `{ptype}` 未在 Ossie 本体中声明")
            if not model.concept(ptype).is_value:
                raise ActionError(
                    f"参数 `{p['name']}` 的类型 `{ptype}` 必须是 ValueType")
            params.append(Parameter(
                name=p["name"], type=ptype,
                required=bool(p.get("required", True)),
                description=p.get("description"),
                constraints=list(p.get("constraints") or []),
            ))

        # --- 前置条件 ---
        pres: list[Precondition] = []
        for pr in a.get("preconditions") or []:
            for key in ("id", "expression", "message"):
                if key not in pr:
                    raise ActionError(f"前置条件缺少 `{key}`")
            try:
                compile_expr(pr["expression"])
            except ExpressionError as e:
                raise ActionError(
                    f"前置条件 `{pr['id']}` 表达式非法: {e}") from None
            pres.append(Precondition(pr["id"], pr["expression"], pr["message"]))

        ids = [p.id for p in pres]
        if len(ids) != len(set(ids)):
            raise ActionError("前置条件的 id 必须唯一")

        # --- 效果（D-2：MUST NOT 为空）---
        effects: list[Effect] = []
        for e in a.get("effects") or []:
            if "set" not in e:
                raise ActionError(
                    "最小 I4 的 effect 只支持 `set`（改目标实例的属性）")
            s = e["set"]
            path, expr = s["path"], str(s["value"])

            # ⚠️ v0.2 的字段名是 `applies_to`，**不是 `on`**。
            #    YAML 1.1 把 `on` / `off` / `yes` / `no` 解析为布尔值，
            #    所以 `on: customer` 的键名会变成 True 而不是字符串 "on"，
            #    导致字段静默丢失。这是格式规范必须避开的坑。
            if "on" in e or True in e:
                raise ActionError(
                    "effect 使用 `on` 作为键名是**不合法的** —— "
                    "YAML 1.1 会把 `on` 解析成布尔值 true，键名丢失。"
                    "请改用 `applies_to`")
            on = e.get("applies_to", "default")
            # v0.2：on 必须指向已声明的目标
            if on != "default" and on not in [t["name"] for t in
                                              (target.get("also_write") or [])]:
                raise ActionError(
                    f"effect 的 `on: {on}` 未在 target.also_write 中声明")
            # 作用于附属目标时，关系要在该目标的概念上校验
            check_concept = concept
            if on != "default":
                for t in target.get("also_write") or []:
                    if t["name"] == on:
                        check_concept = t["concept"]
                        break
            rel = model.concept(check_concept).relation(path)
            if rel is None:
                try:
                    rel = model.find_relation(check_concept, path)
                except OssieError:
                    raise ActionError(
                        f"effect 的 path `{path}` 不是 `{check_concept}` 上的关系"
                    ) from None
            try:
                compile_expr(expr)
            except ExpressionError as ex:
                raise ActionError(
                    f"effect `{path}` 的 value 表达式非法: {ex}") from None
            effects.append(Effect(path, expr, on))

        if not effects:
            raise ActionError("`effects` 必须非空 —— 否则它不是一个动作")

        # --- v0.2：附属目标 ---
        extra: list[TargetSpec] = []
        for t in target.get("also_write") or []:
            tname = t.get("name")
            tconcept = t.get("concept")
            via = t.get("via")
            if not tname or not tconcept or not via:
                raise ActionError(
                    "target.also_write 的每一项 MUST 含 name / concept / via")
            if tname == "default":
                raise ActionError("附属目标的 name MUST NOT 为 `default`")
            if tname in [x.name for x in extra]:
                raise ActionError(f"附属目标 `{tname}` 重复声明")
            if not model.has_concept(tconcept):
                raise ActionError(f"附属目标 `{tname}` 的概念 `{tconcept}` 未声明")
            path = via if isinstance(via, list) else [via]
            # via 的第一跳必须在主目标概念上存在
            try:
                model.find_relation(concept, path[0])
            except OssieError:
                raise ActionError(
                    f"附属目标 `{tname}` 的 via 首跳 `{path[0]}` "
                    f"不是 `{concept}` 上的关系") from None
            extra.append(TargetSpec(name=tname, concept=tconcept, via=path))

        if not extra and any(e.on != "default" for e in effects):
            raise ActionError("使用了 `on:` 但未声明 target.also_write")

        return ActionDef(
            name=a["name"],
            namespace=a["namespace"],
            version=str(a["version"]),
            target_concept=concept,
            reads=list(target.get("reads") or []),
            parameters=params,
            permission_relation=a.get("permissions", {}).get("relation", ""),
            preconditions=pres,
            effects=effects,
            idempotency_key=a["idempotency"]["key"],
            description=a.get("description"),
            ai_context=a.get("ai_context"),
            definition_hash="sha256:" + hashlib.sha256(raw_bytes).hexdigest(),
            extra_targets=extra,
        )


# --------------------------------------------------------------------------
# 最小授权（生产应换 OpenFGA）
# --------------------------------------------------------------------------

class SimpleAuthz:
    """
    最小授权引擎。

    ⚠️ 这不是本规范的一部分 —— 规范只要求"必须校验权限"，
       并把权限模型交给外部（框架 §13.5 推荐 OpenFGA）。

    本实现用 Zanzibar 风格的 (subject, relation, object) 元组，
    因为它与 Ossie 的 concept/relationship 天然同构（框架 §13.6）。
    """

    def __init__(self) -> None:
        self.tuples: set[tuple[str, str, str]] = set()

    def grant(self, subject: str, relation: str, obj: str) -> None:
        self.tuples.add((subject, relation, obj))

    def revoke(self, subject: str, relation: str, obj: str) -> None:
        self.tuples.discard((subject, relation, obj))

    def check(self, subject: str, relation: str, obj: str) -> bool:
        return (subject, relation, obj) in self.tuples


# --------------------------------------------------------------------------
# 目标的属性视图（表达式里的 `target`）
# --------------------------------------------------------------------------

class TargetView:
    """
    表达式里的 `target`。

    属性访问会查 Ossie 声明的**关系**，并按值类型转换。
    记录读取过的属性，用于生成拒绝信息里的 `actual`。
    """

    def __init__(self, store: Store, model: OssieModel,
                 instance: str, concept: str, snapshot: int):
        self.store = store
        self.model = model
        self.instance = instance
        self.concept = concept
        self.snapshot = snapshot
        self.reads: dict[str, Any] = {}

    def attr(self, name: str) -> Any:
        if name in self.reads:
            return self.reads[name]
        rel = self.model.find_relation(self.concept, name)
        value_concept = rel.value_concept
        raw = self.store.get_one(self.instance, name, self.snapshot)
        if raw is None:
            value: Any = None
        elif value_concept and self.model.has_concept(value_concept) \
                and self.model.concept(value_concept).is_value:
            from store import _coerce
            value = _coerce(raw, value_concept, self.model)
        else:
            value = raw
        self.reads[name] = value
        return value


# --------------------------------------------------------------------------
# 引擎
# --------------------------------------------------------------------------

class ActionEngine:

    def __init__(self, model: OssieModel, store: Store,
                 authz: SimpleAuthz | None = None, catalog=None):
        self.model = model
        self.store = store
        self.authz = authz or SimpleAuthz()
        # I6 目录。用于在拒绝时给出替代动作建议（见 spec/i6-discovery-minimal.md §4）
        self.catalog = catalog

    # ------------------------------------------------------------------ 提交

    def submit(self, action: ActionDef, target: str, parameters: dict[str, Any],
               actor: str = "user:anonymous",
               idempotency_key: str | None = None,
               expected_version: int | None = None) -> dict[str, Any]:
        """执行一次动作提交。返回规范的 Result（§4）。"""

        # ---------------- 阶段 1：解析定义 ----------------
        # （定义由调用方传入；真实实现按 action_name 查注册表）

        record_id = self.store.new_record_id()
        ts = utcnow()

        # ---------------- 阶段 2：参数校验 ----------------
        # S-3：本阶段 MUST NOT 读取目标实例
        param_error = self._validate_parameters(action, parameters)
        if param_error:
            return self._reject(action, target, parameters, actor, record_id, ts,
                                stage="parameter", code=param_error[0],
                                violations=param_error[1])

        # ---------------- 阶段 3：目标解析 ----------------
        if not self.store.exists(target):
            return self._reject(action, target, parameters, actor, record_id, ts,
                                stage="target", code="TARGET_NOT_FOUND",
                                violations=[{
                                    "id": "TARGET",
                                    "message": f"目标实例 `{target}` 不存在",
                                    "actual": {},
                                }])

        # ---------------- 阶段 4：权限校验 ----------------
        # S-1：MUST 早于前置条件（否则会通过前置条件的报错泄露状态）
        if not self.authz.check(actor, action.permission_relation, target):
            return self._reject(
                action, target, parameters, actor, record_id, ts,
                stage="permission", code="PERMISSION_DENIED",
                violations=[{
                    "id": "PERMISSION",
                    "message": f"主体 `{actor}` 对 `{target}` 没有 "
                               f"`{action.permission_relation}` 权限",
                    "actual": {},
                }])

        # ---------------- 阶段 5：空转检查（幂等） ----------------
        key = idempotency_key or self._compute_idempotency_key(
            action, target, parameters)
        scope = Store.scope_key(action.qualified, target, key)
        cached = self.store.idempotent_lookup(scope)
        if cached is not None:
            result = dict(cached)
            result["idempotent_replay"] = True
            return result

        # ---------------- 阶段 6~9：同一事务（A-1） ----------------
        with self.store.transaction():

            # A-2 / R-5：先取读快照，本次提交的所有读都基于它
            read_snapshot = self.store.current_snapshot()

            # ---- v0.2：解析附属目标（同一快照，保证 A-2）----
            resolved: dict[str, str] = {"default": target}
            for spec in action.extra_targets:
                node, missing = target, None
                for rel in spec.via:
                    nxt = self.store.get_one(node, rel, read_snapshot)
                    if nxt is None:
                        missing = (node, rel)
                        break
                    node = nxt
                if missing is not None:
                    v = [{
                        "id": "TARGET",
                        "message": f"附属目标 `{spec.name}` 无法解析："
                                   f"`{missing[0]}` 上没有关系 `{missing[1]}`",
                        "actual": {"via": spec.via},
                    }]
                    result = self._reject(
                        action, target, parameters, actor, record_id, ts,
                        stage="target", code="AUX_TARGET_UNRESOLVED",
                        violations=v, snapshot=read_snapshot, commit=False)
                    self.store.write_audit(self._audit_row(
                        action, target, parameters, actor, record_id, ts,
                        outcome="rejected", stage="target",
                        code="AUX_TARGET_UNRESOLVED", violations=v,
                        snapshot=read_snapshot, applied=[],
                        before_version=None, after_version=None))
                    return result
                resolved[spec.name] = node

            view = TargetView(self.store, self.model, target,
                              action.target_concept, read_snapshot)
            # I4 v0.2 §2.3：缺失的可选参数绑定为 null（而不是"未定义"），
            # 使表达式能用 `is null` 显式检查
            ctx = {p.name: parameters.get(p.name) for p in action.parameters}
            ctx["target"] = view
            for spec in action.extra_targets:
                ctx[spec.name] = TargetView(
                    self.store, self.model, resolved[spec.name],
                    spec.concept, read_snapshot)
            ctx["actor"] = actor
            ctx["NOW"] = ts          # E-4：一次提交内恒定

            # ---------------- 阶段 6：前置条件 ----------------
            violations = []
            missing_optional = sorted(
                p.name for p in action.parameters
                if not p.required and parameters.get(p.name) is None)
            for pre in action.preconditions:
                try:
                    ok = evaluate(compile_expr(pre.expression),
                                  DictResolver(ctx))
                except ExpressionError as e:
                    violations.append({
                        "id": pre.id,
                        "message": f"前置条件 `{pre.id}` 无法求值: {e}",
                        "expression": pre.expression,
                        "actual": {},
                    })
                    continue
                if ok is not True:
                    v = {
                        "id": pre.id,
                        "message": pre.message,
                        "expression": pre.expression,
                    }
                    if view.reads:
                        v["actual"] = dict(view.reads)
                    if missing_optional:
                        # null 参与求值 → 判为未通过（而不是静默放行）
                        v["null_parameters"] = missing_optional
                    violations.append(v)

            if violations:
                # 拒绝：无任何变更。记录在本事务外（规范 R-2）
                result = self._reject(
                    action, target, parameters, actor, record_id, ts,
                    stage="precondition", code="PRECONDITION_FAILED",
                    violations=violations, snapshot=read_snapshot,
                    commit=False)
                self.store.write_audit(self._audit_row(
                    action, target, parameters, actor, record_id, ts,
                    outcome="rejected", stage="precondition",
                    code="PRECONDITION_FAILED", violations=violations,
                    snapshot=read_snapshot, applied=[],
                    before_version=self.store.get_version(target),
                    after_version=None))
                return result

            # ---------------- 阶段 7：并发检查 ----------------
            before_version = self.store.get_version(target)
            if expected_version is not None and expected_version != before_version:
                result = self._reject(
                    action, target, parameters, actor, record_id, ts,
                    stage="conflict", code="VERSION_CONFLICT",
                    violations=[{
                        "id": "VERSION",
                        "message": f"期望版本 {expected_version}，"
                                   f"实际 {before_version}",
                        "actual": {"expected": expected_version,
                                   "actual": before_version},
                    }],
                    snapshot=read_snapshot, commit=False)
                self.store.write_audit(self._audit_row(
                    action, target, parameters, actor, record_id, ts,
                    outcome="rejected", stage="conflict",
                    code="VERSION_CONFLICT",
                    violations=[{"id": "VERSION"}],
                    snapshot=read_snapshot, applied=[],
                    before_version=before_version, after_version=None))
                return result

            # ---------------- 阶段 8：应用效果 ----------------
            write_snapshot = self.store.bump_snapshot()
            applied = []
            written: dict[str, str] = {}        # 实例 → 概念（用于版本号）
            for eff in action.effects:
                try:
                    value = evaluate(compile_expr(eff.expression),
                                     DictResolver(ctx))
                except ExpressionError as e:
                    raise ActionError(
                        f"effect `{eff.path}` 求值失败: {e}") from e

                # v0.2：效果可作用于附属目标
                inst = resolved[eff.on]
                if eff.on == "default":
                    eff_concept = action.target_concept
                else:
                    eff_concept = next(t.concept for t in action.extra_targets
                                       if t.name == eff.on)

                rel = self.model.find_relation(eff_concept, eff.path)
                vc = rel.value_concept
                is_entity = (vc and self.model.has_concept(vc)
                             and self.model.concept(vc).is_entity)

                if is_entity:
                    obj, kind = str(value), "instance"
                else:
                    obj, kind = _literal(value), "literal"

                # I2-G1：写入路径上强制 multiplicity 约束
                single_valued = rel.multiplicity in ("ManyToOne", "OneToOne")

                self.store.set_fact(
                    inst, eff.path, obj, kind, write_snapshot,
                    single_valued=single_valued,
                    source=f"action:{action.qualified_versioned}")

                written[inst] = eff_concept
                applied.append({
                    "on": eff.on,
                    "instance": inst,
                    "path": eff.path,
                    "value": value if not is_entity else str(value),
                    "multiplicity": rel.multiplicity or "unconstrained",
                })

            # v0.2：所有被写入的实例都升版本（原子性覆盖全部目标）
            versions = {}
            for inst in sorted(written):
                versions[inst] = self.store.bump_version(inst)
            after_version = versions.get(target, self.store.get_version(target))

            # ---------------- 阶段 9：写审计（R-1，同事务） ----------------
            self.store.write_audit(self._audit_row(
                action, target, parameters, actor, record_id, ts,
                outcome="succeeded", stage=None, code=None, violations=[],
                snapshot=read_snapshot, applied=applied,
                before_version=before_version, after_version=after_version))

            # ---------------- 阶段 10：返回结果 ----------------
            result = {
                "outcome": "succeeded",
                "action": action.qualified_versioned,
                "target": target,
                "targets": resolved,
                "record_id": record_id,
                "applied": applied,
                "new_version": after_version,
                "versions": versions,
                "snapshot": read_snapshot,
            }

            # 幂等存入同一事务 —— 保证"结果可重放"与"效果已生效"一致
            self.store.idempotent_store(scope, record_id, result)
            return result

    # ------------------------------------------------------------------ 内部

    def _validate_parameters(self, action: ActionDef,
                             params: dict[str, Any]) -> tuple[str, list] | None:
        defined = {p.name for p in action.parameters}
        unknown = set(params) - defined
        if unknown:
            return ("UNKNOWN_PARAMETER", [{
                "id": "PARAM",
                "message": f"未定义的参数: {', '.join(sorted(unknown))}",
                "actual": {"unknown": sorted(unknown)},
            }])

        for p in action.parameters:
            if p.required and p.name not in params:
                return ("MISSING_REQUIRED_PARAMETER", [{
                    "id": "PARAM",
                    "message": f"缺少必填参数 `{p.name}`",
                    "actual": {"missing": p.name},
                }])
            if p.name in params:
                value = params[p.name]
                if not _type_matches(value, p.type, self.model):
                    return ("PARAMETER_TYPE_MISMATCH", [{
                        "id": "PARAM",
                        "message": f"参数 `{p.name}` 的类型应为 `{p.type}`，"
                                   f"实为 {type(value).__name__}",
                        "actual": {p.name: value},
                    }])
                for c in p.constraints:
                    try:
                        ok = evaluate(compile_expr(c),
                                      DictResolver(dict(params)))
                    except ExpressionError as e:
                        return ("CONSTRAINT_EVAL_ERROR", [{
                            "id": "PARAM",
                            "message": f"参数 `{p.name}` 的约束 `{c}` 无法求值: {e}",
                            "actual": {},
                        }])
                    if ok is not True:
                        return ("PARAMETER_CONSTRAINT_VIOLATED", [{
                            "id": "PARAM",
                            "message": f"参数 `{p.name}` 违反约束 `{c}`",
                            "expression": c,
                            "actual": {p.name: value},
                        }])
        return None

    def _compute_idempotency_key(self, action: ActionDef, target: str,
                                 params: dict[str, Any]) -> str:
        view = TargetView(self.store, self.model, target,
                          action.target_concept, self.store.current_snapshot())
        ctx = dict(params)
        ctx["target"] = view
        try:
            return _literal(evaluate(compile_expr(action.idempotency_key),
                                     DictResolver(ctx)))
        except ExpressionError:
            return json.dumps(params, sort_keys=True, ensure_ascii=False)

    def _reject(self, action: ActionDef, target: str, params: dict,
                actor: str, record_id: str, ts: str, *, stage: str,
                code: str, violations: list, snapshot: int | None = None,
                commit: bool = True) -> dict[str, Any]:
        result = {
            "outcome": "rejected",
            "stage": stage,
            "code": code,
            "action": action.qualified_versioned,
            "target": target,
            "violations": violations,
            "suggestions": self._suggestions(stage, action, target, actor),
            "retryable": stage == "conflict",
            "record_id": record_id,
        }
        if commit:
            # 早期阶段的拒绝：此时尚未开启主事务，直接记审计（R-2）
            self.store.write_audit(self._audit_row(
                action, target, params, actor, record_id, ts,
                outcome="rejected", stage=stage, code=code,
                violations=violations, snapshot=snapshot, applied=[],
                before_version=None, after_version=None))
        return result

    def _suggestions(self, stage: str, action: ActionDef, target: str,
                     actor: str) -> list[dict]:
        """
        替代动作建议。

        **I4 v0.2 §4.2（解决原 I4-min 的发现 4）**：
        替代动作建议的职责归 **I6**，不归 I4。

        - 若未注入 catalog → 返回空列表（规范 F-7：调用方 MUST NOT 依赖它存在）
        - 若已注入 → 调 `FindByCapability` 查**同一概念上的其他动作**，
          并**标注来源**（F-8）
        """
        if self.catalog is None:
            return []
        # 只有"前置条件失败"和"权限失败"才值得找替代动作；
        # 参数写错、目标不存在、版本冲突都应先修正原动作
        if stage not in ("precondition", "permission"):
            return []
        need = action.description or action.name
        try:
            matches = self.catalog.find_by_capability(
                need, actor=actor, concept=action.target_concept, limit=6)
        except Exception:
            return []
        out = []
        for m in matches:
            if m["qualified"] == action.qualified:
                continue                      # 排除自己
            out.append({
                "action": m["qualified"],
                "reason": m.get("description") or "",
                "score": m["score"],
                "matched_on": m["matched_on"],
                "via": "i6.FindByCapability",      # F-8：必须标注来源
            })
            if len(out) == 3:
                break
        return out

    def _audit_row(self, action: ActionDef, target: str, params: dict,
                   actor: str, record_id: str, ts: str, *, outcome: str,
                   stage: str | None, code: str | None, violations: list,
                   snapshot: int | None, applied: list,
                   before_version: int | None,
                   after_version: int | None) -> dict[str, Any]:
        return {
            "record_id": record_id,
            "ts": ts,
            "action": action.qualified,
            "action_version": action.version,
            "definition_hash": action.definition_hash,      # R-4
            "target": target,
            "parameters": params,
            "actor": {"id": actor},
            "outcome": outcome,
            "stage": stage,
            "code": code,
            "violations": violations,
            "snapshot": snapshot,                            # R-5
            "read_concepts": action.reads,
            "applied": applied,
            "before_version": before_version,
            "after_version": after_version,
            "trace_id": record_id,
        }


# --------------------------------------------------------------------------
# 工具
# --------------------------------------------------------------------------

def _literal(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _type_matches(value: Any, concept: str, model: OssieModel) -> bool:
    """按 Ossie 的 extends 链判断参数值是否符合声明的值类型。"""
    chain = {concept, *model.all_supertypes(concept)}
    if "String" in chain:
        return isinstance(value, str)
    if "Integer" in chain:
        return isinstance(value, int) and not isinstance(value, bool)
    if "Float" in chain or "Decimal" in chain:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if "Boolean" in chain:
        return isinstance(value, bool)
    return True
