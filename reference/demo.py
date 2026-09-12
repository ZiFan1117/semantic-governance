"""
I4-min / I3-min / I6-min 参考实现 · 端到端演示

运行：
    python reference/demo.py

覆盖：
    §8  验收样本集 9 条
    I3  派生求值与 via 溯源
    I6  发现与按需查找（含"拒绝后改选"的 Agent 自纠流程）
    v0.2 多实例事务
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from discovery import ActionRegistry, Catalog              # noqa: E402
from engine import ActionEngine, ActionLoader, SimpleAuthz  # noqa: E402
from ossie_model import OssieModel                         # noqa: E402
from query import QueryEngine                              # noqa: E402
from store import Store                                    # noqa: E402

HERE = Path(__file__).parent
EXAMPLES = HERE / "examples"
NS = "urn:sem:acme:supply"

ORDER_1 = f"{NS}:Order:12345"       # pending, paid 100
ORDER_2 = f"{NS}:Order:67890"       # shipped, paid 250
CUST_A = f"{NS}:Customer:acme"
CUST_B = f"{NS}:Customer:beta"
ACTOR = "user:anne"

GOOD = {"reason": "customer_request", "refund_amount": 50.0}


def hr(t: str) -> None:
    print("\n" + "=" * 74 + f"\n  {t}\n" + "=" * 74)


def show(label: str, obj) -> None:
    print(f"\n▸ {label}")
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def seed(store: Store) -> None:
    with store.transaction():
        tx = store.bump_snapshot()
        for inst, concept, pairs in (
            (ORDER_1, "Order", [("nr", "12345"), ("status", "pending"),
                                ("paid_amount", "100.0")]),
            (ORDER_2, "Order", [("nr", "67890"), ("status", "shipped"),
                                ("paid_amount", "250.0")]),
            (CUST_A, "Customer", [("cid", "acme"), ("risk_flag", "low")]),
            (CUST_B, "Customer", [("cid", "beta"), ("risk_flag", "low")]),
        ):
            store.set_concept(inst, concept, tx, source="seed")
            for rel, val in pairs:
                store.set_fact(inst, rel, val, "literal", tx,
                               single_valued=True, source="seed")
        # 订单归属客户 + 股权链
        store.set_fact(ORDER_1, "customer", CUST_A, "instance", tx,
                       single_valued=True, source="seed")
        store.set_fact(ORDER_2, "customer", CUST_B, "instance", tx,
                       single_valued=True, source="seed")
        for a, b in ((CUST_A, CUST_B),):
            store.set_fact(a, "holds", b, "instance", tx,
                           single_valued=False, source="seed")


def main() -> int:
    hr("0. 加载 Ossie 本体（L3 / I1）")
    model = OssieModel.from_file(EXAMPLES / "ontology.ossie.yaml")
    print(model.describe())

    hr("1. 加载动作定义（校验对 Ossie 的引用，规范 D-1）")
    registry = ActionRegistry()
    for f in sorted((EXAMPLES / "actions").glob("*.yaml")):
        a = ActionLoader.load(f, model)
        registry.register(a)
        extra = f"  +附属目标{[t.name for t in a.extra_targets]}" \
            if a.extra_targets else ""
        print(f"  {a.qualified_versioned:<48} target={a.target_concept}{extra}")

    store = Store(":memory:")
    authz = SimpleAuthz()
    seed(store)
    engine = ActionEngine(model, store, authz)
    query = QueryEngine(model, store)

    hr("2. I6 发现：目录从本体自动生成")
    catalog = Catalog(model, registry)
    engine.catalog = catalog            # 接入 I6，用于拒绝时给替代建议
    print(f"概念 {len(catalog.list_concepts())} 个，"
          f"动作 {len(catalog.list_actions())} 个")
    print("\n作用于 Order 的动作:")
    for a in catalog.list_actions(concept="Order"):
        print(f"  {a['qualified'].split(':')[-1]:<14} {a['description']}")

    print("\n派生规则（I3）:")
    print(query.describe_rules())

    hr("3. 成功提交")
    authz.grant(ACTOR, "can_cancel", ORDER_1)
    r = engine.submit(registry.get(f"{NS}:cancel_order"), ORDER_1,
                      {"reason": "customer_request", "refund_amount": 100.0},
                      actor=ACTOR)
    show("取消 ORDER_1", {k: r[k] for k in
                          ("outcome", "record_id", "new_version", "snapshot")})
    print(f"  状态 = {store.get_one(ORDER_1, 'status')}")

    hr("4. 幂等（样本集第 9 条：不拒绝，返回原结果）")
    r2 = engine.submit(registry.get(f"{NS}:cancel_order"), ORDER_1,
                       {"reason": "customer_request", "refund_amount": 100.0},
                       actor=ACTOR)
    print(f"  outcome          = {r2['outcome']}")
    print(f"  idempotent_replay= {r2.get('idempotent_replay')}")
    print(f"  record_id 相同   = {r2['record_id'] == r['record_id']}")

    hr("5. 验收样本集 1~8")
    cancel = registry.get(f"{NS}:cancel_order")

    def reset_status(inst: str, value: str) -> None:
        with store.transaction():
            tx = store.bump_snapshot()
            store.set_fact(inst, "status", value, "literal", tx,
                           single_valued=True, source="demo")

    # ①②③④⑤ 在 ORDER_2（anne 无权限）上验证
    for label, tgt, params, kw in [
        ("① 参数类型不符", ORDER_2, {"reason": 123, "refund_amount": 1.0}, {}),
        ("② 缺必填参数", ORDER_2, {"reason": "x"}, {}),
        ("③ 违反 constraints", ORDER_2, {"reason": "x", "refund_amount": -1.0}, {}),
        ("④ 目标不存在", f"{NS}:Order:NOPE",
         {"reason": "x", "refund_amount": 1.0}, {}),
        ("⑤ 无权限", ORDER_2, {"reason": "x", "refund_amount": 1.0}, {}),
    ]:
        res = engine.submit(cancel, tgt, params, actor=ACTOR, **kw)
        print(f"  {label:<20} → {res['outcome']:<9} stage={res['stage']}")

    # ⑥⑦⑧ 需要授权，且状态要被精确构造
    authz.grant(ACTOR, "can_cancel", ORDER_2)
    authz.grant(ACTOR, "can_cancel", ORDER_1)

    reset_status(ORDER_2, "shipped")
    res = engine.submit(cancel, ORDER_2, {"reason": "x", "refund_amount": 1.0},
                        actor=ACTOR)
    print(f"  {'⑥ P1 前置条件':<20} → {res['outcome']:<9} "
          f"stage={res['stage']} id={res['violations'][0]['id']}")

    reset_status(ORDER_2, "pending")
    res = engine.submit(cancel, ORDER_2, {"reason": "x",
                                          "refund_amount": 999.0}, actor=ACTOR)
    print(f"  {'⑦ P2 前置条件':<20} → {res['outcome']:<9} "
          f"stage={res['stage']} id={res['violations'][0]['id']}")

    reset_status(ORDER_2, "pending")
    res = engine.submit(cancel, ORDER_2, {"reason": "x", "refund_amount": 1.0},
                        actor=ACTOR, expected_version=999)
    print(f"  {'⑧ 版本冲突':<20} → {res['outcome']:<9} stage={res['stage']}"
          f" retryable={res['retryable']}")

    hr("6. ⭐ Agent 自纠流程（I6 §4.3）")
    reset_status(ORDER_2, "shipped")          # 构造"已发货"状态以触发拒绝
    authz.grant(ACTOR, "can_cancel", ORDER_2)
    res = engine.submit(cancel, ORDER_2, {"reason": "x", "refund_amount": 1.0},
                        actor=ACTOR)
    print(f"  ① 提交 cancel_order → {res['outcome']} / {res['stage']}")
    print(f"     violations[0].id = {res['violations'][0]['id']}")
    print(f"     actual           = {res['violations'][0].get('actual')}")
    print(f"\n  ② 拒绝信息里带出的替代建议（来源已标注）:")
    for s in res["suggestions"]:
        print(f"     → {s['action'].split(':')[-1]}  (score={s['score']},"
              f" via={s['via']})")
        print(f"       {s['reason']}")
    print(f"\n  ③ 改走退货流程:")
    authz.grant(ACTOR, "can_return", ORDER_2)
    res2 = engine.submit(registry.get(f"{NS}:return_order"), ORDER_2,
                         {"reason": "damaged", "return_fee": 0.0}, actor=ACTOR)
    print(f"     return_order → {res2['outcome']}")
    print(f"     状态 = {store.get_one(ORDER_2, 'status')}")

    hr("7. ⭐ 多实例事务（I4 v0.2）")
    flag = registry.get(f"{NS}:flag_order")
    authz.grant(ACTOR, "can_flag", ORDER_1)
    with store.transaction():
        tx = store.bump_snapshot()
        store.set_fact(ORDER_1, "status", "pending", "literal", tx,
                       single_valued=True, source="demo")
    print(f"  提交前: ORDER_1.status={store.get_one(ORDER_1, 'status')}  "
          f"CUST_A.risk_flag={store.get_one(CUST_A, 'risk_flag')}")
    res3 = engine.submit(flag, ORDER_1, {"reason": "fraud_signal"},
                         actor=ACTOR)
    show("flag_order 结果", {k: res3[k] for k in
                             ("outcome", "targets", "versions")})
    print(f"  提交后: ORDER_1.status={store.get_one(ORDER_1, 'status')}  "
          f"CUST_A.risk_flag={store.get_one(CUST_A, 'risk_flag')}")
    print(f"  → 两个实例在同一事务内被原子修改")

    hr("8. I3 查询与派生（via 溯源）")
    print("  存储的事实（holds）:")
    for i in query.query(relation="holds")["items"]:
        print(f"    {i['subject'].split(':')[-1]} holds "
              f"{i['object'].split(':')[-1]}   derived={i['derived']}")

    print("\n  派生事实（holds_transitively，每条带 via）:")
    res4 = query.infer(relation="holds_transitively")
    for i in res4["items"]:
        s, o = i["subject"].split(":")[-1], i["object"].split(":")[-1]
        print(f"    {s} ⇒ {o}   via case#{i['via']['case']}:"
              f" {i['via']['expression']}")
        for p in i["via"]["premises"]:
            print(f"        前提: {p['subject'].split(':')[-1]}"
                  f" -{p['relation']}-> {p['object'].split(':')[-1]}")

    print("\n  D-2 验证（派生不落库）:")
    print(f"    Query 查 holds_transitively → "
          f"{query.query(relation='holds_transitively')['budget']['total']} 条")

    print("\n  Q-1 验证（截断必须显式）:")
    r5 = query.infer(relation="holds_transitively", max_items=1)
    print(f"    max_items=1 → returned={r5['budget']['returned']} "
          f"total={r5['budget']['total']} truncated={r5['truncated']}")

    hr("9. 审计轨迹摘要")
    for rec in store.audit_records():
        print(f"  {rec['outcome']:<9} stage={str(rec['stage']):<13}"
              f" snap={rec['snapshot']}  {rec['action'].split(':')[-1]}")
    print(f"\n  全部记录都含 definition_hash: "
          f"{all(r['definition_hash'] for r in store.audit_records())}")

    print(f"\n最终状态: {store.stats()}")
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
