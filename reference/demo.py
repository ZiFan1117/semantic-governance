"""
I4-min 参考实现 · 端到端演示

运行：
    python reference/demo.py

演示覆盖规范 §8 验收样本集的全部 9 条。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from engine import ActionEngine, ActionLoader, SimpleAuthz   # noqa: E402
from ossie_model import OssieModel                            # noqa: E402
from store import Fact, Store                                 # noqa: E402

HERE = Path(__file__).parent
ONTOLOGY = HERE / "examples" / "ontology.ossie.yaml"
ACTION = HERE / "examples" / "actions" / "cancel_order.action.yaml"

NS = "urn:sem:acme:supply"
ORDER_1 = f"{NS}:Order:12345"      # 待处理、已付 100
ORDER_2 = f"{NS}:Order:67890"      # 已发货
ACTOR = "user:anne"


def hr(title: str) -> None:
    print("\n" + "=" * 72)
    print(f"  {title}")
    print("=" * 72)


def show(label: str, result: dict) -> None:
    print(f"\n▸ {label}")
    print(json.dumps(result, indent=2, ensure_ascii=False))


def seed(store: Store) -> None:
    """
    灌入初始事实。

    ⚠️ 必须走 `set_fact(single_valued=...)` 而不是裸 `assert_fact`：
       前者在**写入路径**上强制 multiplicity 约束（框架 I2-G1）。
       Order.nr / Order.status / Order.paid_amount 在 Ossie 里都是
       ManyToOne（单值），所以 single_valued=True。
    """
    with store.transaction():
        tx = store.bump_snapshot()
        for order, status, paid in (
            (ORDER_1, "pending", 100.0),
            (ORDER_2, "shipped", 250.0),
        ):
            store.set_fact(order, "nr", order.rsplit(":", 1)[1], "literal", tx,
                           single_valued=True, source="seed")
            store.set_fact(order, "status", status, "literal", tx,
                           single_valued=True, source="seed")
            store.set_fact(order, "paid_amount", str(paid), "literal", tx,
                           single_valued=True, source="seed")


def main() -> int:
    hr("0. 加载 Ossie 本体（L3 / I1）")
    model = OssieModel.from_file(ONTOLOGY)
    print(model.describe())

    hr("1. 加载动作定义并校验它对 Ossie 的引用（规范 D-1）")
    action = ActionLoader.load(ACTION, model)
    print(f"动作      : {action.qualified_versioned}")
    print(f"作用概念  : {action.target_concept}")
    print(f"读取概念  : {action.reads}")
    print(f"参数      : {[p.name for p in action.parameters]}")
    print(f"前置条件  : {[p.id for p in action.preconditions]}")
    print(f"定义哈希  : {action.definition_hash}")

    store = Store(":memory:")
    authz = SimpleAuthz()
    seed(store)
    print(f"\n初始状态  : {store.stats()}")

    # 权限：anne 可取消 ORDER_1，不可取消 ORDER_2
    authz.grant(ACTOR, "can_cancel", ORDER_1)

    engine = ActionEngine(model, store, authz)

    hr("2. 成功提交（样本集之外的正常路径）")
    r = engine.submit(action, ORDER_1, {"reason": "customer_request",
                                        "refund_amount": 100.0},
                      actor=ACTOR)
    show("取消 ORDER_1", r)
    print(f"\n订单状态  : {store.get_one(ORDER_1, 'status')}")
    print(f"取消原因  : {store.get_one(ORDER_1, 'cancel_reason')}")
    print(f"退款金额  : {store.get_one(ORDER_1, 'refunded_amount')}")

    hr("3. 幂等重放（样本集第 9 条：不拒绝，返回原结果）")
    r2 = engine.submit(action, ORDER_1, {"reason": "customer_request",
                                         "refund_amount": 100.0},
                       actor=ACTOR)
    show("重复提交同一请求", r2)
    assert r2.get("idempotent_replay") is True, "应标记为重放"
    assert r2["record_id"] == r["record_id"], "应返回原结果"
    print("\n✅ 幂等命中：未拒绝，返回原结果")

    hr("4. 验收样本集 1-3：参数错误")
    show("① 参数类型不符",
         engine.submit(action, ORDER_2, {"reason": 123,
                                         "refund_amount": 10.0}, actor=ACTOR))
    show("② 缺少必填参数",
         engine.submit(action, ORDER_2, {"reason": "x"}, actor=ACTOR))
    show("③ 违反 constraints（refund_amount < 0）",
         engine.submit(action, ORDER_2, {"reason": "x",
                                         "refund_amount": -1.0}, actor=ACTOR))

    hr("5. 验收样本集 4：目标不存在")
    show("目标实例不存在",
         engine.submit(action, f"{NS}:Order:NOPE",
                       {"reason": "x", "refund_amount": 1.0}, actor=ACTOR))

    hr("6. 验收样本集 5：无权限")
    show("anne 对 ORDER_2 无 can_cancel",
         engine.submit(action, ORDER_2, {"reason": "x", "refund_amount": 1.0},
                       actor=ACTOR))

    hr("7. 验收样本集 6-7：前置条件不满足（先授权）")
    authz.grant(ACTOR, "can_cancel", ORDER_2)
    show("P1：订单已发货（status=shipped）",
         engine.submit(action, ORDER_2, {"reason": "x", "refund_amount": 1.0},
                       actor=ACTOR))

    # 造一个 pending 但退款超额的单（走 set_fact，写入路径强制单值约束）
    with store.transaction():
        tx = store.bump_snapshot()
        store.set_fact(ORDER_2, "status", "pending", "literal", tx,
                       single_valued=True, source="demo")
    print(f"\n（已把 ORDER_2 的 status 改成 pending；"
          f"当前取值数 = {len(store.get_objects(ORDER_2, 'status'))}）")
    show("P2：退款超过已付金额（paid=250，refund=999）",
         engine.submit(action, ORDER_2, {"reason": "x",
                                         "refund_amount": 999.0},
                       actor=ACTOR))

    hr("8. 验收样本集 8：乐观并发冲突")
    show("expected_version 不匹配",
         engine.submit(action, ORDER_2, {"reason": "x", "refund_amount": 1.0},
                       actor=ACTOR, expected_version=999))

    hr("9. 审计轨迹（规范 §5）")
    for rec in store.audit_records():
        print(f"\n{rec['ts']}  {rec['outcome']:<10} "
              f"stage={rec['stage'] or '-':<12} code={rec['code'] or '-'}")
        print(f"   target={rec['target']}  snapshot={rec['snapshot']}")
        print(f"   def_hash={rec['definition_hash']}")
        if rec["violations"] and rec["violations"] != "[]":
            print(f"   violations={rec['violations']}")

    hr("10. 快照读验证（规范 A-2）")
    hist = []
    for snap in range(1, store.current_snapshot() + 1):
        hist.append((snap, store.get_one(ORDER_1, "status", snapshot=snap)))
    print("ORDER_1 的 status 随快照的演变:")
    for snap, st in hist:
        print(f"  snapshot {snap}: {st}")

    print(f"\n最终状态: {store.stats()}")
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
