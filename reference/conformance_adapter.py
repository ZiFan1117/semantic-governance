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
