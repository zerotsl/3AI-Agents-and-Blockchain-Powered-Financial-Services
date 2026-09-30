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

### 安装

```bash
pip install agent-spend-guard        # 从 PyPI（发布后）
# 或者用离线包
pip install dist/agent_spend_guard-0.2.0-py3-none-any.whl
```

装好后有两个命令：

```bash
agent-guard --help                   # 主入口
agent-guard-export --list            # 导出工具
```

> **发行名与导入名不同**，这不是笔误：PyPI 上的 `agent-guard` 已被另一个无关项目占用，且它用的 import 名也是 `agent_guard`。所以发行名用 `agent-spend-guard`，导入名保持 `agent_guard`。详见 [docs/PUBLISH.md](E:\代号3\docs\PUBLISH.md)。

### 从源码跑（不安装）

```bash
# ① 导出网页控制台（推荐先跑这个）—— 单文件 HTML，双击就能开
python -m agent_guard.cli web --out out/console.html

# ② 起一个本地实时服务（可选，默认只绑 127.0.0.1:8787）
python -m agent_guard.cli serve

# ③ 终端版全链路演示
python -m agent_guard.cli demo

# ④ 追溯报告 / 校验
python -m agent_guard.cli report --chain out/chain.json
python -m agent_guard.cli validate --policy data/policy.example.json

# ⑤ 探测 Kiln 是否在线
python -m agent_guard.cli kiln-health --base-url http://<板子IP>:8080/v1

# ⑥ 测试
python -m pytest
```

---

## 下载：一个自包含的模块

**下载功能在 [`agent_guard/export.py`](E:\代号3\agent_guard\export.py)。**

它**不 import 本仓库的任何其他模块**，只依赖 Python 标准库——所以可以被单独拷走：

```bash
# 从仓库根目录（转发壳）
python export.py --demo --format all --out-dir out

# 装好包之后
agent-guard-export --demo --format all --out-dir out

# 想要真正单文件？直接拷实现本身
cp agent_guard/export.py /somewhere/export.py
python /somewhere/export.py --demo --format all --out-dir out
```

> **实现为什么在包里而不是根目录**：根目录的文件**不进 wheel**。原先实现在根目录时，`pip install` 之后一调导出就会 ImportError。现在实现随包走，根目录的 `export.py` 只剩转发。CI 里有一段专门检查 wheel 是否含 `agent_guard/export.py`，防这个回归。

### 四种格式

| 格式 | 用途 | 特点 |
| --- | --- | --- |
| `json` | **归档与取证** | 完整快照，含逐条记录与每个数值的可信度标签。**可回灌**（读写闭环） |
| `csv` | 灌进 Excel / pandas / 财务系统 | 带 UTF-8 BOM，双击不乱码，字段含逗号引号也正确转义 |
| `md` | 贴进工单 / PR / 邮件 / GitHub issue | 标准 Markdown 表格，含汇总、流水、按收款方归集 |
| `html` | 给人看的离线归档 | 单文件、无外部请求、可打印存 PDF |

一次全导：

```bash
python export.py --demo --format all --out-dir out
# out/mandate-demo-mandate.json / .csv / .md / .html
```

### 输入接受两种形状

两种在真实工作流里都会出现，所以都支持：

1. `cli demo --json` 的产物：`{"mandate_id": …, "records": […] }`
2. 裸记录数组：`[{…}, {…}]`

JSON 导出**自带 `records` 字段，可以直接回灌**——所以 `导出 → 导入 → 再导出` 是闭环，测试里就是按这个断言的。

### 接在演示流程上

```bash
python -m agent_guard.cli export --format all --out-dir out
```

它跑一遍演示、再调同一个导出工具。实现是**同一个模块**（`agent_guard/export.py`），根目录的 `export.py` 只是一层转发——不存在两份实现漂移的问题。

### 一条硬规矩

导出文件里每个数值都**带着可信度标签**（`measured` / `reported` / `estimated` / `unknown`）。**能耗永远是 `estimated`**——Kiln 的 HTTP API 不提供任何功率数据（已核对服务端源码：无相关字段、无 `/metrics` 端点）。

导出工具**不会**把这些标签抹平成"精确值"。这是刻意的：抹平标签正是这类原型最容易骗人的地方。测试里专门断言了输出中不存在"实测能耗"这类说法。

---

## 网页控制台与下载

### 方式一：导出单文件 HTML（推荐）

```bash
python -m agent_guard.cli web --out out/console.html
```

产出一个**自包含的单文件 HTML**：

| 性质 | 说明 |
| --- | --- |
| **零外部请求** | 无 CDN、无字体、无图标库、无埋点。CSS/JS/数据全部内联 |
| **离线可用** | 断网机器、内网机器、U 盘拷过去都能开 |
| **可直接外发** | 一个文件就能进邮件、工单、附件。不需要对方装 Python 或起服务 |
| **数据是真的** | 内容从授权链导出，**不是写死的演示假数据** |
| **页内可下载** | 页面右上角有三个按钮：**下载 JSON**（完整快照）、**下载 CSV**（流水表格）、**打印/存 PDF** |

界面包含：额度进度条、委托条款与指纹、待人工复核队列、支出流水表（可点击行跳到该笔解释）、逐笔解释、哈希链可视化、完整性校验结论、token 与能耗面板。

**审计结论由 Python 侧算定。** 剩余额度、规则命中、完整性判定全部在导出时算好再内联，前端只负责渲染。这一点是刻意的：审计结论不能由浏览器计算，否则改一行 JS 就能把"发现篡改"渲染成"一切正常"。

**页内下载用的是 Blob URL**，不依赖服务端，所以在 `file://` 下直接双击打开也能下载。若某些浏览器限制了本地文件下载，用 `cli demo --json out/chain.json` 从命令行导出同一份数据。

界面变体：

```bash
python -m agent_guard.cli web --empty            # 空状态界面
python -m agent_guard.cli web --revoke-after     # 演示「已撤销」状态
python -m agent_guard.cli web --live             # 接真实 Kiln（默认用回放传输）
```

### 方式二：本地实时服务

```bash
python -m agent_guard.cli serve                  # http://127.0.0.1:8787/
python -m agent_guard.cli serve --host 0.0.0.0   # 局域网可访问（有风险，见下）
```

| 路径 | 内容 |
| --- | --- |
| `/` | 控制台页面（每次刷新都重新渲染） |
| `/data.json` | 同一份数据的 JSON 快照 |
| `/health` | `{"status":"ok"}` |

**这个服务是只读的，而且这是刻意的。** 只有 `GET`；`POST` 返回 405 并说明原因：

> 批准与撤销**没有** HTTP 端点。把"按下停止按钮"暴露成一个 URL，等于把撤销权交给任何能发请求的人。

其他安全默认值：只绑 `127.0.0.1`；`Content-Security-Policy` 设 `default-src 'none'` / `connect-src 'none'`，页面无法外发任何数据；禁缓存、禁 iframe 嵌入、禁 MIME 嗅探。

**没有鉴权。** 绑到 `0.0.0.0` 时终端会打印警告。别放到公网。

### 下载什么、给谁

| 场景 | 用哪个 |
| --- | --- |
| 给同事/客户看这批支出 | `cli web` 导出的 `.html`，单文件直接发 |
| 自己随时盯 | `cli serve` 开着的本地页面 |
| 灌进表格分析 | `export.py --format csv`，或页面里的「下载 CSV」 |
| 归档取证 | `export.py --format json`（可回灌）+ `cli report --chain` 复校验 |
| 贴进工单 / PR | `export.py --format md` |
| 上链锚定 | `chain.head_hash(mandate_id)`，写进 `SpendMandate.anchorReceipt` |

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
| `tests/test_webui.py` | HTML 自包含性、XSS 转义、审计结论由 Python 侧算定、服务只读、JSON 往返 | ⚠️ 未执行 |
| `tests/test_export.py` | 打包形态（实现随包走、根目录是转发壳）、自包含性（AST 检查）、四格式、CSV BOM、往返一致、标签不被抹平 | ⚠️ 未执行 |

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
  webui.py         导出单文件 HTML 控制台（自包含、零外部请求）
  server.py        本地只读服务（GET only，无写端点）
  demo.py          演示状态构造（cli / web / serve 共用同一份数据）
  webui.py         导出单文件 HTML 控制台（自包含、零外部请求）
  server.py        本地只读服务（GET only，无写端点）
  export.py        导出工具**实现**（自包含，只用标准库，随包安装）
  py.typed         PEP 561 标记
  cli.py           命令行入口：web / serve / export / demo / report / validate / simulate / kiln-health
export.py          根目录转发壳（`python export.py` 用；不进 wheel）
contracts/
  SpendMandate.sol   链上花费委托（强制级）
data/
  policy.example.json     示例委托条款
  requests.example.json   示例支出序列（17 笔，覆盖全部规则）
docs/
  PUBLISH.md       发布指南（离线包 / TestPyPI / PyPI、命名理由、检查清单）
tests/            7 个文件（conftest + 6 个测试模块），全部未执行
```

## 打包与发布

发行名 `agent-spend-guard`，导入名 `agent_guard`，**运行期零第三方依赖**。

```bash
python -m build            # 产出 dist/*.whl 与 dist/*.tar.gz
python -m twine check dist/*
```

完整流程（含 Trusted Publishing 配置、TestPyPI 验证、发布前检查清单）见 **[docs/PUBLISH.md](E:\代号3\docs\PUBLISH.md)**。

⚠️ **发布前必须跑测试。** 本仓库的测试**至今一次都没执行过**（本环境 shell 不可用），而 CI 工作流已把 `pytest` 放在构建之前——测试不过就不会出包。

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
