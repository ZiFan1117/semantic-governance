# I4 动作接口 · 最小规范

| 字段 | 值 |
|---|---|
| **版本** | v0.1（草案） |
| **状态** | 征求意见 |
| **规范等级** | **Normative**（含 MUST / MUST NOT / SHOULD） |
| **上级文档** | [`../docs/framework.md`](../docs/framework.md) §13 |
| **里程碑** | v0.3 |
| **对应 Issue** | #3 |

---

## 0. 范围

### 0.1 本规范解决什么

框架 §13 给出了 I4 的**候选设计**（要素清单），但没有给出**可实现、可测试的规范**。

**本规范是该问题的第一步：定义「最小 I4」——一个足够窄、可以真正实现和验收的子集。**

### 0.2 在范围内

| # | 内容 |
|---|---|
| 1 | 动作的**描述格式**（声明式） |
| 2 | **提交**的接口与执行阶段 |
| 3 | **原子性**边界（单实例） |
| 4 | **幂等** |
| 5 | **并发**（乐观） |
| 6 | **结果**格式（成功 / 拒绝 / 失败） |
| 7 | **审计记录**格式 |

### 0.3 明确不在范围内

> **不在范围内 ≠ 不重要，而是"留给下一步"。** 排除它们是为了让 v0.1 能真正落地。

| 排除项 | 为什么排除 | 何时做 |
|---|---|---|
| **多实例事务** | 原子性边界会变复杂（跨实例、跨概念） | v0.2 |
| **异步执行** | 引入状态机与回调 | v0.3 |
| **副作用**（通知 / webhook / 触发下游） | 引入外部依赖与补偿 | v0.3 |
| **长事务补偿（Saga）** | 依赖异步 | v0.3 |
| **声明式权限模型** | 已有标准（OpenFGA），本规范只要求"必须校验" | —— |
| **动作的发现与检索** | 属 I6 | —— |

**⚠️ 实现者注意**：本规范**不禁止**实现这些能力，但**不得声称**它们受本规范约束。

### 0.4 一个动作在本规范下的形态

```
一个主体，对一个目标实例，提交一次同步的、只改该实例的动作，
得到确定的结果，并留下一条不可变的审计记录。
```

---

## 1. 术语

> 术语与 [`../docs/framework.md`](../docs/framework.md) §4 术语表一致。以下是本规范新增或收紧的。

| 术语 | 定义 |
|---|---|
| **动作定义**（Action Definition） | 一份声明，描述一个动作的作用对象、参数、前置条件与效果 |
| **目标实例**（Target Instance） | 动作作用的那一个实例。**最小 I4 中，一次提交有且仅有一个** |
| **主体**（Actor） | 提交动作的身份（人 / 服务 / Agent） |
| **阶段**（Stage） | 执行过程中的一个检查或操作步骤，见 §3.2 |
| **拒绝**（Rejection） | 因不满足某个**已声明**的条件而未执行。**不是错误** |
| **失败**（Failure） | 因系统原因（存储不可用等）未能完成。**是错误** |
| **快照标识**（Snapshot ID） | 一致性读所依据的数据版本标识 |
| **幂等键**（Idempotency Key） | 用于识别重复提交的调用方提供的标识 |

**⚠️ "拒绝"与"失败"必须区分：**

- **拒绝** = 系统的**正常行为**，说明调用方需要改变输入或状态
- **失败** = 系统的**异常状态**，调用方可以重试同一个请求

混淆两者会导致调用方做错误的处理（对拒绝无限重试，或对失败不重试）。

---

## 2. 动作描述格式

### 2.1 结构

动作定义使用 **YAML**（与 Ossie 一致）。

```yaml
action:
  name: <动作名，域名内唯一>
  namespace: <命名空间，见 framework §1.1>
  version: <定义版本>
  description: <人读说明>
  ai_context: <给 Agent 的说明，可选>

  target:
    concept: <目标实例的概念名>
    reads: [<动作会读取的概念名>]

  parameters:
    - name: <参数名>
      type: <类型>
      required: <bool>
      description: <说明>
      constraints: [<表达式>]

  permissions:
    relation: <关系名>        # 交由外部授权系统判定
    resource: "${target}"

  preconditions:
    - id: <稳定标识，用于拒绝信息回引>
      expression: <表达式>
      message: <人读说明>

  effects:
    - <变更操作>

  idempotency:
    key: <表达式，用于计算幂等键>

  # 以下字段在本规范中 MUST 为空 / false
  side_effects: []
  async: false
```

### 2.2 字段定义

| 字段 | 必填 | 说明 |
|---|---|---|
| `name` | ✅ | 动作名。命名空间内唯一 |
| `namespace` | ✅ | 命名空间。**用于解析权限与归属** |
| `version` | ✅ | 定义版本。审计记录 MUST 引用它 |
| `description` | ✅ | 人读说明 |
| `ai_context` | ❌ | 给 Agent 的上下文。**建议填写**（对应框架 §22 Agent-first） |
| `target.concept` | ✅ | 目标实例所属概念。**MUST** 在 L3 中已定义 |
| `target.reads` | ✅ | 动作会读取的概念集合。**用于影响分析**（`G-6`） |
| `parameters` | ❌ | 参数列表。无参数时省略 |
| `permissions.relation` | ✅ | 权限关系名。**引用**外部授权系统，不在本规范定义 |
| `preconditions` | ❌ | 前置条件列表 |
| `effects` | ✅ | 变更操作列表。**MUST NOT 为空**（否则不是动作） |
| `idempotency.key` | ✅ | 幂等键计算表达式 |
| `side_effects` | ✅ | **MUST 为空数组**（最小 I4 排除副作用） |
| `async` | ✅ | **MUST 为 `false`** |

### 2.3 表达式语言

| # | 条款 |
|---|---|
| **E-1** | 实现 **MUST** 在文档中声明所支持的表达式语言 |
| **E-2** | 表达式语言 **MUST** 至少支持：比较运算、布尔组合、目标实例属性引用 |
| **E-3** | 实现 **SHOULD** 使用 **CEL**（[Common Expression Language](https://github.com/google/cel-spec)） |

**为什么推荐 CEL**：它已是 OpenFGA 条件表达式的语言（框架 §13.5 采用 OpenFGA），
多个语言有实现，且**求值必然终止**（无循环）—— 这对动作热路径很重要。

**表达式上下文（MUST 提供）：**

| 变量 | 含义 |
|---|---|
| `target` | 目标实例。属性按 L3 定义的名字访问 |
| `actor` | 提交主体标识 |
| `<参数名>` | 已校验通过的参数值 |
| `NOW()` | 当前时刻（**MUST** 在一次提交内恒定） |

**⚠️ `NOW()` 的确定性要求**：同一次提交内多次求值 **MUST** 返回同一值，
否则前置条件与效果可能基于不同时刻，产生不一致。

### 2.4 与 Ossie（L3）的关联

| 本规范引用 | 指向 Ossie 的什么 |
|---|---|
| `target.concept` | `concept` |
| `target.reads` | `concept` 集合 |
| `parameters[].type` | `ValueType` 或内置类型 |
| `parameters[].constraints` | 与 `requires` 同语法的表达式 |
| 表达式中的属性访问 | `concept` 的 `properties` |
| 表达式中的关系遍历 | `relationships` 的点连接语法 |

> **动作定义 MUST 引用 L3 中已声明的概念。** 引用未声明的概念 **MUST** 在定义校验阶段被拒绝。

---

## 3. 提交语义

### 3.1 接口

```
SubmitAction(
    action_name,        # 命名空间 + 名 + 版本
    target_ref,         # 目标实例引用
    parameters,         # 参数值
    idempotency_key,    # 幂等键
    expected_version    # 可选：乐观并发控制的期望版本
) → Result
```

### 3.2 执行阶段

> **阶段顺序为规范性要求。** 顺序影响拒绝时的错误信息质量与副作用范围。

| # | 阶段 | 做什么 | 失败时 |
|---|---|---|---|
| 1 | **解析定义** | 按 `action_name` 取动作定义（固定版本） | 失败（定义不存在） |
| 2 | **参数校验** | 类型、必填、`constraints` | 拒绝（`stage: parameter`） |
| 3 | **目标解析** | 取目标实例；不存在则拒绝 | 拒绝（`stage: target`） |
| 4 | **权限校验** | 交由授权系统判定 | 拒绝（`stage: permission`） |
| 5 | **空转检查** | 若同幂等键已成功 → 返回原结果 | 返回原结果 |
| 6 | **前置条件** | 求值全部 `preconditions` | 拒绝（`stage: precondition`） |
| 7 | **并发检查** | 若提供 `expected_version` 且不匹配 | 拒绝（`stage: conflict`） |
| 8 | **应用效果** | 执行 `effects` | 失败 |
| 9 | **写审计** | 与阶段 8 同事务 | 失败（整体回滚） |
| 10 | **返回结果** | | |

**条款：**

| # | 条款 |
|---|---|
| **S-1** | 阶段顺序 **MUST** 如表中所示。特别是：**权限校验 MUST 早于前置条件校验** |
| **S-2** | 前置条件求值 **MUST** 在**同一快照**上进行（见 §3.3） |
| **S-3** | 参数校验失败 **MUST NOT** 触发任何读取目标实例的操作 |

**为什么权限必须早于前置条件**：前置条件的表达式可能泄露目标实例的内容
（如"订单已发货，不可取消"暴露了订单状态）。**权限没通过就不该让它探知状态。**

### 3.3 原子性与快照

| # | 条款 |
|---|---|
| **A-1** | 阶段 6~9 **MUST** 在**同一事务**内 |
| **A-2** | 阶段 6 的所有前置条件求值 **MUST** 基于**同一快照** |
| **A-3** | 快照标识 **MUST** 记录进审计记录（见 §5） |
| **A-4** | 事务失败时，阶段 8 的变更 **MUST NOT** 部分生效 |

**关于 A-2（这是框架 §8.1 R1 的具体化）：**

> 若前置条件 P1 与 P2 分别基于不同时刻的数据求值，
> 则可能出现"P1 成立、P2 成立，但两者不能同时成立"的情况。
> **快照一致是前置条件有意义的前提。**

### 3.4 幂等

| # | 条款 |
|---|---|
| **I-1** | 调用方 **MUST** 提供幂等键 |
| **I-2** | 相同幂等键的重复提交 **MUST** 返回**原结果**，**MUST NOT** 重复执行效果 |
| **I-3** | 幂等键的作用域 **MUST** 至少覆盖：动作名 + 目标实例 + 幂等键值 |
| **I-4** | 幂等记录的保留期 **MUST** 被声明 |

**关于 I-3**：若不限定作用域，不同动作或不同实例可能撞键，
导致"合法的第二次提交被当成重复"—— 这是静默的错误，比报错更危险。

**幂等键的计算**：`idempotency.key` 是**默认值**；调用方 **MAY** 覆盖它。

### 3.5 并发

最小 I4 **只要求乐观并发**。

| # | 条款 |
|---|---|
| **C-1** | 目标实例 **MUST** 有版本标识（或等价的变更序号） |
| **C-2** | 调用方 **MAY** 提供 `expected_version`；不匹配时 **MUST** 拒绝（`stage: conflict`） |
| **C-3** | 不提供 `expected_version` 时，实现 **MUST** 声明其并发语义（如"后写覆盖"） |

**为什么不做悲观锁**：它会引入死锁与超时的运维负担，
而最小 I4 的目标是"先能跑通"。**乐观并发足够，且失败信息明确（可重试）。**

---

## 4. 结果格式

> **结果 MUST 是结构化的。** （对应框架 §20.8 `A-1`）

### 4.1 成功

```json
{
  "outcome": "succeeded",
  "action": "urn:sem:acme:supply:cancel_order@1.2.0",
  "target": "urn:sem:acme:supply:Order:12345",
  "record_id": "01J8Z...",
  "applied": [
    { "path": "status", "value": "cancelled" },
    { "path": "cancelled_at", "value": "2026-09-12T14:30:00Z" }
  ],
  "new_version": 7,
  "snapshot": "snap-01J8Z..."
}
```

### 4.2 拒绝

> **拒绝信息 MUST 足以让调用方自动纠正。**（对应框架 §20.8 `A-2`）

```json
{
  "outcome": "rejected",
  "stage": "precondition",
  "code": "PRECONDITION_FAILED",
  "action": "urn:sem:acme:supply:cancel_order@1.2.0",
  "target": "urn:sem:acme:supply:Order:12345",
  "violations": [
    {
      "id": "P2",
      "message": "订单已发货，不可取消",
      "expression": "NOT EXISTS(Shipment WHERE order == target AND status == 'shipped')",
      "actual": { "shipment.status": "shipped", "shipment.id": "SH-9981" }
    }
  ],
  "suggestions": [
    { "action": "urn:sem:acme:supply:return_order@1.0.0",
      "reason": "已发货订单应走退货流程" }
  ],
  "retryable": false,
  "record_id": "01J8Z..."
}
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `outcome` | ✅ | 固定 `rejected` |
| `stage` | ✅ | 哪个阶段拒的：`parameter` / `target` / `permission` / `precondition` / `conflict` |
| `code` | ✅ | 机器可判的枚举码 |
| `violations[].id` | ✅ | **回引到动作定义里的 `preconditions[].id`** |
| `violations[].message` | ✅ | 人读说明（**直接取自定义，不由实现临时编**） |
| `violations[].actual` | ❌ | 实际值。**强烈建议提供** —— 这是自纠的关键 |
| `suggestions` | ❌ | 建议的替代动作 |
| `retryable` | ✅ | 调用方能否原样重试 |

### 4.3 失败

```json
{
  "outcome": "failed",
  "code": "STORE_UNAVAILABLE",
  "message": "事实层不可用",
  "retryable": true
}
```

**区分规则：**

| | 拒绝 | 失败 |
|---|---|---|
| 原因 | 输入或状态不满足**已声明**条件 | 系统异常 |
| 可重试 | **视 `retryable` 而定**（一般 false） | **一般 true** |
| 是否产生变更 | 否（保证） | 否（保证，靠事务） |
| 审计 | **MUST 记录** | **MUST 记录** |

---

## 5. 审计记录

### 5.1 字段

> **每次提交（成功 / 拒绝 / 失败）MUST 产生一条不可变记录。**

```json
{
  "record_id": "01J8Z...",
  "timestamp": "2026-09-12T14:30:00.123Z",

  "action": "urn:sem:acme:supply:cancel_order",
  "action_version": "1.2.0",
  "definition_hash": "sha256:...",

  "target": "urn:sem:acme:supply:Order:12345",
  "parameters": { "reason": "customer_request" },

  "actor": { "type": "user", "id": "user:anne" },

  "outcome": "succeeded",
  "stage": null,
  "violations": [],

  "based_on": {
    "snapshot": "snap-01J8Z...",
    "read_concepts": ["Order", "Shipment"]
  },

  "applied": [ "..." ],
  "before_version": 6,
  "after_version": 7,

  "trace_id": "...",
  "request_id": "..."
}
```

### 5.2 关于 `based_on` —— 本规范对"基于什么"的回答

框架 §13.3 要求审计记录包含"**基于什么**"，但没说怎么记。
**记录全部读取集是不现实的**（不可枚举、开销大）。

**本规范的设计：记录快照标识，而非读取明细。**

| 方案 | 可行性 | 可重现性 |
|---|---|---|
| 记录完整读取集 | ❌ 读取不可枚举（遍历、派生） | 高 |
| **记录快照标识** | ✅ 一个值 | **高** —— 可对快照重放 |
| 什么都不记 | ✅ | ❌ **无法回答"为什么批准"** |

> **"基于什么" = "基于哪个数据快照" + "读了哪几类概念"。**
> 前者让决策可重现，后者让影响分析可做。

### 5.3 条款

| # | 条款 |
|---|---|
| **R-1** | 成功路径：审计记录 **MUST** 与效果写入在**同一事务**内 |
| **R-2** | 拒绝 / 失败路径：**MUST 也产生记录**；因无变更，其原子性要求弱于 R-1 |
| **R-3** | 审计记录 **MUST NOT** 可被修改或删除 |
| **R-4** | 记录 **MUST** 含 `definition_hash` —— 定义被改过也能知道当时执行的是哪一版 |
| **R-5** | 记录 **MUST** 含 `based_on.snapshot` |
| **R-6** | 实现 **SHOULD** 用 **CloudEvents** 格式对外发布审计事件（框架 §13.5） |

**关于 R-4**：`action_version` 是语义版本，可能被复用（如错误地原地改定义）。
`definition_hash` 是内容哈希，**唯一确定执行的是哪一份定义**。
两者都要，前者给人看，后者用来验证。

---

## 6. 规范性条款汇总

| 组 | 条款 |
|---|---|
| **定义** | D-1 定义 MUST 引用 L3 中已声明的概念<br>D-2 `effects` MUST NOT 为空<br>D-3 `side_effects` MUST 为空数组，`async` MUST 为 false |
| **表达式** | E-1 声明所用语言 · E-2 最低能力 · E-3 SHOULD 用 CEL<br>E-4 同一次提交内 `NOW()` MUST 恒定 |
| **阶段** | S-1 顺序 MUST 固定，**权限早于前置条件**<br>S-2 前置条件 MUST 同快照<br>S-3 参数校验失败 MUST NOT 读取目标 |
| **原子性** | A-1 阶段 6~9 同事务 · A-2 同快照 · A-3 快照进审计 · A-4 不部分生效 |
| **幂等** | I-1 调用方 MUST 提供键 · I-2 重复 MUST 返回原结果 · I-3 作用域 MUST 足够 · I-4 保留期 MUST 声明 |
| **并发** | C-1 实例 MUST 有版本 · C-2 版本不匹配 MUST 拒绝 · C-3 无版本时 MUST 声明语义 |
| **结果** | R-0 结果 MUST 结构化<br>成功/拒绝/失败三种形态 · 拒绝 MUST 含 `violations[].id` 与 `retryable` |
| **审计** | R-1 成功同事务 · R-2 拒绝也记 · R-3 不可改 · R-4 含定义哈希 · R-5 含快照 · R-6 SHOULD 用 CloudEvents |

---

## 7. 完整示例

### 7.1 动作定义

```yaml
action:
  name: cancel_order
  namespace: urn:sem:acme:supply
  version: 1.2.0
  description: 取消一个尚未发货的订单
  ai_context: "当客户要求取消订单时使用。仅对未发货订单有效。"

  target:
    concept: Order
    reads: [Order, Shipment, Customer]

  parameters:
    - name: reason
      type: String
      required: true
      description: 取消原因
    - name: refund_amount
      type: Decimal
      required: false
      constraints: [ "refund_amount >= 0" ]

  permissions:
    relation: can_cancel
    resource: "${target}"

  preconditions:
    - id: P1
      expression: "target.status == 'pending'"
      message: "只有待处理订单可以取消"
    - id: P2
      expression: "!target.shipments.exists(s, s.status == 'shipped')"
      message: "订单已发货，不可取消"

  effects:
    - set: { path: "status", value: "'cancelled'" }
    - set: { path: "cancel_reason", value: "reason" }
    - set: { path: "cancelled_at", value: "NOW()" }

  idempotency:
    key: "target.id + ':' + reason"

  side_effects: []
  async: false
```

### 7.2 成功提交

```
SubmitAction(
  action_name  = "urn:sem:acme:supply:cancel_order@1.2.0",
  target_ref   = "urn:sem:acme:supply:Order:12345",
  parameters   = { reason: "customer_request" },
  idempotency_key = "auto:Order:12345:customer_request"
)
```

→ `outcome: succeeded`，审计记录含 `snapshot: snap-01J8Z...`

### 7.3 被拒绝的提交

同一订单，但已有已发货的 Shipment：

```json
{
  "outcome": "rejected",
  "stage": "precondition",
  "code": "PRECONDITION_FAILED",
  "violations": [{
    "id": "P2",
    "message": "订单已发货，不可取消",
    "actual": { "shipment.id": "SH-9981", "shipment.status": "shipped" }
  }],
  "suggestions": [{ "action": "urn:sem:acme:supply:return_order@1.0.0",
                    "reason": "已发货订单应走退货流程" }],
  "retryable": false
}
```

**Agent 拿到这个结果能做什么**：看到 `stage=precondition`、`retryable=false`、
有 `suggestions` → **自动改走退货流程**。这就是可自纠。

---

## 8. 一致性等级

| 等级 | 要求 |
|---|---|
| **I4-min/Core** | 全部 MUST 条款 |
| **I4-min/Plus** | Core + 全部 SHOULD（CEL、`actual` 值、建议、CloudEvents） |

**验收方法**：框架 §19.1 的"**该被拒绝的样本集**"。

针对本规范，样本集 **MUST** 覆盖：

| # | 应被拒绝的情形 | 期望 `stage` |
|---|---|---|
| 1 | 参数类型错 | `parameter` |
| 2 | 必填参数缺失 | `parameter` |
| 3 | 参数违反 `constraints` | `parameter` |
| 4 | 目标实例不存在 | `target` |
| 5 | 无权执行 | `permission` |
| 6 | 前置条件 P1 不满足 | `precondition` |
| 7 | 前置条件 P2 不满足 | `precondition` |
| 8 | `expected_version` 不匹配 | `conflict` |
| 9 | 重复幂等键 | **不拒绝** —— 返回原结果 |

第 9 条特别重要：**幂等不是拒绝**，是返回原结果。写错会导致合法的重试被误判。

---

## 附：与完整 I4 的差距

| 能力 | 最小 I4 | 完整 I4 |
|---|---|---|
| 作用实例数 | 1 | N |
| 执行 | 同步 | 同步 + 异步 |
| 副作用 | ❌ | 声明式 |
| 补偿 | ❌ | Saga |
| 权限模型 | 引用外部 | 引用外部（同） |
| 并发 | 乐观 | 乐观 + 悲观 |
| 事务边界 | 单实例 | 多实例、可声明 |

**升级路径（建议）**：

```
v0.1（本规范）  单实例 · 同步 · 无副作用 · 有审计
   ↓
v0.2            多实例事务边界 + 跨概念原子性
   ↓
v0.3            异步 + 副作用声明 + 补偿
```

---

## 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1 | 2026-09 | 初稿。定义最小 I4：单实例、同步、无副作用、有审计 |

---

## 许可

[Apache License 2.0](../LICENSE)
