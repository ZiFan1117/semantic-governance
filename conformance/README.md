# 一致性测试套件

> 让**第三方实现**能自测是否合规，而不必读参考实现的代码。

---

## 怎么用

```bash
# 用参考实现自测（应当全绿）
python conformance/run.py reference/conformance_adapter.py

# 用你自己的实现
python conformance/run.py myimpl/adapter.py
```

输出：

```
  I4  ✓ 17/17
  I3  ✓ 12/12
  I6  ✓ 11/11

一致性等级: I4-min/Core, I3-min/Core, I6-min/Core
```

**全部通过 → 可以声称符合对应的 Core 等级。**
有任何失败 → 输出会指出违反了哪条条款。

---

## 适配器协议

你的实现只需提供一个 `Adapter` 类：

```python
class Adapter:
    # --- 装载（测试开始前调用一次）---
    def load_ontology(self, yaml_text: str) -> None: ...
    def load_action(self, yaml_text: str) -> None: ...

    # --- 每个用例前调用 ---
    def reset(self) -> None:
        """
        清空全部事实与授权，**并把动作注册表恢复到基线**。

        基线 = runner 完成初始装载后的状态。
        中途由用例 load_action 加载的探针定义**必须**被清掉，
        否则会污染后续用例（I6 的 G1「可完整枚举」会因此失败）。
        """
    ...
```

> **`reset()` 的基线语义是协议的关键。** 实现可以在首次 `reset()` 时捕获基线 ——
> 那一刻 runner 刚完成初始装载，尚未执行任何会中途加载定义的用例。

    # --- 授权（测试用最小的注入方式）---
    def grant(self, subject: str, relation: str, obj: str) -> None: ...

    # --- 事实（测试直接灌，不走 I5）---
    def seed(self, facts: list[dict]) -> None: ...
        # facts 项：{"subject":..., "concept":..., "relation":...,
        #            "object":..., "kind":"literal"|"instance"}

    # --- I4 ---
    def submit(self, action: str, target: str, params: dict,
               actor: str, **kw) -> dict: ...

    # --- I3 ---
    def query(self, **kw) -> dict: ...
    def infer(self, **kw) -> dict: ...
    def traverse(self, start: str, path: list[str], **kw) -> dict: ...
    def search(self, text: str, **kw) -> dict: ...

    # --- I6 ---
    def list_concepts(self, **kw) -> list: ...
    def list_actions(self, concept: str | None = None) -> list: ...
    def describe_action(self, qualified: str) -> dict: ...
    def find_by_capability(self, need: str, **kw) -> list: ...
```

**返回值必须是规范定义的原始结构**（dict / list），不要包装成文本。

---

## 测什么

用例直接对应规范条款，分三组：

### I4 组（17 项）

| 类别 | 覆盖条款 |
|---|---|
| 定义校验 | D-1 引用未声明的概念须拒绝 · D-2 `effects` 非空 · D-3 排除项 |
| 阶段顺序 | **S-1 权限早于前置条件** · S-3 参数失败不得读目标 |
| 原子性 | A-2 前置条件同快照 · A-4 不部分生效 |
| 幂等 | I-2 重放返回原结果 · I-3 作用域 |
| 并发 | C-2 版本冲突 |
| 审计 | R-1 同事务 · R-4 定义哈希 · R-5 快照 |
| **§8 验收样本** | **9 条全部** |
| 多实例（v0.2） | M-2 未声明的 applies_to 须拒绝 · M-5 原子性覆盖全部目标 · M-8 `on` 键陷阱 |
| null 语义（v0.2） | N-1 绑定 null · N-3 未知判为未通过 · N-4 `is null` |

### I3 组（12 项）

| 类别 | 覆盖条款 |
|---|---|
| 派生 | D-1 不动点 · D-2 不落库 · D-3 不支持的表达式须报错 |
| 溯源 | **§3.2 `via` 必填** · premises 真实性 |
| 预算 | **Q-1 截断显式** |
| 遍历 | T-2 环终止 · T-3 返回路径 |
| 检索 | S-2 标明命中字段 |
| 通用 | Q-3 顺序确定 |

### I6 组（11 项）

| 类别 | 覆盖条款 |
|---|---|
| 枚举 | G1 完整枚举（概念数须等于本体里的数量） |
| 描述 | **E-2 `DescribeAction` 须返回足以构造提交请求的完整契约** |
| 查找 | **F-3 `matched_on` 必填** · F-6 无匹配返回空 · F-1 概念筛选 |
| 保证 | G4 确定性 · **G5 无副作用** |

---

## 一致性等级

| 等级 | 要求 |
|---|---|
| **I4-min/Core** | I4 组全过 |
| **I3-min/Core** | I3 组全过 |
| **I6-min/Core** | I6 组全过 |

**Plus 等级不在此套件内** —— 它们要求 SHOULD 条款
（CEL、向量检索、CloudEvents），无法用统一用例判定。

---

## 设计取舍

| 取舍 | 理由 |
|---|---|
| **适配器用 Python 类，不用 HTTP** | 规范没有定义传输绑定（属实现自定）。用类接口能让测试直接跑，不必先约定线协议 |
| **用例写在 runner 里，不拆 YAML** | 最小版够用；拆成声明式 YAML 是 v0.2 的事 |
| **只测 MUST** | SHOULD 无法用统一用例判定，强行测会误伤 |

**⚠️ 已知局限**：适配器协议本身**不是**规范的一部分。
它是为了让测试能跑而临时约定的。真正的规范级一致性测试需要先定义 I4/I3/I6 的**传输绑定**。

---

## 许可

[Apache License 2.0](../LICENSE)
