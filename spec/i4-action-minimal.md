# I4 动作接口 · 最小规范
<!-- clauses: ST AT ID CC AU EX BD RP MI NL XAD DF FD -->

| 字段 | 值 |
|---|---|
| **版本** | v0.2.4 |
| **状态** | 征求意见 |
| **规范等级** | **Normative**（含 MUST / MUST NOT / SHOULD） |
| **上级文档** | [`../docs/framework.md`](../docs/framework.md) §18 |
| **五要素落位** | 实现 **动作**（五要素中唯一能改变状态的）；规则以 `preconditions`（业务性）与 `parameters[].constraints`（结构性）为载体 |
| **本规范自有条款前缀** | `S-`（阶段）· `A-`（原子性）· `I-`（幂等）· `C-`（并发）· `R-`（审计）· `E-`（表达式语言）· `B-`（判据绑定）· `Q-`（重放）· `M-`（多实例）· `N-`（null）· `X-`（适配层）· `D-`（定义校验）· `F-`（字段） |
| **里程碑** | v0.3 |
| **对应 Issue** | #3 |

---

## 0. 范围

### 0.1 本规范解决什么

框架 §18 给出了 I4 的**候选设计**（要素清单），但没有给出**可实现、可测试的规范**。

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
  namespace: <命名空间，见框架 §1.1>
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
| `ai_context` | ❌ | 给 Agent 的上下文。**建议填写**（对应框架 §27 Agent-first） |
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

> **⚠️ v0.2.1 修正：不应自己发明或推荐外部语言 —— Ossie 已有表达式语言规范。**

Ossie 在 `core-spec/expression_language.md` 中定义了表达式语言
（**状态：Proposed Final**，工作组含 Snowflake / Databricks / dbt Labs / Starburst / Cube / Denodo 等）。

**它是 SQL 的一个子集**，而非通用表达式语言：

| 组成 | 内容 |
|---|---|
| SQL 子集 | 支持的构造 + 运算符优先级 + **明确列出不支持什么** |
| 聚合函数 | Core / Statistical / Percentile / Conditional（REQUIRED）+ Approximate（RECOMMENDED） |
| 日期时间函数 | 当前时刻 / 提取 / 截断 / 算术 / 构造 |
| 字符串函数 | 操作 / 搜索 / 格式化 |
| 命名空间与标识符解析 | 与 `ontology.yaml` 的概念/关系对齐 |

**条款：**

| # | 条款 |
|---|---|
| **EX-1** | 动作定义中的 `preconditions[].expression`、`parameters[].constraints`、`effects[].set.value` **MUST** 使用 **Ossie 表达式语言** |
| **EX-2** | 实现 **MUST** 声明其支持的 Ossie 表达式子集；**MUST NOT** 静默接受它不支持的构造 |
| **EX-3** | 在 Ossie 表达式语言定稿前，实现 **MAY** 支持其他语言（如 CEL）作为**过渡**，但 **MUST** 在文档中标注为偏离 |
| **EX-4** | 同一次提交内 `NOW()` 等时刻函数 **MUST** 恒定 |

**为什么这条修正重要：**

- 框架的原则是「**符合的部分用 Ossie**」。表达式出现在 `requires`、`derived_by`、
  以及本规范的 `preconditions` / `constraints` / `effects` 中 —— **它属于 Ossie 的地盘**。
- 自己推荐 CEL，会造成**同一个语义层里两套表达式语言**（Ossie 的规则用 SQL 子集，
  动作的前置条件用 CEL），这是人为制造的割裂。
- 而且 Ossie 的表达式语言**明确对齐本体标识符**（`concept` / `relationship` 的命名空间解析），
  这是通用语言（CEL）做不到的。

**⚠️ 已知偏离（历史记录）**：本仓库早期附带的一份实现曾用 **CEL 子集**，
因为它在 Ossie 表达式语言定稿前写成。**这是规范允许的过渡态，当时已标注为偏离。**
（该实现已从仓库移除；此条保留是为了说明"为什么本规范把表达式的选择权交给实现"。）

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

### 2.5 判据绑定（`BD-1`~`BD-6`）

> **本节回答一个实现必然撞到的问题：`preconditions[].expression` 由谁求值？**

规范给的答案是"表达式语言"（§2.3）。但工程实现里，前置条件常常**不是**由表达式引擎求值的，
而是绑到一个已注册的**判据**（criterion）上：

- 为一条规则引入整套 parser/evaluator 并不划算；
- 规则本身需要能被**单元测试直接调用**；
- 有些规则（如"这个珠子名在库内"）本质是查表，写成 SQL 反而更别扭。

**判据**因此是：**声明式意图（`expression`）+ 命令式实现（绑定的求值体）**。

| 编号 | 级别 | 条款 |
|---|---|---|
| **BD-1** | MUST | 每个动作 **MUST** 声明至少一条前置条件；确实不需要时 **MUST** 显式给出理由。**MUST NOT** 存在"沉默的无门禁动作" |
| **BD-2** | MUST | 前置条件引用的判据 **MUST** 已绑定；绑定关系 **MUST** 在**构建期**（定义注册/校验时）检查，**MUST NOT** 留到运行期才发现 |
| **BD-3** | MUST | 求值不了的判据 **MUST** 硬错误，**MUST NOT** 视为通过。放行一个"求值不了的前置条件"等于门禁形同虚设 |
| **BD-4** | MUST | 每条判据 **MUST** 携带规范 `expression`，即使实现走绑定路径。否则跨实现无法比对，`expression` 会退化成注释 |
| **BD-5** | MUST | **结构性**规则（类型、长度、取值范围）**MUST** 只在 `parameters[].constraints` 声明；**业务性**规则 **MUST** 只在 `preconditions` 声明。同一规则 **MUST NOT** 两处各写一份 |
| **BD-6** | SHOULD | 绑定与 `expression` **SHOULD** 由一致性测试在同一组样本上比对；未被任何动作引用的判据 **SHOULD** 被检出（死判据） |

**为什么 `BD-4` 是 MUST**：允许"只有绑定、没有 `expression`"，等于允许每个实现各自定义语义——
那就不再是**互操作规范**，只是各自的内部实现。

**为什么 `BD-3` 要写成硬错误而不是拒绝**：这不是"调用方做错了"，是"**部署配错了**"。
降级成一次正常拒绝，会让配置错误伪装成业务拒绝，在监控里看起来"系统在正常工作"。

**为什么 `BD-5` 是 MUST**（来自实现事故）：某实现把"summary ≤ 50 字"同时写成
`parameters[].constraints.maxLength` **和**一条判据。后果有两层：

1. **两个真源**：改一处忘另一处，两条规则开始漂移；
2. **判据成了死代码**：阶段 2（参数校验）永远先命中，阶段 6 的那条判据**从未被求值**——
   测试看不到它、覆盖率看不到它，但它在代码里"看起来门禁在这儿"。

这类"看起来在工作、实际从不执行"的门禁，比没有门禁更危险。

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
| **ST-1** | 阶段顺序 **MUST** 如表中所示。特别是：**权限校验 MUST 早于前置条件校验** |
| **ST-2** | 前置条件求值 **MUST** 在**同一快照**上进行（见 §3.3） |
| **ST-3** | 参数校验失败 **MUST NOT** 触发任何读取目标实例的操作 |
| **ST-4** | 阶段 8 的效果写入 **MUST** 在**写入路径**上强制 L3 声明的 multiplicity 约束，**MUST NOT** 只在读取时校验（见 §9.1） |

**为什么权限必须早于前置条件**：前置条件的表达式可能泄露目标实例的内容
（如"订单已发货，不可取消"暴露了订单状态）。**权限没通过就不该让它探知状态。**

### 3.3 原子性与快照

| # | 条款 |
|---|---|
| **AT-1** | 阶段 6~9 **MUST** 在**同一事务**内 |
| **AT-2** | 阶段 6 的所有前置条件求值 **MUST** 基于**同一快照** |
| **AT-3** | 快照标识 **MUST** 记录进审计记录（见 §5） |
| **AT-4** | 事务失败时，阶段 8 的变更 **MUST NOT** 部分生效 |

**关于 AT-2（这是框架 §18.1 R1 的具体化）：**

> 若前置条件 P1 与 P2 分别基于不同时刻的数据求值，
> 则可能出现"P1 成立、P2 成立，但两者不能同时成立"的情况。
> **快照一致是前置条件有意义的前提。**

### 3.4 幂等

| # | 条款 |
|---|---|
| **ID-1** | 调用方 **MUST** 提供幂等键 |
| **ID-2** | 相同幂等键的重复提交 **MUST** 返回**原结果**，**MUST NOT** 重复执行效果 |
| **ID-3** | 幂等键的作用域 **MUST** 至少覆盖：动作名 + 目标实例 + 幂等键值 |
| **ID-4** | 幂等记录的保留期 **MUST** 被声明 |
| **RP-1** | 命中幂等键的重放 **MUST** 在审计中留痕，并 **MUST** 与"真实变更"可区分 |
| **RP-2** | 重放返回的 `record_id` **MUST** 是**原变更的** `record_id`，**MUST NOT** 生成新的 |
| **RP-3** | 审计记录 **MUST** 能区分「**本次调用**的 id」与「本次调用对应的**变更** id」，两者 **MUST NOT** 被同一个字段名兼任 |

**关于 ID-3**：若不限定作用域，不同动作或不同实例可能撞键，
导致"合法的第二次提交被当成重复"—— 这是静默的错误，比报错更危险。

**幂等键的计算**：`idempotency.key` 是**默认值**；调用方 **MAY** 覆盖它。

**关于 RP-1 / RP-2 —— 本规范此前未定义"重放要不要记审计"**

这是实现逼出来的缺口：阶段 5 说"返回原结果"，§5 说"每次提交 MUST 产生一条记录"，
两句话放在一起就矛盾了——重放算不算一次"提交"？

本规范现在明确：**审计记录的是「调用」，不是「变更」**。

| 视角 | 记录什么 | 适合 |
|---|---|---|
| **调用视角**（本规范采用） | 每次调用都留痕，重放标 `replayed: true` | 排查"谁在什么时候试图做什么" |
| 变更视角 | 只记真实变更 | 排查"状态被改成了什么" |

采用调用视角的理由：**"谁在重试"本身就是需要被看见的信息**——
一个客户端在短时间内重放 1000 次，是故障信号；
若重放不留痕，这个信号在审计里**完全不可见**。

`record_id` 仍只标识**那一次真实变更**（`RP-2`），因此两种视角可以同时满足：
审计条数 = 调用次数，`record_id` 去重后 = 变更次数。

**关于 RP-3 —— 一个字段名干了两件事**

`RP-2` 说"重放返回原 `record_id`"，于是同一个名字在两个地方指代不同的东西：

| 出现位置 | 指的是 |
|---|---|
| 返回结果的 `record_id` | 那次**变更** |
| 审计记录的 `record_id`（§5.1） | 那次**调用** |

重放时二者必然不同，而调用方**没有任何办法区分**自己拿到的是哪一种。
更糟的是：审计行看起来"有 id 可以查"，实际 `find(结果里的 record_id)` 查到的是**别的一行**。

`RP-3` 要求把两者拆开。一种做法是给审计记录增加一个 `change_record_id`：

```jsonc
// 第一次调用
{ "record_id": "rec1", "outcome": "succeeded", "change_record_id": "rec1" }
// 重放（同参数）
{ "record_id": "rec2", "outcome": "succeeded", "replayed": true, "change_record_id": "rec1" }
//          ↑ 本次调用           ↑ 审计条数=调用数              ↑ 去重后=变更数
```

于是两个问题都有确定答案，不需要调用方猜：
「这次调用做了什么？」→ 看 `record_id`；「状态被改过几次？」→ `change_record_id` 去重。

### 3.5 并发

最小 I4 **只要求乐观并发**。

| # | 条款 |
|---|---|
| **CC-1** | 目标实例 **MUST** 有版本标识（或等价的变更序号） |
| **CC-2** | 调用方 **MAY** 提供 `expected_version`；不匹配时 **MUST** 拒绝（`stage: conflict`） |
| **CC-3** | 不提供 `expected_version` 时，实现 **MUST** 声明其并发语义（如"后写覆盖"） |

**为什么不做悲观锁**：它会引入死锁与超时的运维负担，
而最小 I4 的目标是"先能跑通"。**乐观并发足够，且失败信息明确（可重试）。**

---

## 4. 结果格式

> **结果 MUST 是结构化的。** （对应框架 §25.8 `AT-1`）

> **本节所有字面量 MUST 逐字实现，MUST NOT 自定。**
> 实现踩过一次：`outcome` 写成 `"ok"` 而规范是 `"succeeded"`。
> 语义上无歧义，但**任何跨实现的机器判定都会失效**——
> 这类错误不会被类型系统、也不会被自己的单元测试发现，只会被**一致性测试**发现。
> 建议实现把三态字面量集中到**一个**常量处，并在测试里与规范逐条比对。

> **⚠️ 规范自身的一处不一致（待 v0.3 收敛）**：
> §4.2 的拒绝里动作身份是**合成**的 `urn:sem:acme:supply:cancel_order@1.2.0`，
> 而 §5.1 的审计里拆成 `action` + `action_version` 两个字段。
> 同一个身份两种写法，调用方要写两套解析。
> 本版暂不裁决，要求实现**各按各处照做**；v0.3 应统一（倾向 §5.1 的拆法，
> 因为审计需要按"动作名跨版本"聚合）。

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

> **拒绝信息 MUST 足以让调用方自动纠正。**（对应框架 §25.8 `AT-2`）

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

### 4.3 拒绝 MUST 穿过适配层

> 这条来自实现，不是设计出来的：**原子层做对了，端到端仍然是错的。**

`Rejection` 在到达调用方之前，通常还要穿过一层**适配器**——MCP 工具声明、
HTTP 响应包装、SDK 结果类型、Agent 框架的工具 `output.schema`。
这些层普遍用 `additionalProperties: false` 或定长结构体，
**未声明的字段会被静默丢弃**。

| 编号 | 级别 | 条款 |
|---|---|---|
| **XAD-1** | MUST | 动作的输出契约（含工具 / 接口 schema）**MUST** 显式声明拒绝形状；**MUST NOT** 依赖"多出来的字段会自动带过去" |
| **XAD-2** | MUST | 适配层 **MUST NOT** 把 `Rejection` 降级为一条自然语言字符串；若同时给人读摘要，摘要 **MUST** 是可丢弃的派生字段 |
| **XAD-3** | SHOULD | 拒绝文案 **SHOULD** 带 `stage` / `code` / `violations[].id`，并 **SHOULD** 按 `retryable` 区分"改正后可重试"与"原样重试会再失败" |

**为什么是 MUST 而不是 SHOULD**：丢弃是**静默**的。
调用方拿到的是"成功的空结果"而非"失败"——这比报错更糟：
既不触发重试，也不触发自纠，错误会继续往下走。

**反面样张（真实事故，来自 bazidiy 实战实现 S1）**：

```ts
// 原子：正确返回结构化拒绝
return { slots: [], rejection: parsed, note: summarize(parsed) }

// 工具：output.schema 是 additionalProperties:false，且没声明 rejection
//   → 适配层丢掉 rejection，只留 note（而 note 已弃用）
// LLM 实际收到：{ type:'design_result', slots: [] }   ← 看起来"成功"，方案是空的
```

**自检（可机器执行）**：

```text
实现能返回的字段集合  ⊆  输出 schema 声明的字段集合
```

两个集合都能在运行期取到（前者 `Object.keys(result)`，后者解析 schema 声明），
因此这条 **SHOULD** 纳入一致性测试常驻执行。

### 4.4 失败

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

框架 §18.3 要求审计记录包含"**基于什么**"，但没说怎么记。
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
| **AU-1** | 成功路径：审计记录 **MUST** 与效果写入在**同一事务**内 |
| **AU-2** | 拒绝 / 失败路径：**MUST 也产生记录**；因无变更，其原子性要求弱于 AU-1 |
| **AU-3** | 审计记录 **MUST NOT** 可被修改或删除 |
| **AU-4** | 记录 **MUST** 含 `definition_hash` —— 定义被改过也能知道当时执行的是哪一版 |
| **AU-5** | **若本次提交发生了任何对事实层的读取**，记录 **MUST** 含 `based_on.snapshot`；未发生读取的早期拒绝（参数/目标/权限），`based_on` **MUST** 存在但 `snapshot` **MAY** 为 null（见 §9.2） |
| **AU-6** | 实现 **SHOULD** 用 **CloudEvents** 格式对外发布审计事件（框架 §18.5） |

**关于 AU-4**：`action_version` 是语义版本，可能被复用（如错误地原地改定义）。
`definition_hash` 是内容哈希，**唯一确定执行的是哪一份定义**。
两者都要，前者给人看，后者用来验证。

---

## 6. 规范性条款汇总

| 组 | 条款 |
|---|---|
| **定义** | DF-1 定义 MUST 引用 L3 中已声明的概念<br>DF-2 `effects` MUST NOT 为空<br>DF-3 `side_effects` MUST 为空数组，`async` MUST 为 false |
| **表达式** | EX-1 声明所用语言 · EX-2 最低能力 · EX-3 SHOULD 用 CEL<br>EX-4 同一次提交内 `NOW()` MUST 恒定 |
| **阶段** | ST-1 顺序 MUST 固定，**权限早于前置条件**<br>ST-2 前置条件 MUST 同快照<br>ST-3 参数校验失败 MUST NOT 读取目标 |
| **原子性** | AT-1 阶段 6~9 同事务 · AT-2 同快照 · AT-3 快照进审计 · AT-4 不部分生效 |
| **幂等** | ID-1 调用方 MUST 提供键 · ID-2 重复 MUST 返回原结果 · ID-3 作用域 MUST 足够 · ID-4 保留期 MUST 声明 |
| **并发** | CC-1 实例 MUST 有版本 · CC-2 版本不匹配 MUST 拒绝 · CC-3 无版本时 MUST 声明语义 |
| **结果** | AU-0 结果 MUST 结构化<br>成功/拒绝/失败三种形态 · 拒绝 MUST 含 `violations[].id` 与 `retryable` |
| **审计** | AU-1 成功同事务 · AU-2 拒绝也记 · AU-3 不可改 · AU-4 含定义哈希 · AU-5 含快照 · AU-6 SHOULD 用 CloudEvents |

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

**验收方法**：框架 §28.1 的"**该被拒绝的样本集**"。

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

**另有两条针对 §4.3 适配层的断言**（不是"应被拒绝的情形"，而是**拒绝有没有送到**）：

| # | 断言 | 期望 |
|---|---|---|
| 10 | 取实现返回值的字段集合，与输出 schema 声明的字段集合比对 | **前者 ⊆ 后者**（`XAD-1`） |
| 11 | 经适配层后调用方拿到的结果 | 仍能读到 `stage` / `code` / `violations`（`XAD-2`） |

第 10 条是**运行期可判定**的（两个集合都能取到），因此 **SHOULD** 常驻在一致性测试里，
而不是靠人审 schema——本规范 v0.2.2 增补 §4.3 的直接原因就是一次人审没挡住的事故。

**加两条针对 §2.5 / §3.4 的断言**：

| # | 断言 | 期望 |
|---|---|---|
| 12 | 取实现返回的 `outcome` 字面量，与 §4 比对 | 恰好是 `succeeded` / `rejected` / `failed` |
| 13 | 用同参数提交两次，取审计记录 | 两条记录、`record_id` 相同、第二条 `replayed: true`（`RP-1`/`RP-2`） |
| 14 | 送一条**只违反参数约束**、且该规则同时被写成判据的样本 | 拒绝发生在 `stage: parameter`；若实现把它写成判据，说明存在两处真源（`BD-5`） |

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

## 9. 实现反馈

> 本节记录**写实现时才暴露出来的**规范缺口。
> 纸面推演发现不了这些。这些缺口的**条款与理由都保留在正文里**，不需要读实现才能理解。

### 9.1 multiplicity 的强制点必须前移（已修正为 `ST-4`）

**现象**：最初的实现把 `multiplicity`（`ManyToOne` / `OneToOne`）**只在读取时检查**：

```
写入两条 status  →  成功（脏数据进库）
读取 status      →  抛错「有 2 个值，但它被声明为单值」
```

**这违反了框架 `I2-1`『写入必须过规则』的立意** —— 规则必须在写入路径上拦。

**本次修正**：新增 **`ST-4`**，明确强制点在阶段 8 的写入路径上。

> **教训：在"声明了约束"和"约束生效"之间，隔着一整条写入路径。**
> 只写"约束必须被校验"不够，**必须说清在哪一层校验**。

### 9.2 `AU-5` 对早期拒绝要求过严（已修正）

参数校验失败、目标不存在、无权限 —— 这三种拒绝发生在**任何读取之前**，
此时**不存在快照**，`based_on.snapshot` 无值可填。

原 `AU-5` 是无条件的，与实现冲突。**已改为条件式**（见 §5.3）。

### 9.3 可选参数缺失时的求值语义（**未修正，待讨论**）

若参数 `required: false` 且调用方未提供，在前置条件里引用它会怎样？**规范未定义**。

| 候选语义 | 问题 |
|---|---|
| 变量为 `null`，比较返回 false | 会因"未传可选参数"而拒绝，语义可疑 |
| 变量为 `null`，比较返回"未知" | "未知"算不算通过？ |
| 直接报错 | 可选参数失去意义 |

**实现反馈中的临时选择**：变量为 `null`；与 `null` 的顺序比较返回"未知"；
"未知"不算通过。示例中把 `refund_amount` 设为必填以规避。

**留给 v0.2 决定。**

### 9.4 `suggestions` 与 `AT-2` 的张力（**未修正，待讨论**）

框架 `AG-2` 要求"所有拒绝 MUST 可被自动纠正"，但本规范把 `suggestions` 列为**可选**。

**实现反馈中的判断**：

- `stage` + `violations[].id` + `actual` 足以让 Agent **修正参数**
- 但不足以让它**改选另一个动作** —— 那需要知道本体里有哪些替代动作

**建议**：把"替代动作建议"归入 **I6 发现**的职责（`FindByCapability`），
而不是 I4 的可选字段。这样 `suggestions` 可以保持可选，职责也更清晰。

---

## 10. v0.2 变更：多实例事务、null 语义、建议移交

> 本版解决 §9 里遗留的发现 3、4，并新增多实例事务能力。

### 10.1 多实例事务（原 §0.3 的排除项）

**一次动作现在可以原子地修改多个实例。**

```yaml
target:
  concept: Order
  reads: [Order, Shipment]
  also_write:
    - name: shipment
      concept: Shipment
      via: shipment            # 从主目标沿 `shipment` 关系到达

effects:
  - applies_to: default
    set: { path: "status", value: "'cancelled'" }
  - applies_to: shipment
    set: { path: "status", value: "'recalled'" }
```

| # | 条款 |
|---|---|
| **MI-1** | 效果 **MUST** 用 `applies_to` 指定作用目标，缺省为 `default`（主目标） |
| **MI-2** | `applies_to` 的值 **MUST** 在 `target.also_write` 中已声明 |
| **MI-3** | 附属目标 **MUST** 在主目标的**同一快照**上解析（`AT-2` 扩展） |
| **MI-4** | 附属目标解析失败 **MUST** 拒绝（`stage: target`），**MUST NOT** 部分执行 |
| **MI-5** | `AT-1`（同事务）与 `AT-4`（不部分生效）**MUST** 覆盖**全部**目标 |
| **MI-6** | 全部被写入实例的版本号 **MUST** 在同一事务内递增 |
| **MI-7** | 附属目标的属性 **MAY** 参与前置条件（通过其 `name` 引用） |

**⚠️ `MI-8`（格式陷阱）**：字段名 **MUST NOT** 使用 `on`。

> **YAML 1.1 把 `on` / `off` / `yes` / `no` 解析为布尔值。**
> 写 `on: customer` 时，键名会变成布尔 `true`，**字段静默丢失** —— 不报错，只是不生效。
>
> 这是实现**实际踩到的坑**。格式规范必须避开它。
> 因此本版用 `applies_to` 而非 `on`。

### 10.2 可选参数缺失的求值语义（解决发现 3）

| # | 条款 |
|---|---|
| **NL-1** | 缺失的可选参数 **MUST** 绑定为 `null`（而非"未定义变量"） |
| **NL-2** | 与 `null` 的**顺序比较**（`<` `<=` `>` `>=`）**MUST** 求值为"未知" |
| **NL-3** | "未知"的前置条件 **MUST** 判为**未通过**（默认拒绝） |
| **NL-4** | 表达式语言 **MUST** 支持 `is null` / `is not null` |
| **NL-5** | 因 null 导致拒绝时，拒绝信息 **MUST** 标明涉及的参数名（`null_parameters`） |

**设计意图：默认拒绝 + 显式守卫。**

> 想用可选参数，就必须显式写 `x is null or <条件>`。
> **沉默地放行**（null 当作 false 或当作忽略）是更危险的默认值。

**规范 §2.3 的表达式语言因此扩展**：MUST 支持 `is null` / `is not null`。

### 10.3 替代动作建议移交 I6（解决发现 4）

| # | 条款 |
|---|---|
| **ST-5** | `suggestions` 保持**可选**；调用方 **MUST NOT** 依赖它存在 |
| **ST-6** | 若实现内联了替代动作建议，每一项 **MUST** 标注来源（`via: i6.FindByCapability`） |
| **ST-7** | 替代动作的**权威来源是 I6**；I4 **MUST NOT** 自行维护一份动作清单 |

详见 [`i6-discovery-minimal.md`](i6-discovery-minimal.md) §4。

### 10.4 仍未解决的

| 项 | 状态 |
|---|---|
| 异步执行 | 留 v0.3 |
| 声明式副作用 | 留 v0.3 |
| 长事务补偿（Saga） | 留 v0.3 |
| 附属目标的**嵌套**（目标的附属目标） | 留 v0.3；本版只支持一层 |

---

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1 | 2026-09 | 初稿。定义最小 I4：单实例、同步、无副作用、有审计 |
| v0.1.1 | 2026-09 | 依据实现反馈修正：新增 `ST-4`（约束强制点在写入路径）；`AU-5` 改为条件式；新增 §9 记录 4 条缺口 |
| **v0.2** | 2026-09 | **多实例事务**（§10.1，含 `MI-8` YAML `on` 键陷阱）；**null 语义**（§10.2，解决发现 3）；**建议移交 I6**（§10.3，解决发现 4）。同步产出 I3-min 与 I6-min 规范 |
| **v0.2.1** | 2026-09 | **表达式语言修正**（§2.3）：改用 Ossie 的表达式语言（SQL 子集），不再推荐 CEL。原推荐会与 Ossie 的 `requires`/`derived_by` 造成两套语言的割裂 |
| **v0.2.2** | 2026-09 | **新增 §4.3：拒绝 MUST 穿过适配层**（`XAD-1`~`XAD-3`）。依据 bazidiy 实战实现第二次回写：原子返回了 `rejection`，但工具 `output.schema`（`additionalProperties:false`）没声明它，**结构化拒绝在适配层被静默丢弃**，LLM 只看到"成功的空结果"。§8 增补第 10/11 条运行期可判定的断言 |
| **v0.2.3** | 2026-09 | **新增 §2.5 判据绑定**（`BD-1`~`BD-6`）：定义"声明式 `expression` + 命令式绑定"这一实现模式，并划清**参数约束 vs 前置条件**的边界（`BD-5`，来自一次"同一规则两处真源导致判据成死代码"的事故）。**§3.4 增补 `RP-1`/`RP-2`**：补上此前未定义的"重放要不要记审计"——审计记**调用**不记**变更**。§4 增补字面量 MUST 对齐要求，并记录规范自身 §4.2/§5.1 动作身份写法不一致（待 v0.3 收敛）。§8 增补第 12~14 条断言 |
| **v0.2.4** | 2026-09 | **§3.4 增补 `RP-3`**：`RP-2` 让 `record_id` 在两个位置指代不同东西（返回结果里指**变更**、审计记录里指**调用**），调用方无法区分。`RP-3` 要求拆成两个字段（如用 `change_record_id`），使"审计条数=调用数、变更 id 去重=变更数"成为可机读的事实，而不是需要猜的约定 |

---

## 许可

[Apache License 2.0](../LICENSE)
