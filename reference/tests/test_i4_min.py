"""
I4-min 一致性测试套件

验证 spec/i4-action-minimal.md 的：
  · §6 全部 MUST / MUST NOT 条款
  · §8 的 9 条验收样本集

运行：
    python -m unittest discover -s reference/tests -v
或：
    python reference/tests/test_i4_min.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REF = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REF))

from engine import (ActionEngine, ActionLoader, ActionError,   # noqa: E402
                    SimpleAuthz)
from ossie_model import OssieError, OssieModel                  # noqa: E402
from store import Fact, Store                                   # noqa: E402

EXAMPLES = REF / "examples"
ONTOLOGY = EXAMPLES / "ontology.ossie.yaml"
ACTION = EXAMPLES / "actions" / "cancel_order.action.yaml"

NS = "urn:sem:acme:supply"
O1 = f"{NS}:Order:12345"        # pending, paid 100
O2 = f"{NS}:Order:67890"        # shipped, paid 250
ACTOR = "user:anne"

GOOD = {"reason": "customer_request", "refund_amount": 50.0}


class Base(unittest.TestCase):
    """每个测试一套全新的 本体 + 存储 + 引擎。"""

    def setUp(self) -> None:
        self.model = OssieModel.from_file(ONTOLOGY)
        self.action = ActionLoader.load(ACTION, self.model)
        self.store = Store(":memory:")
        self.authz = SimpleAuthz()
        self.engine = ActionEngine(self.model, self.store, self.authz)
        self._seed()

    def tearDown(self) -> None:
        self.store.close()

    def _seed(self) -> None:
        with self.store.transaction():
            tx = self.store.bump_snapshot()
            for order, status, paid in ((O1, "pending", 100.0),
                                        (O2, "shipped", 250.0)):
                self.store.set_fact(order, "nr", order.rsplit(":", 1)[1],
                                    "literal", tx, single_valued=True,
                                    source="seed")
                self.store.set_fact(order, "status", status, "literal", tx,
                                    single_valued=True, source="seed")
                self.store.set_fact(order, "paid_amount", str(paid), "literal",
                                    tx, single_valued=True, source="seed")

    def grant(self, target: str) -> None:
        self.authz.grant(ACTOR, "can_cancel", target)

    def submit(self, target: str = O1, params: dict | None = None,
               **kw) -> dict:
        return self.engine.submit(self.action, target,
                                  dict(GOOD if params is None else params),
                                  actor=ACTOR, **kw)


# ==========================================================================
# 本体加载与自检（I1-2）
# ==========================================================================

class TestOssieModel(Base):

    def test_loads_all_concepts(self):
        self.assertEqual(
            set(self.model.concepts),
            {"Order", "Customer", "OrderNr", "CustomerId",
             "OrderStatus", "Money", "CancelReason", "RiskLevel"})
        self.assertTrue(self.model.concept("Order").is_entity)
        self.assertTrue(self.model.concept("Money").is_value)

    def test_subtype_is_transitive(self):
        self.assertTrue(self.model.is_subtype("OrderNr", "String"))

    def test_self_check_rejects_dangling_extends(self):
        raw = {"name": "bad", "ontology": [
            {"concept": "A", "type": "EntityType", "extends": ["Nope"]}]}
        with self.assertRaises(OssieError) as cm:
            OssieModel.from_dict(raw)
        self.assertIn("未声明", str(cm.exception))

    def test_self_check_rejects_cycle(self):
        raw = {"name": "bad", "ontology": [
            {"concept": "A", "type": "EntityType", "extends": ["B"]},
            {"concept": "B", "type": "EntityType", "extends": ["A"]}]}
        with self.assertRaises(OssieError) as cm:
            OssieModel.from_dict(raw)
        self.assertIn("环", str(cm.exception))

    def test_self_check_rejects_value_type_without_builtin(self):
        raw = {"name": "bad", "ontology": [
            {"concept": "V", "type": "ValueType"}]}
        with self.assertRaises(OssieError) as cm:
            OssieModel.from_dict(raw)
        self.assertIn("内置值类型", str(cm.exception))

    def test_self_check_rejects_bad_multiplicity(self):
        raw = {"name": "bad", "ontology": [
            {"concept": "A", "type": "EntityType", "relationships": [
                {"name": "r", "roles": [{"concept": "String"}],
                 "multiplicity": "Exactly3"}]}]}
        with self.assertRaises(OssieError) as cm:
            OssieModel.from_dict(raw)
        self.assertIn("multiplicity", str(cm.exception))


# ==========================================================================
# 定义校验（D-1 / D-2 / D-3）
# ==========================================================================

class TestActionDefinition(Base):

    def _load(self, mutate) -> ActionDef | None:
        import yaml
        raw = yaml.safe_load(ACTION.read_text(encoding="utf-8"))
        mutate(raw["action"])
        tmp = REF / "_tmp_action.yaml"
        tmp.write_text(yaml.safe_dump(raw, allow_unicode=True),
                       encoding="utf-8")
        try:
            return ActionLoader.load(tmp, self.model)
        finally:
            tmp.unlink(missing_ok=True)

    def test_D1_rejects_undeclared_target_concept(self):
        with self.assertRaises(ActionError) as cm:
            self._load(lambda a: a["target"].__setitem__("concept", "Nope"))
        self.assertIn("未在 Ossie 本体中声明", str(cm.exception))

    def test_D1_rejects_undeclared_parameter_type(self):
        def m(a):
            a["parameters"][0]["type"] = "NotAType"
        with self.assertRaises(ActionError) as cm:
            self._load(m)
        self.assertIn("未在 Ossie 本体中声明", str(cm.exception))

    def test_D2_rejects_empty_effects(self):
        with self.assertRaises(ActionError) as cm:
            self._load(lambda a: a.__setitem__("effects", []))
        self.assertIn("非空", str(cm.exception))

    def test_D3_rejects_side_effects(self):
        with self.assertRaises(ActionError) as cm:
            self._load(lambda a: a.__setitem__(
                "side_effects", [{"notify": "x"}]))
        self.assertIn("副作用", str(cm.exception))

    def test_D3_rejects_async(self):
        with self.assertRaises(ActionError) as cm:
            self._load(lambda a: a.__setitem__("async", True))
        self.assertIn("异步", str(cm.exception))

    def test_rejects_effect_on_undeclared_relation(self):
        def m(a):
            a["effects"] = [{"set": {"path": "nope", "value": "1"}}]
        with self.assertRaises(ActionError) as cm:
            self._load(m)
        self.assertIn("不是", str(cm.exception))

    def test_definition_hash_is_content_addressed(self):
        self.assertTrue(self.action.definition_hash.startswith("sha256:"))
        self.assertEqual(len(self.action.definition_hash), 7 + 64)


# ==========================================================================
# 阶段顺序（S-1 / S-3）
# ==========================================================================

class TestStageOrder(Base):

    def test_S1_permission_checked_before_precondition(self):
        """
        关键条款：权限 MUST 早于前置条件。
        无权限 + 前置条件也不满足时，必须报 `permission`，不能报 `precondition`
        —— 否则会通过报错内容泄露目标实例的状态。
        """
        r = self.submit(O2, {"reason": "x", "refund_amount": 1.0})
        self.assertEqual(r["outcome"], "rejected")
        self.assertEqual(r["stage"], "permission",
                         "无权限时不得暴露前置条件的失败原因")

    def test_S3_param_failure_does_not_read_target(self):
        """参数校验失败时 MUST NOT 读取目标实例。"""
        calls = []
        orig = self.store.get_one

        def spy(subject, relation, snapshot=None):
            calls.append((subject, relation))
            return orig(subject, relation, snapshot)

        self.store.get_one = spy
        r = self.submit(O1, {"reason": 123, "refund_amount": 1.0})
        self.assertEqual(r["stage"], "parameter")
        self.assertEqual(calls, [], "参数阶段不应发生任何目标读取")

    def test_target_checked_before_permission(self):
        """目标不存在时先报 target（比权限更早，且不泄露信息）。"""
        r = self.submit(f"{NS}:Order:NOPE", {"reason": "x",
                                             "refund_amount": 1.0})
        self.assertEqual(r["stage"], "target")


# ==========================================================================
# 幂等（I-1 .. I-4）
# ==========================================================================

class TestIdempotency(Base):

    def test_I2_replay_returns_original_result(self):
        self.grant(O1)
        first = self.submit(O1)
        second = self.submit(O1)
        self.assertEqual(first["outcome"], "succeeded")
        self.assertTrue(second.get("idempotent_replay"))
        self.assertEqual(first["record_id"], second["record_id"])

    def test_I2_replay_does_not_reexecute_effects(self):
        self.grant(O1)
        self.submit(O1)
        v = self.store.get_version(O1)
        self.submit(O1)
        self.assertEqual(self.store.get_version(O1), v, "重放不得再次写版本")

    def test_I3_scope_includes_action_target_and_key(self):
        """不同目标不得共享幂等键。"""
        self.grant(O1)
        self.grant(O2)
        with self.store.transaction():
            tx = self.store.bump_snapshot()
            self.store.set_fact(O2, "status", "pending", "literal", tx,
                                single_valued=True)
        a = self.submit(O1)
        b = self.submit(O2)
        self.assertTrue(a["outcome"] == b["outcome"] == "succeeded")
        self.assertNotEqual(a["record_id"], b["record_id"])

    def test_distinct_parameters_are_not_replays(self):
        self.grant(O1)
        a = self.submit(O1, {"reason": "r1", "refund_amount": 10.0})
        b = self.submit(O1, {"reason": "r2", "refund_amount": 10.0})
        self.assertFalse(b.get("idempotent_replay"))
        self.assertNotEqual(a["record_id"], b["record_id"])


# ==========================================================================
# 并发（C-1 .. C-3）
# ==========================================================================

class TestConcurrency(Base):

    def test_C2_version_mismatch_is_rejected(self):
        self.grant(O1)
        r = self.submit(O1, expected_version=999)
        self.assertEqual(r["stage"], "conflict")
        self.assertEqual(r["code"], "VERSION_CONFLICT")
        self.assertTrue(r["retryable"], "冲突应可重试")

    def test_C2_matching_version_succeeds(self):
        self.grant(O1)
        r = self.submit(O1, expected_version=0)
        self.assertEqual(r["outcome"], "succeeded")
        self.assertEqual(r["new_version"], 1)


# ==========================================================================
# 原子性（A-1 / A-4）
# ==========================================================================

class TestAtomicity(Base):

    def test_A4_failed_effect_leaves_no_partial_change(self):
        """效果应用中途失败 → 整体回滚，不得部分生效。"""
        self.grant(O1)
        before = self.store.get_one(O1, "status")

        orig = self.store.set_fact
        state = {"n": 0}

        def flaky(*args, **kw):
            state["n"] += 1
            if state["n"] == 2:
                raise RuntimeError("模拟存储故障")
            return orig(*args, **kw)

        self.store.set_fact = flaky
        with self.assertRaises(RuntimeError):
            self.submit(O1)

        self.assertEqual(self.store.get_one(O1, "status"), before,
                         "第一个 effect 必须被回滚")
        self.assertEqual(self.store.get_version(O1), 0)

    def test_A2_preconditions_share_one_snapshot(self):
        """两个前置条件必须基于同一快照。"""
        self.grant(O1)
        seen = []
        orig = self.store.get_one

        def spy(subject, relation, snapshot=None):
            if snapshot is not None:
                seen.append(snapshot)
            return orig(subject, relation, snapshot)

        self.store.get_one = spy
        self.submit(O1)
        self.assertTrue(seen)
        self.assertEqual(len(set(seen)), 1, f"快照不一致: {set(seen)}")


# ==========================================================================
# 审计（R-1 .. R-5）
# ==========================================================================

class TestAudit(Base):

    def test_R1_success_record_in_same_transaction(self):
        self.grant(O1)
        r = self.submit(O1)
        rows = self.store.audit_records(O1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["record_id"], r["record_id"])
        self.assertEqual(rows[0]["outcome"], "succeeded")

    def test_R2_rejections_also_recorded(self):
        self.submit(O2, {"reason": "x", "refund_amount": 1.0})   # 无权限
        rows = self.store.audit_records(O2)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["outcome"], "rejected")
        self.assertEqual(rows[0]["stage"], "permission")

    def test_R2_idempotent_replay_does_not_add_record(self):
        self.grant(O1)
        self.submit(O1)
        self.submit(O1)
        self.assertEqual(len(self.store.audit_records(O1)), 1,
                         "重放不应新增审计记录")

    def test_R4_record_contains_definition_hash(self):
        self.grant(O1)
        self.submit(O1)
        rec = self.store.audit_records(O1)[0]
        self.assertEqual(rec["definition_hash"], self.action.definition_hash)

    def test_R5_record_contains_snapshot_when_facts_were_read(self):
        self.grant(O1)
        self.submit(O1)
        rec = self.store.audit_records(O1)[0]
        self.assertIsNotNone(rec["snapshot"])

    def test_audit_records_read_concepts(self):
        self.grant(O1)
        self.submit(O1)
        rec = self.store.audit_records(O1)[0]
        self.assertIn("Order", rec["read_concepts"])


# ==========================================================================
# §8 验收样本集（9 条）
# ==========================================================================

class TestAcceptanceSamples(Base):
    """规范 §8 的 9 条样本。第 9 条特别重要：幂等不是拒绝。"""

    def test_sample_01_param_type(self):
        self.grant(O1)
        r = self.submit(O1, {"reason": 123, "refund_amount": 1.0})
        self.assertEqual((r["outcome"], r["stage"]),
                         ("rejected", "parameter"))

    def test_sample_02_missing_required(self):
        self.grant(O1)
        r = self.submit(O1, {"reason": "x"})
        self.assertEqual((r["outcome"], r["stage"]),
                         ("rejected", "parameter"))

    def test_sample_03_constraint_violated(self):
        self.grant(O1)
        r = self.submit(O1, {"reason": "x", "refund_amount": -1.0})
        self.assertEqual((r["outcome"], r["stage"]),
                         ("rejected", "parameter"))
        self.assertEqual(r["code"], "PARAMETER_CONSTRAINT_VIOLATED")

    def test_sample_04_target_missing(self):
        self.grant(O1)
        r = self.submit(f"{NS}:Order:NOPE",
                        {"reason": "x", "refund_amount": 1.0})
        self.assertEqual((r["outcome"], r["stage"]), ("rejected", "target"))

    def test_sample_05_permission_denied(self):
        r = self.submit(O1, {"reason": "x", "refund_amount": 1.0})
        self.assertEqual((r["outcome"], r["stage"]),
                         ("rejected", "permission"))

    def test_sample_06_precondition_P1(self):
        self.grant(O2)                                     # shipped
        r = self.submit(O2, {"reason": "x", "refund_amount": 1.0})
        self.assertEqual((r["outcome"], r["stage"]),
                         ("rejected", "precondition"))
        self.assertEqual(r["violations"][0]["id"], "P1")

    def test_sample_07_precondition_P2(self):
        self.grant(O2)
        with self.store.transaction():
            tx = self.store.bump_snapshot()
            self.store.set_fact(O2, "status", "pending", "literal", tx,
                                single_valued=True)
        r = self.submit(O2, {"reason": "x", "refund_amount": 999.0})
        self.assertEqual((r["outcome"], r["stage"]),
                         ("rejected", "precondition"))
        self.assertEqual(r["violations"][0]["id"], "P2")

    def test_sample_08_version_conflict(self):
        self.grant(O1)
        r = self.submit(O1, expected_version=999)
        self.assertEqual((r["outcome"], r["stage"]), ("rejected", "conflict"))

    def test_sample_09_idempotent_is_NOT_a_rejection(self):
        """⭐ 第 9 条：重复幂等键必须返回原结果，而不是拒绝。"""
        self.grant(O1)
        first = self.submit(O1)
        second = self.submit(O1)
        self.assertEqual(second["outcome"], "succeeded")
        self.assertNotEqual(second["outcome"], "rejected")
        self.assertTrue(second.get("idempotent_replay"))

    def test_rejection_includes_actual_values(self):
        """拒绝信息必须含 actual —— 这是 Agent 自纠的关键（A-2）。"""
        self.grant(O2)
        r = self.submit(O2, {"reason": "x", "refund_amount": 1.0})
        self.assertIn("actual", r["violations"][0])
        self.assertEqual(r["violations"][0]["actual"]["status"], "shipped")

    def test_rejection_includes_retryable(self):
        for target, params in ((O1, GOOD),):
            self.grant(target)
            r = self.submit(target, params)
            if r["outcome"] == "rejected":
                self.assertIn("retryable", r)


# ==========================================================================
# I2-1：写入路径必须过规则
# ==========================================================================

class TestWritePathConstraints(Base):
    """
    这是参考实现暴露出的真实教训：
    最初 multiplicity 只在**读取时**检查，脏数据能写进去。
    框架 I2-1 要求在**写入路径**上拦截。
    """

    def test_single_valued_write_replaces(self):
        with self.store.transaction():
            tx = self.store.bump_snapshot()
            self.store.set_fact(O1, "status", "pending", "literal", tx,
                                single_valued=True)
        self.assertEqual(len(self.store.get_objects(O1, "status")), 1)

    def test_multi_valued_write_appends(self):
        with self.store.transaction():
            tx = self.store.bump_snapshot()
            self.store.set_fact(O1, "tag", "a", "literal", tx,
                                single_valued=False)
            self.store.set_fact(O1, "tag", "b", "literal", tx,
                                single_valued=False)
        self.assertEqual(len(self.store.get_objects(O1, "tag")), 2)

    def test_read_detects_pre_existing_violation(self):
        """绕过写入路径造出的脏数据，读取时必须报错而不是静默取一个。"""
        with self.store.transaction():
            tx = self.store.bump_snapshot()
            self.store.assert_fact(Fact(O1, "status", "pending", "literal"), tx)
            self.store.assert_fact(Fact(O1, "status", "shipped", "literal"), tx)
        with self.assertRaises(ValueError) as cm:
            self.store.get_one(O1, "status")
        self.assertIn("单值", str(cm.exception))

    def test_action_write_respects_single_valued(self):
        self.grant(O1)
        self.submit(O1)
        self.assertEqual(len(self.store.get_objects(O1, "status")), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
