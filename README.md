# 3AI Agents and Blockchain-Powered Financial Services

构建一个金融服务原型，模拟资金委托给 AI 代理后的全流程：如何确保其支出始终在用户设定的范围内，以及在触及或越过额度上限时如何拦截、告警与回滚。

**一句话定位**：支付轨道记录**谁付给了谁**，但不记录**谁授权的、依据什么条件**。所以一个代理守住预算，只因为它被写成会守预算。本原型把"授权"变成可强制、可追溯、可停止的东西。

> ⚠️ 原型阶段。**不处理真实资金。** 详见下方[信任模型](#信任模型这个原型能证明什么不能证明什么)与[已知局限](#已知局限)。

---

## 目录

- [问题与答案](#问题与答案)
- [架构](#架构)
- [快速开始](#快速开始)
- [接 Kiln（NPU 推理）](#接-kiln-npu-推理)
- [区块链集成](#区块链集成)
- [信任模型：这个原型能证明什么，不能证明什么](#信任模型这个原型能证明什么不能证明什么)
- [token 与能耗核算](#token-与能耗核算)
- [已知局限](#已知局限)
- [测试状态](#测试状态)

---

## 问题与答案

| 问题 | 本原型的答案 | 代码位置 |
| --- | --- | --- |
| 边界怎么定？ | 委托条款（`Mandate`）：单笔上限、窗口累计、分类上限、白名单、黑名单、复核线 | `models.py` `Policy` |
| 事前怎么拦？ | **两道闸门**：策略引擎（语义判定）+ 授权链（权威记账）。任一被绕过还有另一道 | `engine.py` `receipts.py` |
| 谁来花？ | Kiln NPU 上的 LLM **只提议，不决定**。模型输出是不可信输入 | `agent.py` |
| 事后怎么答？ | 哈希链上的授权回执 + 追溯工具，可回答"谁批的、依据哪条规则、代理当时说了什么" | `receipts.py` `forensics.py` |
| 怎么停？ | 单方面撤销，立即生效，无需代理配合 | `wallet.py` `stop()` |
| 怎么防事后改账？ | 链头哈希锚定到区块链；且预算本身可做成**链上硬约束** | `anchor.py` `contracts/SpendMandate.sol` |

用户简报里点名的三种实现，本仓库都做了：

1. **钱包界面**（批准 / 监视 / 停止）→ `agent_guard/wallet.py`
2. **跨整个会话持有预算与许可名单的策略层** → `agent_guard/engine.py` + `agent_guard/receipts.py`
3. **用审批记录与交易记录解释某笔历史购买的工具** → `agent_guard/forensics.py`

---

## 架构

```
                 用户（授权人）
                      │  ① 登记委托条款：额度 / 名单 / 期限
                      ▼
              ┌───────────────┐
              │    Mandate    │  条款指纹 policy_hash
              └───────┬───────┘
                      │
   ┌──────────────────┼──────────────────────────────────────┐
   │                  ▼                                      │
   │         ┌─────────────────┐   ② 提议（只提议，不决定）    │
   │         │  Kiln NPU / LLM │◄──────────────────┐         │
   │         └────────┬────────┘                   │         │
   │                  │ SpendProposal              │         │
   │                  ▼                            │         │
   │      ┌───────────────────────┐                │         │
   │      │ ③ 授权链预检           │  撤销？过期？   │         │
   │      │ AuthorizationChain    │  额度？币种？   │         │
   │      └───────────┬───────────┘                │         │
   │                  ▼                            │         │
   │      ┌───────────────────────┐                │         │
   │      │ ④ 策略引擎             │  名单/复核线/   │         │
   │      │ PolicyEngine          │  分类/单笔/累计 │         │
   │      └───────────┬───────────┘                │         │
   │           放行   │   拒绝 / 转人工 ────────────┘         │
   │                  ▼                    （模型解释为什么）   │
   │      ┌───────────────────────┐                          │
   │      │ ⑤ 授权 + 占用额度      │  AUTH 记录（含条款指纹）  │
   │      └───────────┬───────────┘                          │
   │                  ▼                                      │
   │      ┌───────────────────────┐                          │
   │      │ ⑥ 支付轨道             │  "谁付给了谁"             │
   │      └───────────┬───────────┘                          │
   │                  ▼                                      │
   │      ┌───────────────────────┐                          │
   │      │ ⑦ SETTLE 记录          │  凭证号关联两个世界       │
   │      └───────────┬───────────┘                          │
   │                  ▼                                      │
   │      ┌───────────────────────┐   ⑧ 锚定链头哈希          │
   │      │ 区块链                 │  → 防事后改账             │
   │      │ SpendMandate.sol      │  → 可选：预算硬约束        │
   │      └───────────────────────┘                          │
   └─────────────────────────────────────────────────────────┘
```

---

## 快速开始

要求 **Python ≥ 3.10**，运行期**零第三方依赖**。

```bash
# 跑演示：不接 Kiln 也能跑通全链路（用回放传输）
python -m agent_guard.cli demo

# 追溯报告
python -m agent_guard.cli report

# 校验策略
python -m agent_guard.cli validate --policy data/policy.example.json

# 探测 Kiln 是否在线
python -m agent_guard.cli kiln-health --base-url http://<板子IP>:8080/v1

# 测试
python -m pytest
```

### 作为库使用

```python
from agent_guard import Wallet, Policy, KilnClient, GuardService

policy = Policy.from_dict({
    "currency": "CNY",
    "per_tx_limit": "2000.00",
    "window_limit": "5000.00",
    "window": "30d",
    "payee_allowlist": ["cloud-vm", "data-vendor"],
    "payee_denylist": ["scam-llc"],
    "escalation": {"block_at_or_above": "1500.00"},
})

wallet = Wallet()                                   # 授权链 + 追溯
mandate = wallet.register_mandate(
    owner="alice", agent_id="shopper-1", policy=policy
)

service = GuardService(
    chain=wallet.chain,
    mandate_id=mandate.mandate_id,
    policy=policy,
    client=KilnClient("http://192.168.1.50:8080/v1"),   # 指向你的 Kiln 板子
)
wallet.attach_service(service)

outcome = wallet.spend(mandate.mandate_id, "为本月的行情数据订阅付款")
print(outcome.describe())

print(wallet.status(mandate.mandate_id).render())       # 监视
wallet.stop(mandate.mandate_id, actor="alice", reason="行为异常")  # 停止
```

---

## 接 Kiln（NPU 推理）

本原型对接的是 [**Kiln**](https://github.com/gahingwoo/kiln)（`gahingwoo/kiln`）
——在 Rockchip **RK3576** NPU 上跑本地 LLM 的离线服务，硬件参考平台是
Radxa ROCK 4D（[Radxa 文档](https://docs.radxa.com/en/rock4/rock4d/application-dev/npu/kiln)）。

**本仓库的客户端契约是逐一对照服务端源码核实的**（`buildroot/board/rock4d/kiln_serve.cpp`，main 分支 blob sha `fa5d8265…`），不是照 OpenAI 文档猜的。核实结果如下——**其中多条与"标准 OpenAI 兼容"的直觉不符**：

| 项目 | 实际情况 |
| --- | --- |
| 端点 | `GET /health`、`GET /v1/models`、`POST /v1/chat/completions`、`POST /v1/vision/classify`、`POST /v1/vision/detect`、`OPTIONS *`。无 `/v1/completions`、无 `/v1/embeddings`、无 `/metrics` |
| 请求字段 | **只读 `messages` 和 `stream`**。`model` / `temperature` / `max_tokens` / `stop` / `top_p` / `tools` 等**全部被静默忽略**。采样参数只能改板上的 `/etc/kiln/config.ini` 的 `[llm]` 段 |
| 鉴权 | **完全没有**。不读 `Authorization`，无 API Key 配置项。官方文档明说 API key 被忽略、建议放在反向代理后面 |
| `usage.prompt_tokens` | **恒为 0**。运行时没有 tokenizer，"prompt 侧 token 用量从 API 不可观测" |
| `usage.completion_tokens` | = `usage.total_tokens` = 实际生成 token 数。**不等于** prompt+completion |
| 流式响应 | SSE，`data: {json}\n\n`，无 `event:`/`id:` 行，以 `data: [DONE]` 结束。**任何分块里都没有 usage 对象** |
| 时序 | HTTP 层**没有任何**耗时/tok-s 字段。TTFT 与解码速度只能由客户端本地测 |
| `finish_reason` | 恒为字面量 `"stop"`，**即使被 `max_new_tokens` 截断也不会是 `"length"`** |
| 能耗 | **不存在**。无功率/能量/电流/电压字段或端点 |

### 由此产生的三个实现决定

1. **`prompt_tokens: 0` 被当作"不可观测"而非"零"。** 照单全收会把未知伪装成已知，让所有"每 token 成本"虚高。见 `metrics.py`。
2. **token 数拿不到就记 `UNKNOWN`，绝不估算。** 估算的 token 数会污染下游全部结论。
3. **`[bench]` 行的解析被保留但重新定位。** 该仓库 `docs/BENCHMARK.md` 称 kiln-serve 也打印 `[bench] tokens=… prefll(TTFT)=… decode=… tok/s`，但 `bench` 这个字符串在服务端源码里不存在——那是 `kiln-chat` CLI 的行为。`parse_bench_line()` 因此标注为"解析 CLI 输出"。

### 没有板子也能跑

`ReplayTransport` 会按顺序回放预置响应，因此**全部测试与 `cli demo` 都不需要 Kiln 真机**。它测的是管道，不是模型质量——真机上把 `transport` 换成默认的 `UrllibTransport` 即可，其余代码不动。

### 关于"Kiln"这个名字的歧义

还有另一个不相关的 **Kiln AI**（`kiln.tech`，LLM 评测平台，有自己的 REST API）。本原型对接的是 **NPU 那个**。若你要换成别的 OpenAI 兼容后端，只需改 `base_url`；注意 `kiln-serve` 会忽略的那些字段在新后端上可能生效。

---

## 区块链集成

### 选了什么

**两件事分开做，因为它们的可信度完全不同：**

| 层 | 做什么 | 在哪 |
| --- | --- | --- |
| **授权回执**（始终可用） | 哈希链记录每次授权/拒绝/结算/撤销；链头哈希可锚定上链 | `receipts.py` + `anchor.py` |
| **链上硬约束**（可选，更强） | 预算与名单在合约里强制执行，超限直接 revert | `contracts/SpendMandate.sol` |

### 合约为什么这么写（每条都有出处）

1. **窗口用 `block.number` 切，不用 `block.timestamp`。** 时间戳受出块者影响（[SCWE-065](https://scs.owasp.org/SCWE/SCSVS-BLOCK/SCWE-065/)），且按时间惰性重置会出现"窗口边界前后各用满一次"。Safe 的 [Allowance Module](https://github.com/safe-global/safe-modules/blob/master/modules/allowances/contracts/AllowanceModule.sol) 正是按 `uint32(block.timestamp / 60)` 切窗口，那是它的已知弱点。
2. **不在 ERC-4337 的 `validateUserOp` 里做额度检查。** [ERC-7562](https://docs.erc4337.io/core-standards/erc-7562.html) 规定校验阶段的规则由 **bundler 在链下执行**，且 `TIMESTAMP` 在校验期间被禁用。本机跑通的检查可能在真实 bundler 上被直接拒收。所以检查放在**执行阶段**，由合约在转账前完成。
3. **先扣减、后转账。** 顺序反了就有重入窗口。
4. **检查、扣减、转账在同一笔交易内。** 这是"强制"与"提示"的分界线——中间没有可插入其它请求的间隙。
5. **名单只做 membership 查询，不做无界遍历。** gas 与名单长度无关。
6. **结算不得超过授权。** 超出授权的付款必须重新走一次授权，不允许在结算环节补。

### 现实核查：链上并没有现成标准

研究结论（见 `agent-spend-authorization-report.md`）：

- **没有**针对"按窗口支出上限"的标准。[ERC-7579](https://eips.ethereum.org/EIPS/eip-7579) 只标准化模块类型 id，刻意不含额度逻辑。[ERC-4337](https://eips.ethereum.org/EIPS/eip-4337) 链上只强制一个时间范围（`validAfter`/`validUntil`）。
- **没有**针对"代理授权回执"的标准。[ERC-7710](https://eips.ethereum.org/EIPS/eip-7710)/[7715](https://eips.ethereum.org/EIPS/eip-7715) 是 Draft 且只覆盖委托管道；[RFC 9421](https://www.rfc-editor.org/rfc/rfc9421.html) 签的是 HTTP 请求而非决策；[EAS](https://docs.attest.org/) 是务实的锚定层。
- [ERC-8004](https://eips.ethereum.org/EIPS/erc-8004) 自己写明 "Payments are orthogonal to this protocol and not covered here" —— 这恰好就是用户简报指出的那个空缺。

`SpendMandate.sol` 与 `AnchorReceipt` 是**为此空缺写的最小实现**，不是某个标准的实现。别把它当成标准。

---

## 信任模型：这个原型能证明什么，不能证明什么

这一节是整个 README 最重要的部分。

### 能证明

- **记录未被事后修改**：哈希链的 `verify_chain()` 会检测内容篡改、链接断裂、序号缺口。
- **某条记录在某个时刻已存在**：链头哈希锚定上链后，任何人都能独立核对。锚定在服务方控制之外。
- **额度是否被突破**：把 AUTH 记录按窗口重放，累计超限会被报为 `WINDOW_EXCEEDED`。
- **付款没超过授权**：`OVER_SETTLED` 检查会报出"批了 100 却付了 150"。
- **谁按下了停止**：撤销本身就是一条带 actor 与 reason 的记录。

### 不能证明（**这些限制是真的，不是谦辞**）

- **回执能证明"这笔被授权了"，永远不能证明"这次授权是对的"。**
- **链下策略检查是否真的跑过**。链上记录的 rule/reason 是**链下引擎声称的**。若引擎有 bug 或被绕过，回执照样记得漂漂亮亮。锚定只固定"它当时是这么说的"。
- **记录当初就是真的**。哈希链防的是**事后**修改。服务被攻破后，攻击者能重算全部哈希造一条自洽假链。防这个要靠外部锚定 + 本地签名，本原型**只做了锚定，没做签名**。
- **用户当初真的画了那条线**。链上只能证明"存在一个签名/一条记录"，不能证明签名的人理解了自己签的是什么。**这是整个链条最薄的一环。**
- **资金被追回**。`recordRollback` 只是事实登记，**不移动任何资金**。真实退款要支付轨道自己做。
- **代理会停止行动**。撤销只让"这条委托不可再用"。代理若还持有别的密钥或渠道，照样能花钱。

### 强度分级（别把这三件事混为一谈）

| 做法 | 强度 | 说明 |
| --- | --- | --- |
| 链下策略引擎 | **提示级** | 只要改代码/绕过程序就能突破。本原型的 `engine.py` |
| 链下哈希链 + 外部锚定 | **可审计级** | 能被独立验证，但**不能阻止**超支。`receipts.py` + `anchor.py` |
| 链上 `SpendMandate` | **强制级** | 超限直接 revert，与调用方是否守规矩无关。`contracts/` |

只有第三级才让预算**成为约束**而非**建议**。

---

## token 与能耗核算

用户目标之一是"探索一个完整服务在 token 用量与能耗上能跑多高效"。**这一块必须诚实**，因为 Kiln 不提供能耗数据。

每个数值都带可信度标签（`agent_guard/metrics.py`）：

| 标签 | 含义 | 例子 |
| --- | --- | --- |
| `MEASURED` | 真实传感器读数 | 客户端墙钟时间 |
| `REPORTED` | 服务端权威计数 | `completion_tokens` |
| `ESTIMATED` | 由公开参数推算 | **全部能耗数字** |
| `UNKNOWN` | 拿不到，**明确留空** | prompt tokens、流式响应的 token 数 |

**关键规矩：`ESTIMATED` 的能耗永远不会被当作 `MEASURED` 展示。** 仪表盘和报告都带出处标签，就是为了防止这个原型变成一台"看起来很精确的编数字机器"。

**要拿到真实能耗**，需要给板子接功率传感器（INA219/INA226 一类 I2C 电表）或外接功率计，然后把读数接进 `Measurement(basis=MEASURED)`。`EnergyModel` 里的默认瓦数只是量级估计，**用之前请自己标定**。

按决策粒度记账（而不只是报总算力）是刻意的：要回答"一个完整服务能跑多高效"，必须知道**每个决策**花了多少。

---

## 已知局限

按严重程度排序：

1. **所有测试都未执行过。** 本开发环境的 shell（`pwsh`）不可用（`0xC0000142`，[DSH 已知问题](https://github.com/deepseek-ai/deepseek-harness/discussions/810)），因此 `pytest` 一次都没跑过，`SpendMandate.sol` 也**从未编译**。代码经过逐文件人工审阅与静态检查，但**首次运行仍可能失败**。见[测试状态](#测试状态)。
2. **`JsonRpcAnchor` 未在真链上验证过。** 它手写了 JSON-RPC 与一种简化的 calldata 编码以求零依赖。函数选择器 `ANCHOR_SELECTOR` 是占位值，**必须用你编译产物的 ABI 覆盖**。生产环境请换 `web3.py`。
3. **锚定后端不做交易签名。** 依赖节点托管账户（Anvil/Hardhat 风格）。**不适合生产。**
4. **内存存储。** 授权链在进程内存里，重启即丢。生产要换带事务的持久化存储，但**接口不要变**——占用与校验必须在同一事务内。
5. **无本地签名。** 回执没有加密签名，只靠哈希链 + 锚定。要防服务自身作恶，需要签名。
6. **无多币种换算。** 币种不符直接拒绝，未实现汇率折算。
7. **`_settledAmount` 与窗口额度未联动。** 合约里回滚会释放窗口额度，但部分结算不会。**部分结算 + 回滚的组合语义未仔细设计**，见 `recordRollback` 的注释。
8. **`AuthorizationChain.reject()` 也占链上记录位置**（不占额度）。窗口重放只统计 AUTH，因此拒绝不影响额度——这是有意的，但意味着链会随被拒次数增长。
9. **无告警通道。** `ESCALATE` 只返回判定结果，未接通知/审批流。
10. **`payee_kind` 字段未参与判定。** 预留给后续"供应商 vs 内部转账"的差异化风控。
11. **合约未做 gas 优化，未审计。** 它是原型代码，别拿去管真钱。

---

## 测试状态

**诚实记录：以下测试全部已编写，但一次都没执行过。**

| 文件 | 覆盖 | 状态 |
| --- | --- | --- |
| `tests/test_policy.py` | 金额折算、时长解析、策略与请求校验 | ⚠️ 未执行 |
| `tests/test_engine.py` | 六类规则边界、并发 TOCTOU、台账状态机 | ⚠️ 未执行 |
| `tests/test_simulator.py` | 示例数据端到端、CLI、JSON 报告 | ⚠️ 未执行 |
| `tests/test_end_to_end.py` | Kiln 回放 → 提案 → 链 → 引擎 → 结算 → 追溯 → 锚定 | ⚠️ 未执行 |

已有替代验证：逐文件人工审阅、跨模块调用签名核对（grep 确认无失效调用）、示例数据 17 笔判定结果与金额累加手工核对。**这些都不能替代真正跑一遍。**

首次执行方式：

```bash
python -m pytest -q
```

**若失败，以测试输出为准，不要以本文档为准。**

其他未验证项：

- `contracts/SpendMandate.sol` **未编译、未部署、未测试**。
- `JsonRpcAnchor` 未在真链上跑过。
- Kiln 真机行为未验证（回放传输测的是管道）。`kiln_serve.cpp` 的契约核实到源码级，但**未在硬件上端到端跑过**。

---

## 目录结构

```
agent_guard/
  models.py        领域模型、金额折算（整数最小单位，无浮点）
  ledger.py        本地台账：占用/结算/回滚（线程安全）
  engine.py        策略引擎：规则判定与优先级
  receipts.py      授权链：哈希链、委托、授权/拒绝/结算/撤销记录、完整性验证
  agent.py         代理：Kiln 只提议，不决定
  kiln_client.py   Kiln 客户端（契约对照服务端源码核实）
  metrics.py       用量与能耗核算（带可信度标签）
  service.py       编排：提议→链预检→策略审→授权→结算
  forensics.py     追溯：解释某笔购买、列出被拒尝试、悬空授权、超额结算
  wallet.py        钱包界面：批准 / 监视 / 停止
  anchor.py        锚定：NullAnchor（默认，明确不锚定）/ JsonRpcAnchor
  simulator.py     序列模拟器（第一阶段的产物，仍可用）
  cli.py           命令行入口：demo / report / validate / simulate / kiln-health
contracts/
  SpendMandate.sol   链上花费委托（强制级）
data/
  policy.example.json     示例委托条款
  requests.example.json   示例支出序列（17 笔，覆盖全部规则）
tests/            4 个测试文件，全部未执行
```

---

## 免责声明

本项目是一个**技术原型**，用于研究和演示 AI 代理在受托资金场景下的支出约束机制：

- 不构成任何投资建议或金融服务；
- **不得用于处理真实资金**；
- 示例中的额度、阈值、白名单、私钥、合约地址均为演示数据；
- 能耗数字为模型估算，非实测；
- 软件按 MIT 许可证 "AS IS" 提供，作者不对任何使用后果承担责任。

## 许可证

[MIT](LICENSE)
