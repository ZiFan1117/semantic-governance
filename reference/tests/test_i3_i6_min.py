"""
I3-min / I6-min / I4 v0.2 一致性测试套件

验证：
    spec/i3-query-minimal.md
    spec/i6-discovery-minimal.md
    spec/i4-action-minimal.md v0.2（多实例事务、null 语义、suggestions 移交 I6）

运行：
    python reference/tests/test_i3_i6_min.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REF = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REF))

from discovery import ActionRegistry, Catalog, allow_all   # noqa: E402
from engine import (ActionEngine, ActionLoader, ActionError,  # noqa: E402
                    SimpleAuthz)
from ossie_model import OssieModel                          # noqa: E402
from query import (DerivationLimitExceeded, QueryEngine,    # noqa: E402
                   UnsupportedDerivation, parse_derived_by)
from store import Store                                     # noqa: E402

EXAMPLES = REF / "examples"
NS = "urn:sem:acme:supply"
C1, C2, C3, C4 = (f"{NS}:Customer:{n}" for n in ("g", "a", "b", "c"))
O1 = f"{NS}:Order:12345"
ACTOR = "user:anne"


def build_model() -> OssieModel:
    return OssieModel.from_file(EXAMPLES / "ontology.ossie.yaml")


def build_registry(model: OssieModel) -> ActionRegistry:
    reg = ActionRegistry()
    for f in sorted((EXAMPLES / "actions").glob("*.yaml")):
        reg.register(ActionLoader.load(f, model))
    return reg


class Base(unittest.TestCase):

    def setUp(self) -> None:
        self.model = build_model()
        self.registry = build_registry(self.model)
        self.store = Store(":memory:")
        self._seed()
        self.query = QueryEngine(self.model, self.store)
        self.catalog = Catalog(self.model, self.registry)
        self.authz = SimpleAuthz()
        self.engine = ActionEngine(self.model, self.store, self.authz,
                                   catalog=self.catalog)

    def tearDown(self) -> None:
        self.store.close()

    def _seed(self) -> None:
        """股权链 g → a → b → c，外加两个订单。"""
        with self.store.transaction():
            tx = self.store.bump_snapshot()
            for i, c in enumerate((C1, C2, C3, C4)):
                self.store.set_concept(c, "Customer", tx, source="seed")
                self.store.set_fact(c, "cid", f"c{i}", "literal", tx,
                                    single_valued=True, source="seed")
                self.store.set_fact(c, "risk_flag", "low", "literal", tx,
                                    single_valued=True, source="seed")
            for a, b in ((C1, C2), (C2, C3), (C3, C4)):
                self.store.set_fact(a, "holds", b, "instance", tx,
                                    single_valued=False, source="seed")
            for o, cust in ((O1, C1),):
                self.store.set_concept(o, "Order", tx, source="seed")
                for rel, val in (("nr", "12345"), ("status", "pending"),
                                 ("paid_amount", "100.0")):
                    self.store.set_fact(o, rel, val, "literal", tx,
                                        single_valued=True, source="seed")
                self.store.set_fact(o, "customer", cust, "instance", tx,
                                    single_valued=True, source="seed")

    def action(self, name: str):
        return self.registry.get(f"{NS}:{name}")


# ==========================================================================
# I3 · 派生
# ==========================================================================

class TestDerivation(Base):

    def test_base_case(self):
        """基础情形：直接持股也属于穿透持股。"""
        items = self.query.infer(relation="holds_transitively")["items"]
        pairs = {(i["subject"], i["object"]) for i in items}
        self.assertIn((C1, C2), pairs)
        cases = {i["via"]["case"] for i in items
                 if (i["subject"], i["object"]) == (C1, C2)}
        self.assertEqual(cases, {0}, "直接持股应由 case#0 推出")

    def test_fixpoint_recursive(self):
        """D-1：必须推到不动点。链长 4 → 应有 6 条传递事实。"""
        items = self.query.infer(relation="holds_transitively")["items"]
        self.assertEqual(len(items), 6, "4 个节点的链，闭包应有 6 条")
        pairs = {(i["subject"], i["object"]) for i in items}
        self.assertIn((C1, C4), pairs, "链首必须能到达链尾（需 2 轮迭代）")

    def test_via_recursive_case_marked(self):
        """C1 ⇒ C4 必须标为递归情形（case#1）。"""
        items = self.query.infer(relation="holds_transitively")["items"]
        target = [i for i in items if (i["subject"], i["object"]) == (C1, C4)]
        self.assertEqual(len(target), 1)
        self.assertEqual(target[0]["via"]["case"], 1)
        self.assertEqual(len(target[0]["via"]["premises"]), 2)

    def test_via_premises_are_real(self):
        """规范 §7-2：via.premises 里的前提必须真实存在。"""
        items = self.query.infer(relation="holds_transitively")["items"]
        stored = {(i["subject"], i["relation"], i["object"])
                  for i in self.query.query()["items"]}
        derived_pairs = {(i["subject"], i["relation"], i["object"])
                         for i in items}
        for item in items:
            for p in item["via"]["premises"]:
                key = (p["subject"], p["relation"], p["object"])
                self.assertTrue(
                    key in stored or key in derived_pairs,
                    f"前提 {key} 既不在存储里也不是派生事实")

    def test_D2_derived_not_persisted(self):
        """D-2：派生事实不落库。"""
        self.query.infer(relation="holds_transitively")
        stored = self.query.query(relation="holds_transitively")
        self.assertEqual(stored["budget"]["total"], 0)

    def test_Q3_deterministic_order(self):
        a = self.query.infer(relation="holds_transitively")["items"]
        b = self.query.infer(relation="holds_transitively")["items"]
        self.assertEqual([(i["subject"], i["object"]) for i in a],
                         [(i["subject"], i["object"]) for i in b])

    def test_Q1_truncation_is_explicit(self):
        r = self.query.infer(relation="holds_transitively", max_items=2)
        self.assertEqual(r["budget"]["returned"], 2)
        self.assertEqual(r["budget"]["total"], 6)
        self.assertTrue(r["truncated"])

    def test_Q1_no_false_truncation(self):
        r = self.query.infer(relation="holds_transitively", max_items=100)
        self.assertFalse(r["truncated"])

    def test_D3_unsupported_expression_rejected(self):
        """D-3：不支持的 derived_by 形式必须报错，不得静默当空结果。"""
        raw = {
            "name": "bad",
            "ontology": [
                {"concept": "A", "type": "EntityType", "relationships": [
                    {"name": "r", "roles": [{"concept": "A", "name": "x"}],
                     "derived_by": ["A.files AND A.earns > 100"]}]},
            ],
        }
        m = OssieModel.from_dict(raw)
        with self.assertRaises(UnsupportedDerivation):
            parse_derived_by(m)

    def test_D3_non_path_expression_rejected(self):
        raw = {
            "name": "bad",
            "ontology": [
                {"concept": "A", "type": "EntityType", "relationships": [
                    {"name": "r", "roles": [{"concept": "A", "name": "x"}],
                     "derived_by": ["whatever"]}]},
            ],
        }
        m = OssieModel.from_dict(raw)
        with self.assertRaises(UnsupportedDerivation):
            parse_derived_by(m)

    def test_D4_iteration_limit_is_declared(self):
        from query import MAX_ITERATIONS
        self.assertGreater(MAX_ITERATIONS, 0)
        self.assertTrue(hasattr(sys.modules["query"], "DerivationLimitExceeded"))

    def test_T2_cycle_terminates(self):
        """T-2：含环的图必须终止遍历。"""
        with self.store.transaction():
            tx = self.store.bump_snapshot()
            self.store.set_fact(C4, "holds", C1, "instance", tx,
                                single_valued=False, source="cycle")
        r = self.query.traverse(C1, ["holds"], max_depth=20)
        self.assertEqual(len(r["items"]), 3, "环上只能到达另外 3 个节点")

    def test_T3_traverse_returns_path(self):
        r = self.query.traverse(C1, ["holds"], max_depth=3)
        deepest = max(r["items"], key=lambda i: i["hops"])
        self.assertEqual(deepest["hops"], 3)
        self.assertEqual(len(deepest["path"]), 3)

    def test_S1_search_marks_field(self):
        r = self.query.search("12345")
        self.assertTrue(r["items"])
        self.assertIn("matched_field", r["items"][0])

    def test_Q2_snapshot_recorded(self):
        r = self.query.query()
        self.assertIn("snapshot", r)
        self.assertIsInstance(r["snapshot"], int)


# ==========================================================================
# I6 · 发现
# ==========================================================================

class TestDiscovery(Base):

    def test_G1_enumerates_all_concepts(self):
        got = {c["name"] for c in self.catalog.list_concepts()}
        self.assertEqual(got, set(self.model.concepts))

    def test_list_concepts_kind_filter(self):
        ent = self.catalog.list_concepts(kind="EntityType")
        self.assertEqual({c["name"] for c in ent}, {"Customer", "Order"})
        val = self.catalog.list_concepts(kind="ValueType")
        self.assertNotIn("Order", {c["name"] for c in val})

    def test_get_concept_detail(self):
        d = self.catalog.get_concept_detail("Order")
        self.assertEqual(d["type"], "EntityType")
        self.assertIn("nr", d["identify_by"])
        names = {r["name"] for r in d["relationships"]}
        self.assertIn("status", names)
        self.assertIn("customer", names)

    def test_list_actions_by_concept(self):
        acts = self.catalog.list_actions(concept="Order")
        self.assertEqual(len(acts), 3)
        self.assertTrue(all(a["target_concept"] == "Order" for a in acts))

    def test_E2_describe_action_is_complete(self):
        """E-2：DescribeAction 必须返回足以构造提交请求的完整契约。"""
        d = self.catalog.describe_action(f"{NS}:cancel_order")
        for key in ("qualified", "version", "target", "parameters",
                    "permissions", "preconditions", "effects", "idempotency"):
            self.assertIn(key, d, f"缺少 `{key}`")
        self.assertTrue(d["parameters"])
        self.assertTrue(d["preconditions"])
        self.assertTrue(d["effects"])

    def test_describe_unknown_action_raises(self):
        with self.assertRaises(KeyError):
            self.catalog.describe_action(f"{NS}:nope")

    def test_F3_matched_on_present(self):
        res = self.catalog.find_by_capability("退货")
        self.assertTrue(res)
        for r in res:
            self.assertIn("matched_on", r)
            self.assertTrue(r["matched_on"])

    def test_F_ranking_puts_relevant_first(self):
        """退货相关的查询，return_order 必须排第一。"""
        res = self.catalog.find_by_capability("订单已发货要退货")
        self.assertTrue(res)
        self.assertEqual(res[0]["qualified"], f"{NS}:return_order")

    def test_F_ranking_cancel_query(self):
        res = self.catalog.find_by_capability("取消订单")
        self.assertEqual(res[0]["qualified"], f"{NS}:cancel_order")

    def test_F6_no_match_returns_empty(self):
        """F-6：无匹配必须返回空列表，不得兜底。"""
        res = self.catalog.find_by_capability("完全不相关的需求xyzzy")
        self.assertEqual(res, [])

    def test_F1_concept_filter(self):
        res = self.catalog.find_by_capability("订单", concept="Customer")
        self.assertEqual(res, [], "按 Customer 过滤不应返回 Order 的动作")

    def test_G4_deterministic(self):
        a = self.catalog.find_by_capability("订单")
        b = self.catalog.find_by_capability("订单")
        self.assertEqual([x["qualified"] for x in a],
                         [x["qualified"] for x in b])

    def test_G5_no_side_effects(self):
        before = self.store.stats().copy()
        self.catalog.list_concepts()
        self.catalog.list_actions()
        self.catalog.find_by_capability("订单")
        self.assertEqual(self.store.stats(), before)

    def test_G2_permission_filter_applied(self):
        """G2：过滤器必须生效。"""
        cat = Catalog(self.model, self.registry,
                      visible=lambda actor, concept: concept != "Customer")
        self.assertNotIn("Customer",
                         {c["name"] for c in cat.list_concepts()})


# ==========================================================================
# I4 v0.2 · 多实例事务
# ==========================================================================

class TestMultiInstance(Base):

    def test_atomic_write_across_instances(self):
        self.authz.grant(ACTOR, "can_flag", O1)
        r = self.engine.submit(self.action("flag_order"), O1,
                               {"reason": "fraud"}, actor=ACTOR)
        self.assertEqual(r["outcome"], "succeeded")
        self.assertEqual(self.store.get_one(O1, "status"), "flagged")
        self.assertEqual(self.store.get_one(C1, "risk_flag"), "high")

    def test_both_instances_get_version_bump(self):
        self.authz.grant(ACTOR, "can_flag", O1)
        r = self.engine.submit(self.action("flag_order"), O1,
                               {"reason": "fraud"}, actor=ACTOR)
        self.assertEqual(r["versions"][O1], 1)
        self.assertEqual(r["versions"][C1], 1)
        self.assertEqual(self.store.get_version(O1), 1)
        self.assertEqual(self.store.get_version(C1), 1)

    def test_aux_target_resolution_recorded(self):
        self.authz.grant(ACTOR, "can_flag", O1)
        r = self.engine.submit(self.action("flag_order"), O1,
                               {"reason": "fraud"}, actor=ACTOR)
        self.assertEqual(r["targets"]["default"], O1)
        self.assertEqual(r["targets"]["customer"], C1)

    def test_aux_target_precondition_uses_aux_state(self):
        """附属目标的属性可以参与前置条件。"""
        self.authz.grant(ACTOR, "can_flag", O1)
        with self.store.transaction():
            tx = self.store.bump_snapshot()
            self.store.set_fact(C1, "risk_flag", "high", "literal", tx,
                                single_valued=True, source="test")
        r = self.engine.submit(self.action("flag_order"), O1,
                               {"reason": "fraud"}, actor=ACTOR)
        self.assertEqual(r["outcome"], "rejected")
        ids = {v["id"] for v in r["violations"]}
        self.assertIn("F2", ids)

    def test_atomicity_rolls_back_both(self):
        """A-1/A-4 扩展到全部目标：一个效果失败，两个都不得生效。"""
        self.authz.grant(ACTOR, "can_flag", O1)
        orig = self.store.set_fact
        n = {"i": 0}

        def flaky(*a, **kw):
            n["i"] += 1
            if n["i"] == 2:
                raise RuntimeError("模拟故障")
            return orig(*a, **kw)

        self.store.set_fact = flaky
        with self.assertRaises(RuntimeError):
            self.engine.submit(self.action("flag_order"), O1,
                               {"reason": "fraud"}, actor=ACTOR)
        self.assertEqual(self.store.get_one(O1, "status"), "pending")
        self.assertEqual(self.store.get_one(C1, "risk_flag"), "low")

    def test_aux_target_unresolvable_is_rejected(self):
        """附属目标解析不到 → 拒绝，stage=target。"""
        with self.store.transaction():
            tx = self.store.bump_snapshot()
            self.store.replace_fact(O1, "customer", "", "literal", tx)
            self.store.conn.execute(
                "UPDATE facts SET valid_to = ? WHERE subject = ? AND relation = ?",
                (tx, O1, "customer"))
        self.authz.grant(ACTOR, "can_flag", O1)
        r = self.engine.submit(self.action("flag_order"), O1,
                               {"reason": "fraud"}, actor=ACTOR)
        self.assertEqual((r["outcome"], r["stage"]),
                         ("rejected", "target"))
        self.assertEqual(r["code"], "AUX_TARGET_UNRESOLVED")


# ==========================================================================
# I4 v0.2 · YAML 键名陷阱
# ==========================================================================

class TestYamlOnKeyTrap(Base):
    """
    参考实现暴露的教训：
    YAML 1.1 把 `on` / `off` / `yes` / `no` 解析成布尔值，
    所以 `on: customer` 的**键名会丢失**（变成 True），字段静默消失。
    规范必须禁用 `on` 作为字段名。
    """

    def test_on_key_is_rejected_with_clear_message(self):
        import yaml
        raw = yaml.safe_load(
            (EXAMPLES / "actions" / "flag_order.action.yaml")
            .read_text(encoding="utf-8"))
        # 把 applies_to 改回 on（YAML 会解析成布尔键）
        for e in raw["action"]["effects"]:
            e["on"] = e.pop("applies_to")
        tmp = REF / "_tmp_on.yaml"
        tmp.write_text(yaml.safe_dump(raw, allow_unicode=True),
                       encoding="utf-8")
        try:
            with self.assertRaises(ActionError) as cm:
                ActionLoader.load(tmp, self.model)
            self.assertIn("applies_to", str(cm.exception))
            self.assertIn("布尔", str(cm.exception))
        finally:
            tmp.unlink(missing_ok=True)


# ==========================================================================
# I4 v0.2 · null 语义与 suggestions
# ==========================================================================

class TestNullSemantics(Base):

    def test_is_null_and_is_not_null(self):
        from expr import eval_expr
        self.assertTrue(eval_expr("x is null", {"x": None}))
        self.assertFalse(eval_expr("x is null", {"x": 1}))
        self.assertTrue(eval_expr("x is not null", {"x": 1}))
        self.assertFalse(eval_expr("x is not null", {"x": None}))

    def test_null_ordering_is_unknown_not_true(self):
        from expr import eval_expr
        self.assertIsNone(eval_expr("x < 5", {"x": None}))
        self.assertIsNone(eval_expr("x >= 0", {"x": None}))

    def test_null_equality_still_works(self):
        from expr import eval_expr
        self.assertTrue(eval_expr("x == null", {"x": None}))
        self.assertFalse(eval_expr("x == null", {"x": 1}))

    def test_is_with_non_null_operand_rejected(self):
        from expr import ExpressionError, eval_expr
        with self.assertRaises(ExpressionError):
            eval_expr("x is 5", {"x": 1})

    def test_missing_optional_param_binds_to_null(self):
        """缺失的可选参数绑定为 null，而不是"未定义变量"报错。"""
        import yaml
        raw = yaml.safe_load(
            (EXAMPLES / "actions" / "cancel_order.action.yaml")
            .read_text(encoding="utf-8"))
        a = raw["action"]
        a["parameters"][1]["required"] = False          # refund_amount 变可选
        # ⚠️ 必须**替换** P2，而不是追加 ——
        #    未做 null 防护的 P2 会因"null 的顺序比较 → 未知 → 不通过"而失败。
        #    这正是规范 §2.3 的"默认拒绝"语义：要用可选参数，必须显式 is null 守卫。
        a["preconditions"][1] = {
            "id": "P2",
            "expression": "refund_amount is null or refund_amount <= target.paid_amount",
            "message": "退款金额必须为空或不超过已付金额",
        }
        tmp = REF / "_tmp_opt.yaml"
        tmp.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
        try:
            act = ActionLoader.load(tmp, self.model)
        finally:
            tmp.unlink(missing_ok=True)

        self.authz.grant(ACTOR, "can_cancel", O1)
        r = self.engine.submit(act, O1, {"reason": "x"}, actor=ACTOR)
        self.assertEqual(r["outcome"], "succeeded",
                         "可选参数缺失时 P3 应因 is null 而通过")

    def test_rejection_reports_null_parameters(self):
        import yaml
        raw = yaml.safe_load(
            (EXAMPLES / "actions" / "cancel_order.action.yaml")
            .read_text(encoding="utf-8"))
        a = raw["action"]
        a["parameters"][1]["required"] = False
        a["preconditions"][1] = {
            "id": "P2", "expression": "refund_amount <= target.paid_amount",
            "message": "退款金额不能超过已付金额"}
        tmp = REF / "_tmp_opt2.yaml"
        tmp.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
        try:
            act = ActionLoader.load(tmp, self.model)
        finally:
            tmp.unlink(missing_ok=True)

        self.authz.grant(ACTOR, "can_cancel", O1)
        r = self.engine.submit(act, O1, {"reason": "x"}, actor=ACTOR)
        self.assertEqual(r["outcome"], "rejected")
        self.assertIn("null_parameters", r["violations"][0])


class TestSuggestionsViaI6(Base):

    def test_suggestions_come_from_i6_and_are_attributed(self):
        """F-8：内联 I6 结果时必须标注来源。"""
        self.authz.grant(ACTOR, "can_cancel", O1)
        with self.store.transaction():
            tx = self.store.bump_snapshot()
            self.store.set_fact(O1, "status", "shipped", "literal", tx,
                                single_valued=True, source="test")
        r = self.engine.submit(self.action("cancel_order"), O1,
                               {"reason": "x", "refund_amount": 1.0},
                               actor=ACTOR)
        self.assertEqual(r["stage"], "precondition")
        self.assertTrue(r["suggestions"], "应给出替代动作建议")
        for s in r["suggestions"]:
            self.assertEqual(s["via"], "i6.FindByCapability")

    def test_F7_suggestions_may_be_empty_when_no_catalog(self):
        """F-7：未接入 I6 时 suggestions 可以为空，调用方不得依赖它。"""
        engine = ActionEngine(self.model, self.store, self.authz)   # 无 catalog
        engine.authz.grant(ACTOR, "can_cancel", O1)
        with self.store.transaction():
            tx = self.store.bump_snapshot()
            self.store.set_fact(O1, "status", "shipped", "literal", tx,
                                single_valued=True, source="test")
        r = engine.submit(self.action("cancel_order"), O1,
                          {"reason": "x", "refund_amount": 1.0}, actor=ACTOR)
        self.assertEqual(r["suggestions"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
