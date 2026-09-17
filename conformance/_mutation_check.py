"""
变异测试：验证 conformance 的 E 组真的能抓到违规，而不是空转。

用法（在仓库根目录）：
    python conformance/_mutation_check.py

它把参考适配器复制到临时文件，注入三类违规，各跑一次套件，断言**必须失败**：

    M1  增设第六要素        → E-1 必须失败
    M2  同一条规则声明两种形态 → E-2 必须失败
    M3  声明了策略但无规则依据 → E-4 必须失败

不改动任何仓库文件（临时文件跑完即删）。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ADAPTER = ROOT / "reference" / "conformance_adapter.py"
# 变异体必须落在 reference/ 里 —— 适配器要 `from engine import ...`，
# 而 engine.py 与它同目录（原文件靠 sys.path 注入自己所在目录实现）。
MUTANT_DIR = ROOT / "reference"
MUTANT_PREFIX = ".mutation_tmp_"

MUTATIONS = {
    "M1 增设第六要素": (
        "        return [f\"{u.where}: {u.field}\" for u in m.unsupported]",
        "        return [f\"{u.where}: {u.field}\" for u in m.unsupported] + [\"Order: routing_preference\"]",
        "E-1",
    ),
    "M2 一条规则两种形态": (
        'return [{"target": owner, "forms": forms}\n                for owner, forms in self._iter_rules()]',
        'return [{"target": owner, "forms": ["requires", "derived_by"]}\n                for owner, forms in self._iter_rules()]',
        "E-2",
    ),
    "M3 策略无依据": (
        '    def declared_strategies(self) -> list[dict]:',
        '    def declared_strategies(self) -> list[dict]:\n        return [{"id": "route_pref", "basis_rule_ids": []}]',
        "E-4",
    ),
}


def run_suite(adapter_path: Path) -> tuple[int, str]:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    p = subprocess.run([sys.executable, str(HERE / "run.py"), str(adapter_path)],
                       capture_output=True, text=True, encoding="utf-8",
                       env=env, cwd=str(ROOT))
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    src = ADAPTER.read_text(encoding="utf-8")

    # 基线：未变异必须全绿
    code, out = run_suite(ADAPTER)
    if code != 0:
        print("❌ 基线失败：未变异的适配器就没跑过")
        print(out)
        return 2
    print("✅ 基线：未变异适配器全绿")

    bad = 0
    for name, (old, new, clause) in MUTATIONS.items():
        if src.count(old) != 1:
            print(f"❌ {name}: 注入锚点未唯一命中（{src.count(old)} 次）——锚点需更新")
            bad += 1
            continue
        mutated = MUTANT_DIR / f"{MUTANT_PREFIX}{uuid.uuid4().hex[:8]}.py"
        mutated.write_text(src.replace(old, new, 1), encoding="utf-8")
        try:
            code, out = run_suite(mutated)
        finally:
            mutated.unlink(missing_ok=True)
        caught = (code != 0) and re.search(rf"\[E {re.escape(clause)}\]", out)
        if caught:
            print(f"✅ {name}: 被 {clause} 抓住")
        else:
            print(f"❌ {name}: **没被抓住**（期望 {clause} 失败）")
            print(out)
            bad += 1

    print()
    if bad:
        print(f"变异测试失败 {bad} 项：E 组用例存在空转")
        return 1
    print("变异测试全部通过：E 组的三类违规都能被抓住")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
