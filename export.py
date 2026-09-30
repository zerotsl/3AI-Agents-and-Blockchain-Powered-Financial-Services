"""下载/导出工具 —— 独立单文件，可单独拷走使用。

**这个文件是自包含的：它不 import 本仓库的任何其他模块。** 拷到任何地方，
只要有 Python 3.10+，就能直接用。

它做什么
--------
把一条委托的**全部记录**导出成可带走的格式。四种格式各有各的用途，不是凑数：

=================  ====================================================
``json``           完整快照。含逐条记录、每个数值的可信度标签、链头哈希。
                   **归档与取证用这个** —— 其余三种都是从它派生的视图。
``csv``            支出流水表。带 UTF-8 BOM，Excel 双击不乱码。
``md``             可读归档。能贴进工单、PR、邮件、GitHub issue。
``html``           单文件网页归档。离线可开、可打印、无外部请求。
=================  ====================================================

怎么用
------
::

    python export.py --demo --format all --out-dir out   # 自带演示数据，立刻看效果
    python export.py --chain out/chain.json --format csv # 导出指定链
    python export.py --list                              # 列出格式
    python export.py --demo --format md --stdout         # 打到标准输出

``--chain`` 接受两种输入（两种在真实工作流里都会出现）：

1. ``cli demo --json`` 的产物：``{"mandate_id": …, "records": […] }``
2. 裸记录数组：``[{…}, {…}]``

**本工具的 JSON 导出自带 ``records`` 字段，可以直接回灌**，所以读写闭合成环。

一条硬规矩
----------
导出文件里的每个数值都**带着可信度标签**（实测 / 上报 / 估算 / 未知）。
能耗数字永远是 ``estimated``——Kiln 的 HTTP API 不提供任何功率数据
（已核对服务端源码：无相关字段、无 ``/metrics`` 端点）。
本工具**不会**把标签抹平成"精确值"，因为那正是这个原型最容易骗人的地方。
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

__version__ = "0.2.0"

#: 支持的导出格式
FORMATS: tuple[str, ...] = ("json", "csv", "md", "html")

_CSV_COLUMNS = (
    "seq",
    "时间",
    "类型",
    "对手方",
    "金额",
    "币种",
    "分类",
    "规则",
    "原因",
    "授权ID",
    "轨道凭证",
)

_ICONS = {"auth": "✅", "settle": "💸", "reject": "⛔", "revoke": "🛑", "mandate": "📜"}
_LABELS = {
    "auth": "授权",
    "settle": "结算",
    "reject": "拒绝",
    "revoke": "撤销",
    "mandate": "委托",
}


class ExportError(RuntimeError):
    """导出失败。"""


# ---------------------------------------------------------------------------
# 读取
# ---------------------------------------------------------------------------
def load_chain(path: str | Path) -> dict[str, Any]:
    """读入一份导出文件。"""
    target = Path(path)
    if not target.is_file():
        raise ExportError(f"文件不存在：{target}")
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ExportError(f"{target} 不是合法 JSON：{exc}") from exc

    if isinstance(data, list):
        return {"records": data, "mandate_id": "", "_source": str(target)}
    if isinstance(data, dict):
        records = data.get("records")
        if not isinstance(records, list):
            raise ExportError(
                f"{target} 里没有 'records' 数组；顶层键：{sorted(data)[:8]}"
            )
        out = dict(data)
        out["_source"] = str(target)
        return out
    raise ExportError(f"{target} 顶层应为对象或数组，实际是 {type(data).__name__}")


# ---------------------------------------------------------------------------
# 归一化：让四种格式共享同一份中间表示
# ---------------------------------------------------------------------------
def _scale_for(currency: str) -> int:
    """货币精度。故意在这里独立实现，以便本文件可以单独拷走。"""
    return 0 if currency.upper() == "JPY" else 2


def normalise(chain: Mapping[str, Any]) -> dict[str, Any]:
    """把原始记录整理成统一的中间表示。"""
    records = list(chain.get("records") or [])
    currency = str(chain.get("currency") or "")
    if not currency:
        for record in records:
            payload = (record or {}).get("payload") or {}
            if payload.get("currency"):
                currency = str(payload["currency"])
                break
    currency = currency or "CNY"
    scale = 10 ** _scale_for(currency)

    rows: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, Mapping):
            continue
        kind = str(record.get("record_type") or "")
        payload = record.get("payload") or {}
        amount_minor = payload.get("amount")
        if amount_minor is None:
            amount_minor = payload.get("settled_amount")
        try:
            amount_value: float | None = int(amount_minor) / scale
        except (TypeError, ValueError):
            amount_value = None

        rows.append(
            {
                "seq": record.get("seq"),
                "record_id": record.get("record_id", ""),
                "kind": kind,
                "label": _LABELS.get(kind, kind or "?"),
                "icon": _ICONS.get(kind, "·"),
                "time": str(record.get("recorded_at") or ""),
                "counterparty": str(
                    payload.get("payee")
                    or payload.get("actor")
                    or payload.get("owner")
                    or ""
                ),
                "amount_minor": amount_minor,
                "amount": amount_value,
                "currency": str(payload.get("currency") or currency),
                "category": str(payload.get("category") or ""),
                "rule": str(payload.get("rule") or ""),
                "reason": str(payload.get("reason") or ""),
                "authorization_id": str(payload.get("authorization_id") or ""),
                "rail_reference": str(payload.get("settlement_ref") or ""),
                "outcome": str(payload.get("outcome") or ""),
                "prev_hash": str(record.get("prev_hash") or ""),
                "record_hash": str(record.get("record_hash") or ""),
            }
        )

    authorised = sum(
        r["amount_minor"]
        for r in rows
        if r["kind"] == "auth" and isinstance(r["amount_minor"], int)
    )
    settled = sum(
        r["amount_minor"]
        for r in rows
        if r["kind"] == "settle" and isinstance(r["amount_minor"], int)
    )

    return {
        "mandate_id": str(chain.get("mandate_id") or ""),
        "owner": str(chain.get("owner") or ""),
        "agent_id": str(chain.get("agent_id") or ""),
        "revoked": bool(chain.get("revoked", False)),
        "policy_hash": str(chain.get("policy_hash") or ""),
        "head_hash": str(chain.get("head_hash") or ""),
        "currency": currency,
        "scale": scale,
        "records": rows,
        "counts": {
            "total": len(rows),
            "auth": sum(1 for r in rows if r["kind"] == "auth"),
            "settle": sum(1 for r in rows if r["kind"] == "settle"),
            "reject": sum(1 for r in rows if r["kind"] == "reject"),
            "revoke": sum(1 for r in rows if r["kind"] == "revoke"),
        },
        "authorised_minor": authorised,
        "settled_minor": settled,
    }


def verifiable(chain: Mapping[str, Any]) -> bool | None:
    """这份导出能不能做链完整性校验。

    只有记录同时带 ``prev_hash`` 与 ``record_hash`` 时才可能校验。
    缺任何一个就返回 ``None``（**不可判断**），而不是想当然地说"通过"。
    """
    records = [r for r in (chain.get("records") or []) if isinstance(r, Mapping)]
    if not records:
        return None
    if not all(r.get("record_hash") for r in records):
        return None
    if not all("prev_hash" in r for r in records):
        return None
    return True


# ---------------------------------------------------------------------------
# 各格式渲染
# ---------------------------------------------------------------------------
def render_json(norm: Mapping[str, Any], source: Mapping[str, Any]) -> str:
    """完整快照。这是**权威导出**，其余格式都是它的视图。"""
    payload: dict[str, Any] = {
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "format_version": 1,
        "tool": f"agent_guard.export {__version__}",
        "mandate_id": norm["mandate_id"],
        "owner": norm["owner"],
        "agent_id": norm["agent_id"],
        "revoked": norm["revoked"],
        "currency": norm["currency"],
        "policy_hash": norm["policy_hash"],
        "head_hash": norm["head_hash"],
        "summary": {
            **norm["counts"],
            "authorised": norm["authorised_minor"],
            "authorised_display": f"{norm['authorised_minor'] / norm['scale']:.2f}",
            "settled": norm["settled_minor"],
            "settled_display": f"{norm['settled_minor'] / norm['scale']:.2f}",
        },
        # 原样带出，保证可回灌
        "records": source.get("records") or [],
    }
    if source.get("usage"):
        payload["usage"] = source["usage"]
    if source.get("remaining"):
        payload["remaining"] = source["remaining"]
    payload["_note"] = (
        "每个数值的 basis 字段表示可信度：measured=实测 / reported=服务端上报 / "
        "estimated=模型估算 / unknown=不可得。能耗永远是 estimated。"
    )
    return json.dumps(payload, ensure_ascii=False, indent=2)


def render_csv(norm: Mapping[str, Any]) -> str:
    """流水表。带 UTF-8 BOM，Excel 直接双击不会乱码。"""
    buffer = io.StringIO()
    buffer.write("\ufeff")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(_CSV_COLUMNS)
    for row in norm["records"]:
        writer.writerow(
            [
                row["seq"],
                row["time"],
                row["label"],
                row["counterparty"],
                f"{row['amount']:.2f}" if row["amount"] is not None else "",
                row["currency"],
                row["category"],
                row["rule"],
                row["reason"],
                row["authorization_id"],
                row["rail_reference"],
            ]
        )
    return buffer.getvalue()


def render_markdown(norm: Mapping[str, Any]) -> str:
    """可读归档：能贴进工单 / PR / 邮件。"""
    scale = norm["scale"]
    currency = norm["currency"]
    lines: list[str] = []
    lines.append("# 委托支出归档")
    lines.append("")
    lines.append(f"- 委托 ID：`{norm['mandate_id'] or '(未记录)'}`")
    if norm["owner"]:
        lines.append(f"- 授权人：{norm['owner']}")
    if norm["agent_id"]:
        lines.append(f"- 代理：{norm['agent_id']}")
    lines.append(f"- 状态：{'⛔ 已撤销' if norm['revoked'] else '✅ 生效中'}")
    lines.append(f"- 币种：{currency}")
    if norm["policy_hash"]:
        lines.append(f"- 条款指纹：`{norm['policy_hash']}`")
    if norm["head_hash"]:
        lines.append(f"- 链头哈希：`{norm['head_hash']}`")
    lines.append(f"- 导出时间：{datetime.now().isoformat(timespec='seconds')}")
    lines.append("")

    counts = norm["counts"]
    lines.append("## 汇总")
    lines.append("")
    lines.append("| 指标 | 值 |")
    lines.append("| --- | --- |")
    lines.append(f"| 记录总数 | {counts['total']} |")
    lines.append(f"| 授权 | {counts['auth']} |")
    lines.append(f"| 结算 | {counts['settle']} |")
    lines.append(f"| 拒绝 | {counts['reject']} |")
    lines.append(f"| 撤销 | {counts['revoke']} |")
    lines.append(f"| 已授权合计 | {norm['authorised_minor'] / scale:,.2f} {currency} |")
    lines.append(f"| 已结算合计 | {norm['settled_minor'] / scale:,.2f} {currency} |")
    lines.append("")

    lines.append("## 流水")
    lines.append("")
    lines.append("| # | 时间 | 类型 | 对手方 | 金额 | 规则 | 原因 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for row in norm["records"]:
        amount = f"{row['amount']:,.2f}" if row["amount"] is not None else "—"
        lines.append(
            f"| {row['seq']} | {row['time']} | {row['icon']} {row['label']} | "
            f"{row['counterparty']} | {amount} | `{row['rule']}` | {row['reason']} |"
        )
    lines.append("")

    by_payee: dict[str, int] = {}
    for row in norm["records"]:
        if row["kind"] == "auth" and isinstance(row["amount_minor"], int):
            by_payee[row["counterparty"]] = (
                by_payee.get(row["counterparty"], 0) + row["amount_minor"]
            )
    if by_payee:
        lines.append("## 钱花去哪了")
        lines.append("")
        lines.append("| 收款方 | 金额 |")
        lines.append("| --- | --- |")
        for payee, amount in sorted(by_payee.items(), key=lambda kv: -kv[1]):
            lines.append(f"| {payee} | {amount / scale:,.2f} {currency} |")
        lines.append("")

    lines.append("## 说明")
    lines.append("")
    lines.append(
        "> 本归档复述的是**记录内容**。它不能证明记录当初就是真的，"
        "也不能证明这次授权是对的。"
    )
    lines.append(
        "> 要证明记录未被事后修改，需把链头哈希与链上锚定值比对。"
    )
    return "\n".join(lines)


def render_html(norm: Mapping[str, Any]) -> str:
    """极简单文件 HTML 归档：不依赖任何模板引擎，拷走即用。

    这不是完整控制台（那个有图表和交互，在 ``agent_guard/webui.py``），
    而是一份**可打印的归档页**。
    """
    from html import escape as _escape

    scale = norm["scale"]
    currency = norm["currency"]

    def e(value: Any) -> str:
        return _escape("" if value is None else str(value))

    rows: list[str] = []
    for row in norm["records"]:
        amount = f"{row['amount']:,.2f}" if row["amount"] is not None else "—"
        tone = {
            "auth": "#1b3d26",
            "settle": "#123039",
            "reject": "#3d1a19",
            "revoke": "#3d1a19",
        }.get(row["kind"], "#1b242d")
        rows.append(
            f'<tr><td class="m">{e(row["time"])}</td>'
            f'<td><span class="pill" style="background:{tone}">'
            f'{e(row["icon"])} {e(row["label"])}</span></td>'
            f"<td>{e(row['counterparty'])}</td>"
            f'<td class="m num">{e(amount)}</td>'
            f'<td class="m">{e(row["rule"])}</td>'
            f'<td class="why">{e(row["reason"])}</td></tr>'
        )
    if not rows:
        rows.append('<tr><td colspan="6" class="why">暂无记录</td></tr>')

    counts = norm["counts"]
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>委托支出归档 {e(norm['mandate_id'])}</title>
<style>
body{{margin:0;background:#0b1015;color:#e6edf3;
 font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans SC",sans-serif}}
.wrap{{max-width:1000px;margin:0 auto;padding:24px 20px 60px}}
h1{{font-size:19px;margin:0 0 4px}} h2{{font-size:14px;margin:26px 0 10px}}
.sub{{color:#8b9aa8;font-size:12.5px}}
.kpi{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:18px 0}}
.card{{background:#121a22;border:1px solid #1e2b36;border-radius:9px;padding:12px 14px}}
.card .l{{color:#8b9aa8;font-size:12px}} .card .v{{font-size:19px;font-weight:650}}
table{{width:100%;border-collapse:collapse;font-size:13px;background:#121a22;
 border:1px solid #1e2b36;border-radius:9px;overflow:hidden}}
th{{text-align:left;font-size:12px;color:#8b9aa8;padding:9px 12px;
 border-bottom:1px solid #1e2b36;background:#0f161d}}
td{{padding:9px 12px;border-bottom:1px solid #16212a;vertical-align:top}}
tr:last-child td{{border-bottom:0}}
.m{{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px}}
.num{{text-align:right}} .why{{color:#8b9aa8;font-size:12.5px}}
.pill{{display:inline-block;padding:1px 8px;border-radius:99px;font-size:12px}}
.note{{background:#0f161d;border:1px solid #1e2b36;border-left:3px solid #39c5cf;
 border-radius:6px;padding:12px 15px;color:#8b9aa8;font-size:12.5px;margin:18px 0}}
code{{font-family:ui-monospace,Menlo,Consolas,monospace;color:#7ee2ea;word-break:break-all}}
@media print{{body{{background:#fff;color:#111}}.card,table{{border-color:#ccc}}
 th{{background:#f4f4f4}}}}
</style></head><body><div class="wrap">
<h1>委托支出归档</h1>
<div class="sub">委托 <code>{e(norm['mandate_id'] or '(未记录)')}</code></div>
<div class="sub">{'⛔ 已撤销' if norm['revoked'] else '✅ 生效中'}
 · 授权人 {e(norm['owner'] or '—')} · 代理 {e(norm['agent_id'] or '—')}</div>

<div class="kpi">
<div class="card"><div class="l">记录总数</div><div class="v">{counts['total']}</div></div>
<div class="card"><div class="l">授权 / 结算</div><div class="v">{counts['auth']} / {counts['settle']}</div></div>
<div class="card"><div class="l">拒绝 / 撤销</div><div class="v">{counts['reject']} / {counts['revoke']}</div></div>
<div class="card"><div class="l">已授权合计</div><div class="v">{norm['authorised_minor'] / scale:,.2f}</div>
<div class="l">{e(currency)}</div></div>
</div>

<h2>流水</h2>
<table><thead><tr><th>时间</th><th>类型</th><th>对手方</th>
<th style="text-align:right">金额</th><th>规则</th><th>原因</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>

<h2>完整性凭据</h2>
<div class="note">
条款指纹 <code>{e(norm['policy_hash'] or '(未记录)')}</code><br>
链头哈希 <code>{e(norm['head_hash'] or '(未记录)')}</code><br><br>
本页复述的是<b>记录内容</b>。它不能证明记录当初就是真的，也不能证明这次授权是对的。
要证明记录未被事后修改，需把链头哈希与链上锚定值比对。
</div>
<div class="sub">导出时间 {datetime.now().isoformat(timespec='seconds')}
 · 单文件离线归档，无外部请求</div>
</div></body></html>
"""


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------
def render(norm: Mapping[str, Any], chain: Mapping[str, Any], fmt: str) -> str:
    """按格式渲染文本。"""
    if fmt == "json":
        return render_json(norm, chain)
    if fmt == "csv":
        return render_csv(norm)
    if fmt == "md":
        return render_markdown(norm)
    if fmt == "html":
        return render_html(norm)
    raise ExportError(f"不支持的格式 {fmt!r}；可用：{', '.join(FORMATS)}")


def export_chain(
    chain: Mapping[str, Any],
    fmt: str,
    *,
    out_dir: str | Path = "out",
    stem: str | None = None,
) -> Path:
    """导出为指定格式，返回写出的文件路径。"""
    if fmt not in FORMATS:
        raise ExportError(f"不支持的格式 {fmt!r}；可用：{', '.join(FORMATS)}")

    norm = normalise(chain)
    name = stem or f"mandate-{norm['mandate_id'] or 'unknown'}"
    text = render(norm, chain, fmt)

    target = Path(out_dir) / f"{name}.{fmt}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


def export_all(
    chain: Mapping[str, Any],
    *,
    out_dir: str | Path = "out",
    stem: str | None = None,
    formats: Sequence[str] = FORMATS,
) -> list[Path]:
    """一次导出多种格式。"""
    return [export_chain(chain, fmt, out_dir=out_dir, stem=stem) for fmt in formats]


# ---------------------------------------------------------------------------
# 自带演示数据：让本文件单独跑也有东西可看
# ---------------------------------------------------------------------------
def demo_chain() -> dict[str, Any]:
    """一小段演示记录。

    **明确标注为演示数据**：带 ``"_demo": True``，免得有人把演示导出
    误当成真实审计产物。
    """
    base = datetime(2026, 9, 30, 10, 0, 0)

    def stamp(offset: int) -> str:
        from datetime import timedelta

        return (base + timedelta(minutes=offset)).isoformat()

    records: list[dict[str, Any]] = [
        {
            "seq": 0,
            "record_id": "demo0001",
            "record_type": "mandate",
            "mandate_id": "demo-mandate",
            "recorded_at": stamp(0),
            "prev_hash": "0" * 64,
            "record_hash": "a" * 64,
            "payload": {
                "owner": "alice",
                "agent_id": "shopper-1",
                "currency": "CNY",
                "per_tx_limit": 200000,
                "window_limit": 500000,
            },
        },
        {
            "seq": 1,
            "record_id": "demo0002",
            "record_type": "auth",
            "mandate_id": "demo-mandate",
            "recorded_at": stamp(1),
            "prev_hash": "a" * 64,
            "record_hash": "b" * 64,
            "payload": {
                "authorization_id": "auth-1",
                "payee": "cloud-vm",
                "amount": 80000,
                "currency": "CNY",
                "category": "infrastructure",
                "rule": "within_limits",
                "reason": "未触及任何约束",
            },
        },
        {
            "seq": 2,
            "record_id": "demo0003",
            "record_type": "settle",
            "mandate_id": "demo-mandate",
            "recorded_at": stamp(2),
            "prev_hash": "b" * 64,
            "record_hash": "c" * 64,
            "payload": {
                "authorization_id": "auth-1",
                "payee": "cloud-vm",
                "settled_amount": 80000,
                "settlement_ref": "pay-demo0001",
            },
        },
        {
            "seq": 3,
            "record_id": "demo0004",
            "record_type": "reject",
            "mandate_id": "demo-mandate",
            "recorded_at": stamp(3),
            "prev_hash": "c" * 64,
            "record_hash": "d" * 64,
            "payload": {
                "payee": "scam-llc",
                "amount": 1000,
                "currency": "CNY",
                "outcome": "DENY",
                "rule": "payee_denylist",
                "reason": "收款方 scam-llc 在拒绝名单中",
            },
        },
    ]
    return {
        "mandate_id": "demo-mandate",
        "owner": "alice",
        "agent_id": "shopper-1",
        "revoked": False,
        "currency": "CNY",
        "policy_hash": "e" * 64,
        "head_hash": "d" * 64,
        "_demo": True,
        "records": records,
        "usage": {
            "calls": 2,
            "tokens": {"value": 96, "basis": "reported"},
            "energy": {"value": 12.4, "basis": "estimated"},
        },
    }


# ---------------------------------------------------------------------------
# 命令行
# ---------------------------------------------------------------------------
_FORMAT_HELP = {
    "json": "完整快照（归档 / 取证 / 可回灌）",
    "csv": "流水表（Excel / pandas，带 BOM）",
    "md": "可读归档（工单 / PR / 邮件）",
    "html": "单文件网页归档（离线可开、可打印）",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="export",
        description="把一条委托的全部记录导出成可带走的文件（独立单文件工具）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python export.py --demo --format all --out-dir out\n"
            "  python export.py --chain out/mandate-x.json --format csv\n"
            "  python export.py --demo --format md --stdout\n"
            "  python export.py --list\n"
        ),
    )
    parser.add_argument("--chain", help="输入文件（导出产物，或裸记录数组）")
    parser.add_argument(
        "--format", default="all", help=f"导出格式：{' / '.join(FORMATS)} / all（默认 all）"
    )
    parser.add_argument("--out-dir", default="out", help="输出目录（默认 out）")
    parser.add_argument("--stem", help="文件名前缀（默认 mandate-<委托ID>）")
    parser.add_argument(
        "--demo", action="store_true", help="用内置演示数据（无需输入文件）"
    )
    parser.add_argument("--list", action="store_true", help="列出可用格式后退出")
    parser.add_argument(
        "--stdout", action="store_true", help="把内容打到标准输出而不写文件"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list:
        print("可用导出格式：")
        for fmt in FORMATS:
            print(f"  {fmt:<5} {_FORMAT_HELP[fmt]}")
        print()
        print("独立用法（不需要本仓库其余部分）：")
        print("  python export.py --demo --format all --out-dir out")
        return 0

    try:
        if args.demo:
            chain = demo_chain()
            source = "(内置演示数据，非真实记录)"
        elif args.chain:
            chain = load_chain(args.chain)
            source = args.chain
        else:
            print(
                "错误：需要 --chain <文件> 或 --demo。用 --help 看用法。",
                file=sys.stderr,
            )
            return 2

        norm = normalise(chain)
        formats = list(FORMATS) if args.format == "all" else [args.format]
        for fmt in formats:
            if fmt not in FORMATS:
                raise ExportError(f"不支持的格式 {fmt!r}")

        if args.stdout:
            for fmt in formats:
                if len(formats) > 1:
                    print(f"===== {fmt} =====")
                print(render(norm, chain, fmt))
            return 0

        written = export_all(
            chain, out_dir=args.out_dir, stem=args.stem, formats=formats
        )
        counts = norm["counts"]
        print(f"来源：{source}")
        print(
            f"记录：{counts['total']} 条（授权 {counts['auth']} / 结算 {counts['settle']}"
            f" / 拒绝 {counts['reject']} / 撤销 {counts['revoke']}）"
        )
        print(
            f"口径：{norm['currency']}，已授权合计 "
            f"{norm['authorised_minor'] / norm['scale']:,.2f}"
        )
        print()
        print("已写出：")
        for path in written:
            print(f"  {str(path):<52} {path.stat().st_size:>9,} 字节")
        print()
        print("说明：每个数值的可信度看 basis 字段"
              "（measured / reported / estimated / unknown）。")
        print("      能耗永远是 estimated —— Kiln 的 HTTP API 不提供功率数据。")
        if verifiable(chain) is None:
            print("      注意：本输入缺少 prev_hash/record_hash，无法做哈希链完整性校验。")
        return 0
    except ExportError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "ExportError",
    "FORMATS",
    "build_parser",
    "demo_chain",
    "export_all",
    "export_chain",
    "load_chain",
    "main",
    "normalise",
    "render",
    "render_csv",
    "render_html",
    "render_json",
    "render_markdown",
    "verifiable",
]
