#!/usr/bin/env python3
"""单一入口转发 —— 真正的实现在 :mod:`agent_guard.export`。

为什么这么安排
--------------
导出工具的实现必须**随包一起安装**，否则 ``pip install`` 之后再调导出就会坏掉
（根目录的文件不进 wheel）。所以实现放在包里，本文件只负责让仓库根目录也有一个
``python export.py`` 的直接入口——方便克隆仓库后立刻用，不必先安装。

包内的 :mod:`agent_guard.export` 本身是**自包含的**（不 import 本包其他模块，
只用标准库），所以想要"单文件拷走"时，直接拷那个文件即可::

    cp agent_guard/export.py /somewhere/export.py
    python /somewhere/export.py --demo --format all --out-dir out

用法（在仓库根目录）::

    python export.py --demo --format all --out-dir out
    python export.py --chain out/chain.json --format csv
    python export.py --list
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    from agent_guard import export as _impl
except ImportError as exc:  # pragma: no cover
    sys.stderr.write(
        "找不到 agent_guard.export。本文件需要仓库根目录在 sys.path 上。\n"
        f"已尝试加入：{_ROOT}\n"
        "若只想用单文件版本，直接拷 agent_guard/export.py 单独运行。\n"
    )
    raise SystemExit(2) from exc

ExportError = _impl.ExportError
FORMATS = _impl.FORMATS
build_parser = _impl.build_parser
demo_chain = _impl.demo_chain
export_all = _impl.export_all
export_chain = _impl.export_chain
load_chain = _impl.load_chain
main = _impl.main
normalise = _impl.normalise
render = _impl.render
render_csv = _impl.render_csv
render_html = _impl.render_html
render_json = _impl.render_json
render_markdown = _impl.render_markdown
verifiable = _impl.verifiable

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

if __name__ == "__main__":
    raise SystemExit(_impl.main())
