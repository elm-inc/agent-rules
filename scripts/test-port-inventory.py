#!/usr/bin/env python3
"""port-inventory.py の解析ロジックの回帰テスト (依存なし・pytest 不要)。

ここで固定しているのは、いずれも実際に取りこぼしていた形。
壊れても実行時エラーにならず「衝突なし」と静かに嘘をつく種類のバグなので、
機械で押さえる価値が高い (codex-review 指摘 P1/P2 群)。

実行: python3 scripts/test-port-inventory.py
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("port-inventory.py")
spec = importlib.util.spec_from_file_location("port_inventory", MODULE_PATH)
assert spec and spec.loader
pi = importlib.util.module_from_spec(spec)
# dataclass は解決時に sys.modules から自分のモジュールを引くため、
# exec_module の前に登録しておく必要がある
sys.modules[spec.name] = pi
spec.loader.exec_module(pi)

failures: list[str] = []


def check(label: str, got, want) -> None:
    if got != want:
        failures.append(f"{label}: got {got!r}, want {want!r}")


# --------------------------------------------------------------------------
# compose short syntax: ホスト側ポートと、その環境変数名
# --------------------------------------------------------------------------

check("素の host:container",
      pi.host_port_and_var("3100:3000", {}), (3100, None))
check("ip:host:container",
      pi.host_port_and_var("127.0.0.1:55433:5432", {}), (55433, None))
check("変数 + 既定値 (ホスト側の変数名を返すこと)",
      pi.host_port_and_var("${BIND:-127.0.0.1}:${DB_PORT:-55433}:5432", {}),
      (55433, "DB_PORT"))
check(".env が既定値より優先されること",
      pi.host_port_and_var("${DB_PORT:-55433}:5432", {"DB_PORT": "60000"}),
      (60000, "DB_PORT"))
# IPv6 ホスト表記。素朴に ':' で split すると 4 分割以上になって落ちていた
check("IPv6 ホスト表記",
      pi.host_port_and_var("[::1]:5173:5173", {}), (5173, None))
check("IPv6 ワイルドカード",
      pi.host_port_and_var("[::]:8080:80", {}), (8080, None))
# 単体指定はホスト側がランダム割当 = 「確保」ではないので宣言に数えない
check("単体指定は宣言に数えない",
      pi.host_port_and_var("6006", {}), (None, None))
check("空文字",
      pi.host_port_and_var("", {}), (None, None))
check("ポート範囲は先頭だけ見る",
      pi.host_port_and_var("8000-8010:8000", {}), (8000, None))

# --------------------------------------------------------------------------
# compose long syntax: published は明示的なホストポート (short の単体とは逆の意味)
# --------------------------------------------------------------------------

check("long syntax の数値",
      pi.scalar_port("55433", {}), (55433, None))
check("long syntax の変数 + 既定値",
      pi.scalar_port("${DB_PORT:-55433}", {}), (55433, "DB_PORT"))
check("long syntax で .env 優先",
      pi.scalar_port("${DB_PORT:-55433}", {"DB_PORT": "60000"}), (60000, "DB_PORT"))

# --------------------------------------------------------------------------
# 台帳: 人が手で書く YAML なので不正値でクラッシュしない
# --------------------------------------------------------------------------

reg = pi.Registry(path=Path("/dev/null"), exists=True, projects={
    "ok": {"range": [13000, 13099]},
    "not_a_dict": "oops",
    "bad_values": {"range": [13000, "oops"]},
    "wrong_length": {"range": [13000]},
    "reversed": {"range": [13099, 13000]},
    "no_range": {"note": "帯を宣言していない案件"},
})
check("正常な帯", reg.range_of("ok"), (13000, 13099))
check("エントリがマッピングでない", reg.range_of("not_a_dict"), None)
check("数値でない値", reg.range_of("bad_values"), None)
check("要素数が違う", reg.range_of("wrong_length"), None)
check("開始 > 終了", reg.range_of("reversed"), None)
check("range 未指定", reg.range_of("no_range"), None)
check("未知の案件", reg.range_of("missing"), None)

# 明示ポート列 (慣用ポートで帯にまとまらない案件用)
reg2 = pi.Registry(path=Path("/dev/null"), exists=True, projects={
    "blocked": {"range": [13000, 13099]},
    "legacy": {"ports": [3000, 5432, 6379]},
    "both": {"range": [20000, 20009], "ports": [3306]},
    "bad_ports": {"ports": "3000"},
    "bad_item": {"ports": [3000, "x"]},
})
check("ポート列を読む", reg2.ports_of("legacy"), {3000, 5432, 6379})
check("ポート列が無ければ空", reg2.ports_of("blocked"), set())
check("リストでない ports は無視", reg2.ports_of("bad_ports"), set())
check("数値でない要素だけ落とす", reg2.ports_of("bad_item"), {3000})

check("帯だけの案件も宣言済み", reg2.declares("blocked"), True)
check("ポート列だけの案件も宣言済み", reg2.declares("legacy"), True)
check("未登録の案件", reg2.declares("missing"), False)

check("帯の中は許可", reg2.allows("blocked", 13050), True)
check("帯の外は不許可", reg2.allows("blocked", 14000), False)
check("列挙されたポートは許可", reg2.allows("legacy", 5432), True)
check("列挙されていないポートは不許可", reg2.allows("legacy", 5433), False)
check("帯と列の併用 (帯側)", reg2.allows("both", 20005), True)
check("帯と列の併用 (列側)", reg2.allows("both", 3306), True)
check("帯と列の併用 (どちらでもない)", reg2.allows("both", 3307), False)

# --------------------------------------------------------------------------
# IPv4/IPv6 の二重行を畳む
# --------------------------------------------------------------------------

folded = pi.fold_dual_stack([
    pi.Live(port=3100, bind="0.0.0.0", source="docker", project="a", detail="c1 → 3000/tcp"),
    pi.Live(port=3100, bind="::", source="docker", project="a", detail="c1 → 3000/tcp"),
    pi.Live(port=3200, bind="0.0.0.0", source="docker", project="b", detail="c2 → 3000/tcp"),
])
check("二重行が 1 行に畳まれる", len(folded), 2)
check("bind が併記される", folded[0].bind, "0.0.0.0+::")
check("別ポートは畳まれない", folded[1].port, 3200)

# 中身が違うものは畳まない (別コンテナが同じポートを別 bind で持つ場合)
not_folded = pi.fold_dual_stack([
    pi.Live(port=8080, bind="127.0.0.1", source="docker", project="a", detail="c1 → 80/tcp"),
    pi.Live(port=8080, bind="10.0.0.1", source="docker", project="b", detail="c2 → 80/tcp"),
])
check("中身が違えば畳まない", len(not_folded), 2)

# --------------------------------------------------------------------------
# 推測マーカーの付け外し
# --------------------------------------------------------------------------

check("マーカーを剥がす", pi.strip_marker("sega-pos ~"), "sega-pos")
check("マーカー無しはそのまま", pi.strip_marker("sega-pos"), "sega-pos")
check("末尾が ~ でも空白が無ければ剥がさない", pi.strip_marker("foo~"), "foo~")

# --------------------------------------------------------------------------
# ss の users:() パース
# --------------------------------------------------------------------------

line = 'LISTEN 0 511 127.0.0.1:5174 0.0.0.0:* users:(("node",pid=1385314,fd=20))'
m = pi.SS_USERS_RE.search(line)
check("プロセス名", m.group("name") if m else None, "node")
check("pid", m.group("pid") if m else None, "1385314")
check("root 所有行はマッチしない",
      pi.SS_USERS_RE.search("LISTEN 0 4096 0.0.0.0:9100 0.0.0.0:*"), None)

# --------------------------------------------------------------------------
# worktree パス → 本体 repo
# --------------------------------------------------------------------------

check("worktree でないパスは None",
      pi.main_repo_of_worktree_path(Path("/tmp/nonexistent/foo/bar")), None)

# --------------------------------------------------------------------------

if failures:
    print(f"FAIL: {len(failures)} 件")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("ok: port-inventory の解析ロジック 全件通過")
