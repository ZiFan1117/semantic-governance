"""
一致性测试适配器 · 参考实现侧

把 reference/ 里的实现包装成 conformance/README.md 定义的 Adapter 协议。

用法：
    python conformance/run.py reference/conformance_adapter.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from engine import ActionEngine, ActionLoader, SimpleAuthz   # noqa: E402
from ossie_model import OssieModel                            # noqa: E402
from query import QueryEngine                                 # noqa: E402
from store import Store                                       # noqa: E402
from discovery import ActionRegistry, Catalog                 # noqa: E402


class Adapter:

    def __init__(self) -> None:
        self.store = Store(":memory:")
        self.model: OssieModel | None = None
        self.registry = ActionRegistry()
        self.authz = SimpleAuthz()
        self.catalog: Catalog | None = None
        self.engine: ActionEngine | None = None
        # 注意：不能叫 self.query —— 会和 Adapter.query 方法名冲突
        self.qe: QueryEngine | None = None
        # 初始装载的动作定义原文。reset() 会用它重建注册表 ——
        # 否则用例中途 load_action 加载的探针定义会污染后续用例。
        self._loaded: list[str] = []
        self._baseline: list[str] | None = None

    # ------------------------------------------------------------ 装载

    def load_ontology(self, yaml_text: str) -> None:
        import yaml
        self.model = OssieModel.from_dict(yaml.safe_load(yaml_text))
        self.qe = QueryEngine(self.model, self.store)

    def load_action(self, yaml_text: str) -> None:
        import yaml
        tmp = _HERE / "_conformance_tmp_action.yaml"
        tmp.write_text(yaml_text, encoding="utf-8")
        try:
            a = ActionLoader.load(tmp, self.model)
        finally:
            tmp.unlink(missing_ok=True)
        self.registry.register(a)
        self._loaded.append(yaml_text)

    def reset(self) -> None:
        """
        清空事实与授权，**并把动作注册表恢复到基线**。

        协议要求：reset 后的状态必须等同于"刚 load 完本体与动作"。

        基线在**首次调用 reset 时**捕获 —— 此时 runner 已完成初始装载，
        尚未执行任何会中途 load_action 的用例。
        """
        if self._baseline is None:
            self._baseline = list(self._loaded)

        self.store.close()
        self.store = Store(":memory:")
        self.authz = SimpleAuthz()
        self.registry = ActionRegistry()
        for text in self._baseline:
            tmp = _HERE / "_conformance_reset_tmp.yaml"
            tmp.write_text(text, encoding="utf-8")
            try:
                self.registry.register(ActionLoader.load(tmp, self.model))
            finally:
                tmp.unlink(missing_ok=True)
        self.catalog = Catalog(self.model, self.registry)
        self.engine = ActionEngine(self.model, self.store, self.authz,
                                   catalog=self.catalog)
        self.qe = QueryEngine(self.model, self.store)

    # ------------------------------------------------------------ 授权

    def grant(self, subject: str, relation: str, obj: str) -> None:
        self.authz.grant(subject, relation, obj)

    # ------------------------------------------------------------ 事实

    def seed(self, facts: list[dict]) -> None:
        with self.store.transaction():
            tx = self.store.bump_snapshot()
            for f in facts:
                if f.get("concept"):
                    self.store.set_concept(f["subject"], f["concept"], tx,
                                           source="conformance")
                self.store.set_fact(
                    f["subject"], f["relation"], f["object"],
                    f.get("kind", "literal"), tx,
                    single_valued=f.get("single_valued", True),
                    source="conformance")

    # ------------------------------------------------------------ I4

    def submit(self, action: str, target: str, params: dict,
               actor: str, **kw) -> dict:
        a = self.registry.get(action)
        return self.engine.submit(a, target, params, actor=actor, **kw)

    def action_qualified(self, short: str) -> str:
        for a in self.registry.all():
            if a.name == short:
                return a.qualified
        raise KeyError(short)

    # ------------------------------------------------------------ I3

    def query(self, **kw) -> dict:
        return self.qe.query(**self._with_actor(kw))

    def infer(self, **kw) -> dict:
        return self.qe.infer(**self._with_actor(kw))

    def traverse(self, start: str, path: list[str], **kw) -> dict:
        return self.qe.traverse(start, path, **self._with_actor(kw))

    def search(self, text: str, **kw) -> dict:
        return self.qe.search(text, **self._with_actor(kw))

    @staticmethod
    def _with_actor(kw: dict) -> dict:
        kw.setdefault("actor", "user:conformance")
        return kw

    # ------------------------------------------------------------ I6

    def list_concepts(self, **kw) -> list:
        return self.catalog.list_concepts(**self._with_actor(kw))

    def list_actions(self, concept: str | None = None) -> list:
        return self.catalog.list_actions(actor="user:conformance",
                                         concept=concept)

    def describe_action(self, qualified: str) -> dict:
        return self.catalog.describe_action(qualified,
                                            actor="user:conformance")

    def find_by_capability(self, need: str, **kw) -> list:
        return self.catalog.find_by_capability(
            need, **self._with_actor(kw))

    # ------------------------------------------------------------ E（五要素）
    #
    # 供一致性套件的 E 组使用。协议见 conformance/README.md。
    # 这四个方法只读"装载进来的声明"，不涉及运行时状态。

    #: 规则在 Ossie 契约文件里的两种声明形态（框架 §5）。
    RULE_FORMS = ("requires", "derived_by")

    def _iter_rules(self):
        """产出 (规则所有者, 形态列表)。规则可挂在对象上，也可挂在关系上。"""
        m = self.model
        if m is None:
            return
        for cname, c in m.concepts.items():
            forms = [k for k in self.RULE_FORMS if getattr(c, k, None)]
            if forms:
                yield cname, forms
            for rel in c.relationships:
                rforms = [k for k in self.RULE_FORMS if getattr(rel, k, None)]
                if rforms:
                    yield rel.qualified, rforms

    def declared_rules(self) -> list[dict]:
        """全部规则声明及其形态（`requires` / `derived_by`），只读。"""
        return [{"target": owner, "forms": forms}
                for owner, forms in self._iter_rules()]

    def declared_strategies(self) -> list[dict]:
        """
        本实现**不支持策略要素**（框架 §5 的五要素之一，Ossie 无载体）。

        返回空列表 = 未声明策略。按框架 `E-4`~`E-6` 的条件式写法，
        **未声明策略是合法状态**，因此 E 组的策略类用例自动免除。
        """
        return []

    def carrier_audit(self) -> list[str]:
        """
        扫描装载进来的本体，报告五要素之外的声明载体键。

        直接复用 `OssieModel` 在解析时对未支持字段的记录 —— 不另立白名单，
        避免"审核标准"与"解析器支持范围"变成两处真源。
        """
        m = self.model
        if m is None:
            return []
        return [f"{u.where}: {u.field}" for u in m.unsupported]
