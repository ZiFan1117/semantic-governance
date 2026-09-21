# I6 发现接口 · 最小规范
<!-- clauses: DG EN FC IFD -->

| 字段 | 值 |
|---|---|
| **版本** | v0.1（草案） |
| **规范等级** | **Normative**（含 MUST / MUST NOT / SHOULD） |
| **上级文档** | [`../docs/framework.md`](../docs/framework.md) §20 |
| **构件落位** | 枚举与描述 **对象 · 关系 · 动作 · 接口**（接口见 §2.7）；`DescribeAction` 返回的契约含**动作侧规则**（前置条件与参数约束）。**不实现优选策略**——候选打分属 `FindByCapability` 的检索质量，不构成策略要素（框架 §25.2 的**策略条款是条件式**） |
| **本规范自有条款前缀** | `G`（保证）· `E-`（枚举与描述）· `F-`（按能力查找） |
| **对应 Issue** | #3 发现 4 |

---

## 0. 范围

### 0.1 本规范解决什么

框架 §20 定义了 I6 的五条保证，但没有给出可实现的接口。

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
| `ListDomains` | — | **域列表**（`I6-G1` 要求"域可被完整列出"） |
| `ListConcepts` | 可选过滤条件 | 概念列表（简） |
| `GetConceptDetail` | 概念名 | 概念完整信息（含关系、约束） |
| `ListActions` | 可选：概念名 | 动作列表（简） |
| `DescribeAction` | 动作全名 | 动作完整契约 |
| `FindByCapability` | 需求描述 | 候选能力列表 + **匹配理由** |
| **`ListInterfaces`** | 可选过滤条件 | **接口列表**（简） |
| **`GetInterface`** | 接口全名 | 接口完整定义（含共享属性与链接约束） |
| **`ListImplementers`** | 接口全名 | **实现该接口的对象类型列表** |

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

### 2.7 接口的发现（`IFD-1`~`IFD-3`）★

```
ListInterfaces() → [Interface]
GetInterface(qualified_name) → InterfaceDefinition
ListImplementers(qualified_name) → [ConceptRef]
```

**接口本身的定义与约束属 I7**；本节只定义**如何发现它**。

**为什么必须在这里**：**"这类东西能被怎么对待"是 Agent 与业务软件都要问的问题。**
没有这三个操作，接口就只是建模者脑中的概念，**不可被发现**。

```json
// GetInterface 的返回（节选）
{
  "qualified": "urn:sem:acme:device:upgradable",
  "display_name": "可升级",
  "api_name": "upgradable",
  "status": "active",
  "shared_properties": ["firmware_version"],
  "extends": [],
  "link_type_constraints": [
    { "name": "固件包", "target_kind": "object_type", "target": "FirmwarePackage",
      "cardinality": "MANY", "required": false }
  ],
  "implementers": ["RelayPlatform", "CommTerminal"]
}
```

### 2.7.1 ⚠️ 与 `FindByCapability` 的区别（**MUST NOT 混用**）

| | `FindByCapability` | `ListImplementers` |
|---|---|---|
| 检索**什么** | **动作** | **对象类型** |
| 回答 | "我需要做 X，**哪些动作**能做 X？" | "这类东西**有哪些实现**？" |
| 结果 | 动作候选 + `matched_on` | 实现该接口的对象类型 |
| 归属 | 发现层（本节 §2.6） | 接口层（I7）经发现层暴露 |

**两者可以在同一个目录里共存，但语义不同。** 措辞混用会导致 Agent 拿"动作建议"当"类型清单"用。

| # | 条款 |
|---|---|
| **IFD-1** | 实现 **MUST** 提供 `ListInterfaces` / `GetInterface` / `ListImplementers`（若该实现支持接口，见 I7） |
| **IFD-2** | `ListImplementers` 的结果 **MUST** 已按 `G2` 权限过滤 |
| **IFD-3** | `FindByCapability`（按能力找动作）与 `ListImplementers`（按接口找实现方）**MUST** 是两个不同操作，**MUST NOT** 合并为一个 |

> **`IFD-1` 的范围说明**：接口是**条件性能力**——与接入侧同理（框架 `LD-1`）。
> **不实现接口的部署不必实现这三个操作**，但 **MUST** 显式声明"本实现不支持接口"（框架 `LD-3`）。

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
| **FC-1** | **MUST** 支持按概念筛选（`concept` 参数） |
| **FC-2** | **MUST** 支持按关键词匹配 `name` / `description` / `ai_context` |
| **FC-3** | **MUST** 在结果中给出 `matched_on` |
| **FC-4** | 匹配方法 **MUST** 在实现文档中声明 |
| **FC-5** | **SHOULD** 支持语义检索（向量） |
| **FC-6** | 无匹配时 **MUST** 返回空列表，**MUST NOT** 返回低质量兜底结果 |

**关于 FC-6**：宁可返回空，也不要推荐一个不相关的动作 ——
Agent 会当真，然后执行错误的动作。**空结果至少是可解释的。**

### 3.2 ⚠️ 排除语境必须与适用语境分开（实战发现）

> **本节条款来自一次真实实现的失败**，不是纸面推演。

**现象**：`when_to_use` 这类字段通常写成一段话，把「适用」和「不适用」混在一起：

```
适用：已有八字结果后给方案。不适用：缺日主/月支五行时先算八字。
```

实现按关键词匹配时，查询 **"算八字"** 会命中这段文字 ——
**但那是「不适用」子句里的内容，是排除信号，却被当成了推荐证据。**
结果是「不该被推荐的动作」排到了第一位。

**根因**：`matched_on` 只报"命中了什么字段"，
**不区分命中的是适用语境还是排除语境。**

**条款：**

| # | 条款 |
|---|---|
| **FC-7** | 可检索的适用条件与排除条件 **MUST** 分开存储为独立字段 |
| **FC-8** | 匹配器 **MUST** 对命中排除条件的候选**减分**，**MUST NOT** 只把该字段排除在检索面之外 |
| **FC-9** | `matched_on` 的 `evidence` **MUST** 标明该命中来自哪种语境 |
| **FC-10** | 净分为非正的候选 **MUST NOT** 被返回 |

**关于 FC-8（关键）**：只把排除字段移出检索面是**不够的**。
那样会让被排除的动作"少一个字段参与打分"，**反而显得更相关**。
**必须显式减分。**

**建议权重（可调，但负号不可省）：**

| 字段 | 权重 |
|---|---|
| 适用条件 | +3.0 |
| 意图 | +2.0 |
| 名称 | +1.5 |
| 目标概念 | +1.0 |
| **排除条件** | **−2.5** |

**修前 / 修后的实测对比（同一份数据）：**

```
修前： "算八字" → propose_designs(0.2667) > calculate_bazi(0.0889)   ✗ 错的排前面
修后： "算八字" → calculate_bazi(0.0889) > propose_designs(0.0222)   ✓
```

### 3.3 ⚠️ 平局裁决未定义（已知缺口）

当两个候选得分完全相同时，规范**没有规定如何裁决**。

实战中遇到：查询 `"腕围不合"`，`propose_designs` 与 `generate_design` 的
意图描述**都含"腕围"**，得分完全相同。

- **`G4`（确定性）要求顺序稳定** —— 实现用「分数降序 → 名称升序」满足它
- **但"稳定"不等于"正确"** —— 平局时的首位是任意的

**本规范不定义平局裁决的语义**（那属于检索质量，不属于接口契约）。
实现 **MUST** 用某个确定的规则打破平局（满足 `G4`），
**SHOULD** 在文档中声明该规则。

**测试写法建议**：对歧义查询，只断言"双方都在结果中"，
**不要断言首位** —— 那是在断言一个规范未定义的语义。

---

## 4. 与 I4 的关系（**解决发现 4**）

### 4.1 问题的由来

框架 `AG-2` 要求"所有拒绝 **MUST** 可被自动纠正"。
但 I4-min 把 `suggestions`（替代动作建议）列为**可选字段**，实现里恒为空。

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
| **FC-11** | I4 的 `suggestions` **MAY** 为空 —— 调用方 **MUST NOT** 依赖它存在 |
| **FC-12** | 实现 **MAY** 在 I4 的拒绝里内联 I6 的查询结果；若如此，`suggestions` 的每一项 **MUST** 标注其来源（`via: i6.FindByCapability`） |
| **FC-13** | 调用方在收到 `stage=precondition` 或 `stage=permission` 的拒绝后，**SHOULD** 用 `FindByCapability` 主动查找替代能力 |

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
| **枚举** | EN-1 `ListConcepts` / `ListActions` MUST 可完整枚举（分页可）<br>EN-2 `DescribeAction` MUST 返回足以构造提交请求的完整契约 |
| **发现** | FC-1 支持按概念筛选 · FC-2 支持关键词匹配 · **FC-3 MUST 给 matched_on**<br>FC-4 匹配方法 MUST 声明 · FC-5 SHOULD 支持语义检索 · **FC-6 无匹配 MUST 返回空**<br>**FC-11 适用/排除语境 MUST 分开存 · FC-12 命中排除条件 MUST 减分 · FC-13 evidence MUST 标语境 · FC-10 净分非正 MUST NOT 返回** |
| **保证** | G1 可枚举 · G2 权限过滤 · G3 自描述 · G4 确定性 · G5 无副作用 |
| **与 I4** | FC-11 调用方 MUST NOT 依赖 suggestions 存在<br>FC-12 内联时 MUST 标注来源 · FC-13 SHOULD 主动查替代 |

---

## 6. 一致性等级

| 等级 | 要求 |
|---|---|
| **I6-min/Core** | 全部 MUST 条款 |
| **I6-min/Plus** | Core + 语义检索（FC-5）+ 能力标签 |

**验收方法**：给定一份已知的本体与动作集，

1. `ListConcepts` 的数量**必须**等于本体里的概念数
2. `ListActions(concept=X)` 的结果**必须**等于声明了 `target.concept = X` 的动作集
3. `DescribeAction` 的输出**必须**能让调用方成功构造一次合法提交
4. `FindByCapability` 对一个**已知存在的动作**的查询，**必须**把它排在前 3
5. `FindByCapability` 对一个**不存在的能力**的查询，**必须**返回空列表（FC-6）

---

## 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1 | 2026-09 | 初稿。定义最小 I6，并解决 I4-min 发现的 `suggestions` 归属问题（§4） |
| **v0.2** | 2026-09 | **依据 bazidiy 实战实现回写 §3.2**：新增 `FC-7`~`FC-10`（适用/排除语境必须分开存、命中排除条件必须减分）。原规范的 matcher 会把"不适用：…先算八字"当成推荐证据，导致排序错乱。另新增 §3.3 记录**平局裁决未定义**这一已知缺口 |
| **v0.2.1** | 2026-09 | **修条款号重号**：§4（与 I4 的关系）那一组原也用 `FC-7`~`FC-9`，与 §3.2 同号冲突。按"先定义的保留原号"，§4 那组改为 `FC-11`~`FC-13`。另按框架 `I6-G1`（域 MUST 可被完整列出）在 §2.1 补 `ListDomains` 操作 |

---

## 许可

[Apache License 2.0](../LICENSE)
