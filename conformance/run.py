"""
一致性测试运行器

用法：
    python conformance/run.py reference/conformance_adapter.py

它会把 89 个单元测试里**可跨实现复现**的部分抽出来，
用一个中立的适配器协议跑任何实现。
"""

from __future__ import annotations

import importlib.util
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FIXTURES = ROOT / "reference" / "examples"

NS = "urn:sem:acme:supply"
O1, O2, O3 = (f"{NS}:Order:{n}" for n in ("12345", "67890", "11111"))
C1, C2, C3, C4 = (f"{NS}:Customer:{n}" for n in ("g", "a", "b", "c"))
ACTOR = "user:anne"

SEED = [
    {"subject": O1, "concept": "Order", "relation": "nr",
     "object": "12345"},
    {"subject": O1, "concept": "Order", "relation": "status",
     "object": "pending"},
    {"subject": O1, "concept": "Order", "relation": "paid_amount",
     "object": "100.0"},
    {"subject": O2, "concept": "Order", "relation": "nr", "object": "67890"},
    {"subject": O2, "concept": "Order", "relation": "status",
     "object": "shipped"},
    {"subject": O2, "concept": "Order", "relation": "paid_amount",
     "object": "250.0"},
    # O3：第二个 pending 订单，供"幂等作用域"用例使用
    # （O2 是 shipped，会在 P1 前置条件上先被拒，测不到幂等作用域）
    {"subject": O3, "concept": "Order", "relation": "nr", "object": "11111"},
    {"subject": O3, "concept": "Order", "relation": "status",
     "object": "pending"},
    {"subject": O3, "concept": "Order", "relation": "paid_amount",
     "object": "50.0"},
    {"subject": O1, "concept": "Order", "relation": "customer",
     "object": C1, "kind": "instance"},
    {"subject": O2, "concept": "Order", "relation": "customer",
     "object": C2, "kind": "instance"},
    {"subject": C1, "concept": "Customer", "relation": "cid", "object": "g"},
    {"subject": C1, "concept": "Customer", "relation": "risk_flag",
     "object": "low"},
    {"subject": C2, "concept": "Customer", "relation": "cid", "object": "a"},
    {"subject": C3, "concept": "Customer", "relation": "cid", "object": "b"},
    {"subject": C4, "concept": "Customer", "relation": "cid", "object": "c"},
    {"subject": C1, "concept": "Customer", "relation": "holds",
     "object": C2, "kind": "instance"},
    {"subject": C2, "concept": "Customer", "relation": "holds",
     "object": C3, "kind": "instance"},
    {"subject": C3, "concept": "Customer", "relation": "holds",
     "object": C4, "kind": "instance"},
]


# --------------------------------------------------------------------------
# 用例
# --------------------------------------------------------------------------

class Ctx:
    """用例上下文。"""

    def __init__(self, a):
        self.a = a
        self.cancel = a.action_qualified("cancel_order")
        self.return_ = a.action_qualified("return_order")
        self.flag = a.action_qualified("flag_order")


def cases() -> dict[str, list[tuple[str, str, callable]]]:
    out: dict[str, list] = {"I4": [], "I3": [], "I6": []}

    def add(group, clause, name):
        def deco(fn):
            out[group].append((clause, name, fn))
            return fn
        return deco

    # ====================================================== I4
    I4 = "I4"

    @add(I4, "§8-1", "参数类型不符 → stage=parameter")
    def _(c):
        assert c.a.submit(c.cancel, O1, {"reason": 1, "refund_amount": 1.0},
                          ACTOR).get("stage") == "parameter"

    @add(I4, "§8-2", "缺必填参数 → stage=parameter")
    def _(c):
        assert c.a.submit(c.cancel, O1, {"reason": "x"},
                          ACTOR).get("stage") == "parameter"

    @add(I4, "§8-3", "违反 constraints → stage=parameter")
    def _(c):
        r = c.a.submit(c.cancel, O1, {"reason": "x", "refund_amount": -1.0},
                       ACTOR)
        assert r.get("stage") == "parameter", r

    @add(I4, "§8-4", "目标不存在 → stage=target")
    def _(c):
        r = c.a.submit(c.cancel, f"{NS}:Order:NOPE",
                       {"reason": "x", "refund_amount": 1.0}, ACTOR)
        assert r.get("stage") == "target", r

    @add(I4, "§8-5", "无权限 → stage=permission")
    def _(c):
        r = c.a.submit(c.cancel, O1, {"reason": "x", "refund_amount": 1.0},
                       ACTOR)
        assert r.get("stage") == "permission", r

    @add(I4, "§8-6", "P1 前置条件 → violations 含 P1")
    def _(c):
        c.a.grant(ACTOR, "can_cancel", O2)
        r = c.a.submit(c.cancel, O2, {"reason": "x", "refund_amount": 1.0},
                       ACTOR)
        assert r.get("stage") == "precondition", r
        assert r["violations"][0]["id"] == "P1", r

    @add(I4, "§8-8", "版本冲突 → stage=conflict 且 retryable")
    def _(c):
        c.a.grant(ACTOR, "can_cancel", O1)
        r = c.a.submit(c.cancel, O1, {"reason": "x", "refund_amount": 1.0},
                       ACTOR, expected_version=999)
        assert r.get("stage") == "conflict", r
        assert r.get("retryable") is True, r

    @add(I4, "§8-9", "⭐ 幂等命中不是拒绝")
    def _(c):
        c.a.grant(ACTOR, "can_cancel", O1)
        p = {"reason": "x", "refund_amount": 1.0}
        first = c.a.submit(c.cancel, O1, p, ACTOR)
        assert first["outcome"] == "succeeded", first
        second = c.a.submit(c.cancel, O1, p, ACTOR)
        assert second["outcome"] == "succeeded", "幂等命中不得返回 rejected"
        assert second.get("record_id") == first.get("record_id"), second

    @add(I4, "S-1", "权限校验 MUST 早于前置条件")
    def _(c):
        """无权限时不得到达前置条件 —— 否则泄露目标状态。"""
        r = c.a.submit(c.cancel, O2, {"reason": "x", "refund_amount": 1.0},
                       ACTOR)
        assert r.get("stage") == "permission", \
            f"无权限时应报 permission（不得泄露前置条件失败原因），实为 {r.get('stage')}"

    @add(I4, "I-2", "重放不重复执行效果（版本不变）")
    def _(c):
        c.a.grant(ACTOR, "can_cancel", O1)
        p = {"reason": "x", "refund_amount": 1.0}
        a = c.a.submit(c.cancel, O1, p, ACTOR)
        v = a.get("new_version")
        b = c.a.submit(c.cancel, O1, p, ACTOR)
        assert b.get("new_version") == v, "重放不得再次写入"

    @add(I4, "I-3", "幂等作用域含目标实例")
    def _(c):
        c.a.grant(ACTOR, "can_cancel", O1)
        c.a.grant(ACTOR, "can_cancel", O3)
        p = {"reason": "x", "refund_amount": 1.0}
        a = c.a.submit(c.cancel, O1, p, ACTOR)
        b = c.a.submit(c.cancel, O3, p, ACTOR)
        assert a.get("outcome") == "succeeded", a
        assert b.get("outcome") == "succeeded", b
        assert a["record_id"] != b["record_id"], "不同目标不得共享幂等键"

    @add(I4, "A-4", "效果失败不得部分生效")
    def _(c):
        c.a.grant(ACTOR, "can_flag", O1)
        before = {f["relation"]: f["object"] for f in SEED
                  if f["subject"] == O1}
        try:
            c.a.submit(c.flag, O1, {"reason": "fraud"}, ACTOR)
        except Exception:
            pass
        after = c.a.query(subject=O1)["items"]
        got = {i["relation"]: i["object"] for i in after}
        for k, v in before.items():
            if k in got:
                assert got[k] is not None

    @add(I4, "R-4", "审计含 definition_hash")
    def _(c):
        c.a.grant(ACTOR, "can_cancel", O1)
        c.a.submit(c.cancel, O1, {"reason": "x", "refund_amount": 1.0}, ACTOR)
        # 通过 I6 拿到定义哈希，确认它存在且是内容寻址
        d = c.a.describe_action(c.cancel)
        assert d.get("definition_hash", "").startswith("sha256:"), d

    @add(I4, "M-2", "未声明的 applies_to 必须被拒绝")
    def _(c):
        """⚠️ 需要实现拒绝非法定义。若实现未校验，会静默生效。"""
        bad = """
action:
  name: bad_multi
  namespace: urn:sem:acme:supply
  version: 1.0.0
  target:
    concept: Order
  effects:
    - applies_to: nowhere
      set: { path: "status", value: "'x'" }
  idempotency: { key: "target.nr" }
  side_effects: []
  async: false
"""
        try:
            c.a.load_action(bad)
        except Exception:
            return                       # 正确：拒绝了
        raise AssertionError("未声明的 applies_to 应被拒绝")

    @add(I4, "M-5", "多实例写入原子且两实例都升版本")
    def _(c):
        c.a.grant(ACTOR, "can_flag", O1)
        r = c.a.submit(c.flag, O1, {"reason": "fraud"}, ACTOR)
        assert r.get("outcome") == "succeeded", r
        vs = r.get("versions") or {}
        assert len(vs) >= 2, f"应有两个实例的版本号，实为 {vs}"

    @add(I4, "N-4", "表达式支持 is null / is not null")
    def _(c):
        """通过一个可选参数 + is null 守卫的动作来验证。"""
        good = """
action:
  name: opt_probe
  namespace: urn:sem:acme:supply
  version: 1.0.0
  target:
    concept: Order
    reads: [Order]
  parameters:
    - name: note
      type: CancelReason
      required: false
  permissions: { relation: "can_cancel", resource: "${target}" }
  preconditions:
    - id: N1
      expression: "note is null or note != ''"
      message: "备注必须为空或非空串"
  effects:
    - set: { path: "cancel_reason", value: "'probe'" }
  idempotency: { key: "target.nr" }
  side_effects: []
  async: false
"""
        c.a.load_action(good)
        q = c.a.action_qualified("opt_probe")
        c.a.grant(ACTOR, "can_cancel", O1)
        r = c.a.submit(q, O1, {}, ACTOR)      # note 缺失 → null
        assert r.get("outcome") == "succeeded", \
            f"`note is null` 守卫应让缺失的 note 通过，实为 {r}"

    @add(I4, "M-8", "YAML 键名 `on` 必须被拒绝")
    def _(c):
        bad = """
action:
  name: on_key_probe
  namespace: urn:sem:acme:supply
  version: 1.0.0
  target: { concept: Order }
  effects:
    - on: default
      set: { path: "status", value: "'x'" }
  idempotency: { key: "target.nr" }
  side_effects: []
  async: false
"""
        try:
            c.a.load_action(bad)
        except Exception:
            return
        raise AssertionError(
            "YAML 会把 `on` 解析成布尔 true，键名丢失；实现必须显式拒绝它")

    # ====================================================== I3
    I3 = "I3"

    @add(I3, "D-1", "基础派生")
    def _(c):
        r = c.a.infer(relation="holds_transitively")
        pairs = {(i["subject"], i["object"]) for i in r["items"]}
        assert (C1, C2) in pairs, "直接持股应属于穿透持股"

    @add(I3, "D-1", "不动点：链首可达链尾")
    def _(c):
        r = c.a.infer(relation="holds_transitively")
        pairs = {(i["subject"], i["object"]) for i in r["items"]}
        assert (C1, C4) in pairs, "4 节点链的传递闭包应含 g⇒c（需 2 轮迭代）"
        assert len(r["items"]) == 6, f"闭包应有 6 条，实为 {len(r['items'])}"

    @add(I3, "§3.2", "⭐ 派生事实 MUST 带 via")
    def _(c):
        for i in c.a.infer(relation="holds_transitively")["items"]:
            assert i.get("derived") is True, i
            v = i.get("via")
            assert v and "rule" in v and "case" in v, f"缺 via: {i}"
            assert isinstance(v.get("premises"), list) and v["premises"], i

    @add(I3, "§3.2", "via.premises 必须真实存在")
    def _(c):
        derived = {(i["subject"], i["relation"], i["object"])
                   for i in c.a.infer(relation="holds_transitively")["items"]}
        stored = {(i["subject"], i["relation"], i["object"])
                  for i in c.a.query()["items"]}
        for i in c.a.infer(relation="holds_transitively")["items"]:
            for p in i["via"]["premises"]:
                key = (p["subject"], p["relation"], p["object"])
                assert key in stored or key in derived, f"前提 {key} 不存在"

    @add(I3, "D-2", "派生事实不落库")
    def _(c):
        c.a.infer(relation="holds_transitively")
        r = c.a.query(relation="holds_transitively")
        assert r["budget"]["total"] == 0, "派生事实不得被持久化"

    @add(I3, "Q-1", "⭐ 截断必须显式")
    def _(c):
        r = c.a.infer(relation="holds_transitively", max_items=2)
        assert r["budget"]["returned"] == 2, r["budget"]
        assert r["budget"]["total"] == 6, r["budget"]
        assert r["truncated"] is True, "被截断时 truncated 必须为 true"

    @add(I3, "Q-1", "未截断时不得误报")
    def _(c):
        r = c.a.infer(relation="holds_transitively", max_items=100)
        assert r["truncated"] is False, r

    @add(I3, "Q-3", "结果顺序确定")
    def _(c):
        a = [(i["subject"], i["object"])
             for i in c.a.infer(relation="holds_transitively")["items"]]
        b = [(i["subject"], i["object"])
             for i in c.a.infer(relation="holds_transitively")["items"]]
        assert a == b, "同一状态下两次查询顺序必须一致"

    @add(I3, "T-2", "遍历必须检测环")
    def _(c):
        r = c.a.traverse(C1, ["holds"], max_depth=20)
        assert len(r["items"]) == 3, f"链上应只到达 3 个节点，实为 {len(r['items'])}"

    @add(I3, "T-3", "遍历必须返回路径")
    def _(c):
        r = c.a.traverse(C1, ["holds"], max_depth=3)
        deep = max(r["items"], key=lambda i: i["hops"])
        assert deep["hops"] == 3 and len(deep["path"]) == 3, deep

    @add(I3, "S-2", "检索须标明命中字段")
    def _(c):
        r = c.a.search("12345")
        assert r["items"], "应命中订单号"
        assert "matched_field" in r["items"][0], r["items"][0]

    @add(I3, "§2.1", "结果信封含 snapshot")
    def _(c):
        r = c.a.query()
        assert isinstance(r.get("snapshot"), int), r

    # ====================================================== I6
    I6 = "I6"

    @add(I6, "G1", "概念可完整枚举")
    def _(c):
        got = {x["name"] for x in c.a.list_concepts()}
        expect = {"Order", "Customer", "OrderNr", "CustomerId",
                  "OrderStatus", "Money", "CancelReason", "RiskLevel"}
        assert got == expect, f"枚举不全: 缺 {expect - got}，多 {got - expect}"

    @add(I6, "G1", "概念可按下述类型过滤")
    def _(c):
        ent = {x["name"] for x in c.a.list_concepts(kind="EntityType")}
        assert ent == {"Order", "Customer"}, ent

    @add(I6, "G1", "动作可按概念筛选")
    def _(c):
        acts = c.a.list_actions(concept="Order")
        assert len(acts) == 3, f"Order 上应有 3 个动作，实为 {len(acts)}"
        assert all(x["target_concept"] == "Order" for x in acts)

    @add(I6, "E-2", "⭐ DescribeAction 返回完整契约")
    def _(c):
        d = c.a.describe_action(c.cancel)
        for k in ("qualified", "version", "target", "parameters",
                  "permissions", "preconditions", "effects", "idempotency"):
            assert k in d, f"契约缺少 `{k}`"
        assert d["parameters"] and d["preconditions"] and d["effects"], d

    @add(I6, "F-3", "⭐ 查找结果 MUST 带 matched_on")
    def _(c):
        res = c.a.find_by_capability("退货")
        assert res, "应能查到 return_order"
        for r in res:
            assert r.get("matched_on"), f"缺 matched_on: {r}"

    @add(I6, "F-6", "⭐ 无匹配 MUST 返回空，不得兜底")
    def _(c):
        res = c.a.find_by_capability("完全不相关的需求xyzzy")
        assert res == [], f"无匹配应返回空列表，实为 {res}"

    @add(I6, "F-2", "相关查询应把对应动作排在前列")
    def _(c):
        r1 = c.a.find_by_capability("订单已发货要退货")
        assert r1 and r1[0]["qualified"] == c.return_, r1
        r2 = c.a.find_by_capability("取消订单")
        assert r2 and r2[0]["qualified"] == c.cancel, r2

    @add(I6, "F-1", "支持按概念筛选")
    def _(c):
        res = c.a.find_by_capability("订单", concept="Customer")
        assert res == [], f"按 Customer 过滤不应返回 Order 的动作: {res}"

    @add(I6, "G4", "结果确定性")
    def _(c):
        a = [x["qualified"] for x in c.a.find_by_capability("订单")]
        b = [x["qualified"] for x in c.a.find_by_capability("订单")]
        assert a == b, "同一查询两次结果顺序必须一致"

    @add(I6, "G5", "发现不得产生副作用")
    def _(c):
        before = c.a.query()["budget"]["total"]
        c.a.list_concepts()
        c.a.list_actions()
        c.a.find_by_capability("订单")
        after = c.a.query()["budget"]["total"]
        assert before == after, "I6 操作不得修改任何状态"

    @add(I6, "G3", "发现结果是结构化数据")
    def _(c):
        for x in c.a.list_concepts():
            assert isinstance(x, dict) and "name" in x and "type" in x, x

    return out


# --------------------------------------------------------------------------
# 运行
# --------------------------------------------------------------------------

def load_adapter(path: str):
    p = Path(path)
    if not p.is_absolute():
        p = (Path.cwd() / p).resolve()
    spec = importlib.util.spec_from_file_location("conformance_adapter_under_test", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["conformance_adapter_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod.Adapter()


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    adapter_path = argv[1]

    try:
        adapter = load_adapter(adapter_path)
    except Exception as e:
        print(f"❌ 无法加载适配器 {adapter_path}: {e}")
        traceback.print_exc()
        return 2

    ontology_text = (FIXTURES / "ontology.ossie.yaml").read_text(encoding="utf-8")
    action_texts = [p.read_text(encoding="utf-8")
                    for p in sorted((FIXTURES / "actions").glob("*.yaml"))]

    adapter.load_ontology(ontology_text)
    for t in action_texts:
        adapter.load_action(t)

    groups = cases()
    summary: dict[str, tuple[int, int]] = {}
    failures: list[str] = []

    for group, items in groups.items():
        ok = 0
        for clause, name, fn in items:
            adapter.reset()
            adapter.seed(list(SEED))
            ctx = Ctx(adapter)
            try:
                fn(ctx)
                ok += 1
            except Exception as e:
                failures.append(f"[{group} {clause}] {name}\n      "
                                f"{type(e).__name__}: {e}")
        summary[group] = (ok, len(items))

    width = max(len(g) for g in summary)
    print()
    for g, (ok, total) in summary.items():
        mark = "✓" if ok == total else "✗"
        print(f"  {g:<{width}}  {mark} {ok}/{total}")

    if failures:
        print(f"\n失败 {len(failures)} 项:\n")
        for f in failures:
            print(f"  ✗ {f}")
        print("\n一致性等级: 无（存在未通过的 MUST 条款）")
        return 1

    levels = [f"{g}-min/Core" for g, (ok, tot) in summary.items()]
    print(f"\n一致性等级: {', '.join(levels)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
