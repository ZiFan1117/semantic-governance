# I6 发现接口 · 最小规范

| 字段 | 值 |
|---|---|
| **版本** | v0.1（草案） |
| **规范等级** | **Normative**（含 MUST / MUST NOT / SHOULD） |
| **上级文档** | [`../docs/framework.md`](../docs/framework.md) §15 |
| **对应 Issue** | #3 发现 4 |

---

## 0. 范围

### 0.1 本规范解决什么

框架 §15 定义了 I6 的五条保证，但没有给出可实现的接口。

**核心问题**：一个刚接入的系统或刚上线的 Agent，**不知道这套语义背景里有什么**。
它不能"猜"，必须能**列出来**。

### 0.2 在范围内

| # | 内容 |
|---|---|
| 1 | **枚举**：域、概念、动作 |
| 2 | **描述**：取单个能力的完整契约 |
| 3 | **按需查找**：`FindByCapability` |
| 4 | 权限过滤与结果稳定性保证 |

### 0.3 明确不在范围内

| 排除项 | 归属 |
|---|---|
| 定义的版本与差异 | I1 |
| 事实的查询 | I3 |
| 动作的提交 | I4 |
| 语义检索的向量库选型 | 实现自定 |

---

## 1. 术语

沿用框架 §4 术语表。新增：

| 术语 | 定义 |
|---|---|
| **能力**（Capability） | 一个**可被调用的东西**。在最小实现里，能力 = 一个动作 |
| **匹配理由**（Matched On） | 说明某能力**为什么**被推荐给这次查询 |
| **目录**（Catalog） | 发现接口对外呈现的整体视图 |

---

## 2. 接口

### 2.1 操作总览

| 操作 | 输入 | 输出 |
|---|---|---|
| `ListConcepts` | 可选过滤条件 | 概念列表（简） |
| `GetConceptDetail` | 概念名 | 概念完整信息（含关系、约束） |
| `ListActions` | 可选：概念名 | 动作列表（简） |
| `DescribeAction` | 动作全名 | 动作完整契约 |
| `FindByCapability` | 需求描述 | 候选能力列表 + **匹配理由** |

### 2.2 `ListConcepts`

```
ListConcepts(domain?, kind?, keyword?) → [ConceptSummary]
```

```json
[
  {
    "name": "Order",
    "namespace": "urn:sem:acme:supply",
    "type": "EntityType",
    "description": "订单",
    "identify_by": ["nr"],
    "relation_count": 5
  }
]
```

`kind` 取值：`EntityType` / `ValueType`。

### 2.3 `GetConceptDetail`

```
GetConceptDetail(name) → ConceptDetail
```

返回该概念的：类型、描述、`extends`、`identify_by`、`ai_context`、
全部关系（含角色、基数、`verbalizes`）、约束（`requires`）。

### 2.4 `ListActions`

```
ListActions(concept?) → [ActionSummary]
```

```json
[
  {
    "name": "cancel_order",
    "qualified": "urn:sem:acme:supply:cancel_order",
    "version": "1.2.0",
    "description": "取消一个尚未发货的订单",
    "ai_context": "当客户要求取消订单时使用……",
    "target_concept": "Order",
    "parameter_names": ["reason", "refund_amount"],
    "precondition_ids": ["P1", "P2"]
  }
]
```

### 2.5 `DescribeAction`

```
DescribeAction(qualified_name) → ActionDefinition
```

返回动作定义的**完整内容**（即 I4 §2 的那份 YAML 的结构化形式），
使调用方**无需额外渠道**就能构造合法的提交请求。

> **这是 I6 对 Agent 最核心的价值**：它不只是"告诉你有什么"，
> 而是"给你足够的契约信息，让你能正确调用"。

### 2.6 `FindByCapability` ⭐

```
FindByCapability(need) → [CapabilityMatch]
```

```json
[
  {
    "qualified": "urn:sem:acme:supply:return_order",
    "version": "1.0.0",
    "description": "对已发货订单发起退货",
    "target_concept": "Order",
    "score": 0.82,
    "matched_on": [
      { "field": "ai_context", "evidence": "已发货订单" },
      { "field": "description", "evidence": "退货" }
    ]
  }
]
```

**`matched_on` 是本操作的灵魂。**

> **不带匹配理由的推荐，Agent 无法判断该不该信。**
> 有了它，Agent 能回答"为什么推荐这个"，也能据此决定是否重试。

---

## 3. 保证

| # | 保证 | 说明 |
|---|---|---|
| **G1** | **可枚举** | 域、概念、动作 **MUST** 可被完整列出（分页可，但必须可达） |
| **G2** | **权限过滤** | 结果 **MUST** 已按调用者权限过滤 —— 不得泄露不可见能力的存在 |
| **G3** | **自描述** | 发现结果 **MUST** 使用标准结构，不得是自由文本 |
| **G4** | **确定性** | 同一状态下，同一请求 **MUST** 返回相同结果（含顺序） |
| **G5** | **不产生副作用** | 发现 **MUST NOT** 修改任何状态 |

### 3.1 `FindByCapability` 的额外要求

| # | 条款 |
|---|---|
| **F-1** | **MUST** 支持按概念筛选（`concept` 参数） |
| **F-2** | **MUST** 支持按关键词匹配 `name` / `description` / `ai_context` |
| **F-3** | **MUST** 在结果中给出 `matched_on` |
| **F-4** | 匹配方法 **MUST** 在实现文档中声明 |
| **F-5** | **SHOULD** 支持语义检索（向量） |
| **F-6** | 无匹配时 **MUST** 返回空列表，**MUST NOT** 返回低质量兜底结果 |

**关于 F-6**：宁可返回空，也不要推荐一个不相关的动作 ——
Agent 会当真，然后执行错误的动作。**空结果至少是可解释的。**

---

## 4. 与 I4 的关系（**解决发现 4**）

### 4.1 问题的由来

框架 `A-2` 要求"所有拒绝 **MUST** 可被自动纠正"。
但 I4-min 把 `suggestions`（替代动作建议）列为**可选字段**，参考实现里恒为空。

**一个只读拒绝信息的 Agent，能修正参数，但不能改选另一个动作** ——
因为改选需要知道本体里**还有哪些动作**。

### 4.2 本规范的解决

> **替代动作建议的职责归 I6，不归 I4。**

| 职责 | 归属 | 理由 |
|---|---|---|
| 说明**违反了哪条约束** | **I4**（拒绝信息） | 只有 I4 知道本次提交的完整上下文 |
| 给出**可改选的替代动作** | **I6**（`FindByCapability`） | 需要本体全局视图，属发现职责 |
| 执行改选 | **调用方**（Agent） | 它自己决定要不要改选 |

**条款：**

| # | 条款 |
|---|---|
| **F-7** | I4 的 `suggestions` **MAY** 为空 —— 调用方 **MUST NOT** 依赖它存在 |
| **F-8** | 实现 **MAY** 在 I4 的拒绝里内联 I6 的查询结果；若如此，`suggestions` 的每一项 **MUST** 标注其来源（`via: i6.FindByCapability`） |
| **F-9** | 调用方在收到 `stage=precondition` 或 `stage=permission` 的拒绝后，**SHOULD** 用 `FindByCapability` 主动查找替代能力 |

### 4.3 Agent 的完整自纠流程

```
提交动作
   ↓
被拒（stage=precondition，violations[].id=P2，actual 里有实际值）
   ↓
① 能靠 violations 修正参数吗？
   ├─ 能 → 改了重试
   └─ 不能 ↓
② 调 FindByCapability(need)  ← I6
   ↓
   拿到候选 + matched_on
   ↓
③ 按 matched_on 判断该不该信 → 改选动作重试
```

**这条流程把 I4 的"可纠正"落到了实处** —— 之前只有 ①，没有 ②③。

---

## 5. 规范性条款汇总

| 组 | 条款 |
|---|---|
| **枚举** | E-1 `ListConcepts` / `ListActions` MUST 可完整枚举（分页可）<br>E-2 `DescribeAction` MUST 返回足以构造提交请求的完整契约 |
| **发现** | F-1 支持按概念筛选 · F-2 支持关键词匹配 · **F-3 MUST 给 matched_on**<br>F-4 匹配方法 MUST 声明 · F-5 SHOULD 支持语义检索 · **F-6 无匹配 MUST 返回空** |
| **保证** | G1 可枚举 · G2 权限过滤 · G3 自描述 · G4 确定性 · G5 无副作用 |
| **与 I4** | F-7 调用方 MUST NOT 依赖 suggestions 存在<br>F-8 内联时 MUST 标注来源 · F-9 SHOULD 主动查替代 |

---

## 6. 一致性等级

| 等级 | 要求 |
|---|---|
| **I6-min/Core** | 全部 MUST 条款 |
| **I6-min/Plus** | Core + 语义检索（F-5）+ 能力标签 |

**验收方法**：给定一份已知的本体与动作集，

1. `ListConcepts` 的数量**必须**等于本体里的概念数
2. `ListActions(concept=X)` 的结果**必须**等于声明了 `target.concept = X` 的动作集
3. `DescribeAction` 的输出**必须**能让调用方成功构造一次合法提交
4. `FindByCapability` 对一个**已知存在的动作**的查询，**必须**把它排在前 3
5. `FindByCapability` 对一个**不存在的能力**的查询，**必须**返回空列表（F-6）

---

## 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1 | 2026-09 | 初稿。定义最小 I6，并解决 I4-min 发现的 `suggestions` 归属问题（§4） |

---

## 许可

[Apache License 2.0](../LICENSE)
