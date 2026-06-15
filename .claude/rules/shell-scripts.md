---
paths:
  - "scripts/*.sh"
---

# シェルスクリプト規約 (agent-rules/scripts)

このリポの `scripts/*.sh` を編集・新規作成するときの規約 (vLLM オンデマンド機構の構築で確立)。

- 冒頭は `set -uo pipefail`。`-e` は付けない (健全性チェックの非ゼロ終了でスクリプトごと落ちるのを避ける)。
- **sudo 不要**で書く。docker 操作は docker グループ所属前提。systemd 管理リソースは `systemctl is-active --quiet` で検出し、管理下なら干渉しない (相互 churn 防止)。
- **awk の比較は必ず括弧で囲む**: `awk 'END{print ((s+0)>0?1:0)}'`。括弧なし `print (s+0)>0?1:0` は `>` が**出力リダイレクトに解釈**され、stdout が空 + cwd にファイル `0` を生成する (実害バグ)。
- **検知ロジックは fail-safe**: メトリクス/ヘルス取得に失敗したら危険側 (停止・実行) でなく安全側 (スキップ・現状維持) に倒す。該当行が 0 本なら空を返して判定を見送る等。
- **デタッチ常駐は flock + setsid**: 単一起動は `setsid flock -n /tmp/x.lock bash worker.sh </dev/null >>log 2>&1 9>&-` (`9>&-` で親の起動ロックを子に継承させない)。ロックパスは `/tmp` 固定 (`TMPDIR` 変動で単一化が破れる)。
- **`docker run` に `--rm` を付けない**: 異常終了時に `docker logs` を残すため。起動前に `docker rm -f` で掃除する方式に統一。
- 並行起動し得る処理は `flock` で直列化し、ロック取得後に状態を再チェックする (worktree 並列で殺し合わない)。
- 実機検証してからコミットする (起動・推論・停止・後片付けまで通す)。
