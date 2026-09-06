#!/usr/bin/env bash
# seal.sh — 採点資産 (sealed/) の封印。ADR-0020 決定 6 の実装。
#
# 防御を二重にする:
#   1. 予防 — bwrap で sealed/ を read-only bind してアームを実行する
#   2. 検知 — 実行前後で sealed/ のハッシュを比較し、変化したら run を無効化する
#
# なぜ検知も要るか: bwrap が無い環境では予防が効かない。そこで
# 「たまたま攻撃されなかった」を成功と誤認しないよう、**常に検知を回す**。
# 予防が効かず検知だけの状態を "detect-only" として呼び出し側に伝える
# (ADR-0019 / ADR-0020 決定 7: 測れない・守れないことを黙って成功にしない)。

# sealed/ の内容ハッシュ (ファイル名込み。追加・削除・改変を検出する)
seal_manifest() {
  local dir="$1"
  find "$dir" -type f -printf '%P\n' 2>/dev/null | LC_ALL=C sort | while read -r f; do
    printf '%s  ' "$f"; sha256sum "$dir/$f" 2>/dev/null | cut -d' ' -f1
  done | sha256sum | cut -d' ' -f1
}

# 封印モードの判定: bwrap があれば enforce、無ければ detect-only
seal_mode() {
  if command -v bwrap >/dev/null 2>&1 && \
     bwrap --dev-bind / / --ro-bind /tmp /tmp true >/dev/null 2>&1; then
    echo enforce
  else
    echo detect-only
  fi
}

# アームを封印下で実行する。$1=sealed dir, 以降=実行するコマンド
run_sealed() {
  local sealed="$1"; shift
  if [ "$(seal_mode)" = "enforce" ]; then
    bwrap --dev-bind / / --ro-bind "$sealed" "$sealed" "$@"
  else
    "$@"
  fi
}
