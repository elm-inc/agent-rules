# モダン CLI ツール チートシート

Rust 製の置き換え CLI ツールを「旧コマンド」から逆引きできるリファレンス。
シェルからは `cheat <tool>`、Claude Code からは `/cli-help <tool>` で参照する。

## 旧 → 新 早見表

| 旧 (これを打ったら) | 新 (こっちが速い/見やすい) | セクション |
|---|---|---|
| `grep -rn`     | `rg`         | [rg](#rg) |
| `find . -name` | `fd`         | [fd](#fd) |
| `cat`          | `bat`        | [bat](#bat) |
| `ls -la`       | `eza -l`     | [eza](#eza) |
| `du -sh */`    | `dust`       | [dust](#dust) |
| `top` / `htop` | `btm`        | [btm](#btm) |
| `ps aux`       | `procs`      | [procs](#procs) |
| `git diff`     | `delta` (pager) | [delta](#delta) |
| `sed -i s/a/b/g` | `sd 'a' 'b'` | [sd](#sd) |
| `time CMD`     | `hyperfine CMD` | [hyperfine](#hyperfine) |
| `man` (要約)    | `tldr`       | [tldr](#tldr) |
| `cat foo.json \| jq \| less` | `jless foo.json` | [jless](#jless) |
| `wc -l **/*.py` | `tokei`     | [tokei](#tokei) |
| `cd ~/path/to/foo` | `z foo`   | [zoxide](#zoxide) |

詳細は各セクション。シェルでは `cheat rg` のように単体で呼べる。

---

## rg — 高速 grep (旧: grep -rn)

旧コマンドからの逆引き:
  grep -rn PAT .                  -> rg PAT
  grep -rni PAT .                 -> rg -i PAT
  grep -rn PAT --include='*.py'   -> rg -tpy PAT
  grep -rnL PAT .                 -> rg --files-without-match PAT

よく使う:
  rg PAT path/             基本 (デフォルトで再帰、.gitignore を尊重)
  rg -tpy PAT              .py のみ。-tjs / -tmd など (rg --type-list で一覧)
  rg -g '!node_modules' PAT  glob で除外
  rg -C3 PAT               前後 3 行
  rg -l PAT                マッチしたファイル名のみ
  rg --files | rg name     ファイル名で絞り込み
  rg --hidden PAT          隠しファイルも対象 (デフォルトは除外)

## fd — 直感的な find (旧: find . -name)

旧コマンドからの逆引き:
  find . -name '*.py'        -> fd -e py
  find . -name '*.py' -type f -> fd -e py -tf
  find . -name foo            -> fd foo
  find . -iname FOO           -> fd -i FOO

よく使う:
  fd PATTERN               部分一致 (正規表現)
  fd -e py                 拡張子で絞り込み
  fd -H .env               隠しファイル含む (デフォルトは除外)
  fd -tf -e log            通常ファイルかつ .log
  fd -td node_modules      ディレクトリのみ
  fd PATTERN -x rm         マッチしたものに対して実行 (xargs 不要)

## bat — syntax highlight 付き cat (旧: cat / less)

旧コマンドからの逆引き:
  cat file                 -> bat file
  cat file | less          -> bat file (デフォルトで paging)
  cat file (パイプ用)       -> bat --plain file  または bat -pp
  diff a b                 -> bat の --diff オプション (delta との併用も可)

よく使う:
  bat file                 基本 (色 + 行番号 + paging)
  bat -A file              タブ/改行などの不可視文字を可視化
  bat --plain file         装飾なし (スクリプトのパイプ用)
  bat -n file              行番号のみ
  bat -r 10:50 file        10〜50 行目のみ
  bat -p file              ヘッダなし

注意: Debian/Ubuntu で apt 経由だとバイナリ名が `batcat`。`cargo install bat` で `bat` にする。

## eza — git 統合のある ls (旧: ls)

旧コマンドからの逆引き:
  ls -la                   -> eza -la
  ls -l --color            -> eza -l
  tree -L 2                -> eza -T --level=2

よく使う:
  eza                      基本
  eza -l --git             git status 列付き (M/A/?)
  eza -la --git --icons    アイコン付き (Nerd Font 必要)
  eza -T --level=2         tree 表示 (2 階層)
  eza -l --sort=modified   更新日時順
  eza -l --total-size      ディレクトリの合計サイズも表示

## dust — 直感的な du (旧: du -sh */)

旧コマンドからの逆引き:
  du -sh */                -> dust
  du -h --max-depth=2      -> dust -d 2
  du -sh | sort -h         -> dust (デフォルトでサイズ順)

よく使う:
  dust                     カレント以下を視覚的に
  dust -d 2                深さ 2 まで
  dust -n 30               上位 30 件
  dust -r                  逆順 (大きい順がデフォルト)
  dust -X node_modules     除外
  dust path/               指定ディレクトリ

## btm — モダンな top (旧: top / htop)

旧コマンドからの逆引き:
  top                      -> btm
  htop                     -> btm

よく使う:
  btm                      基本 (CPU/メモリ/ネット/温度)
  btm -b                   basic モード (シンプル表示)
  btm -t                   tree モード (プロセスツリー)
  btm --battery            バッテリ表示
  (起動中) /              フィルタ
  (起動中) k or d          選択プロセスを kill
  (起動中) ?               ヘルプ

## procs — 読みやすい ps (旧: ps aux | grep)

旧コマンドからの逆引き:
  ps aux                   -> procs
  ps aux | grep node       -> procs node
  pstree                   -> procs --tree

よく使う:
  procs                    全プロセス
  procs node               名前で絞り込み
  procs --tree             tree 表示
  procs --watch            top のように継続更新
  procs --sortd cpu        CPU 降順
  procs --insert tcp       TCP ポート情報を追加列で表示

## delta — git diff の pager (旧: git diff)

導入 (.gitconfig に 1 回設定):
  [core]
      pager = delta
  [delta]
      navigate = true     # n/N で hunk 移動
      line-numbers = true
      side-by-side = true

その後は `git diff` / `git log -p` / `git show` が自動で delta 経由になる。

直接使う場合:
  delta a.txt b.txt        ファイル比較
  diff -u a b | delta      パイプで

## sd — 安全な sed (旧: sed -i s/a/b/g)

旧コマンドからの逆引き:
  sed -i 's/foo/bar/g' f   -> sd 'foo' 'bar' f
  sed 's/foo/bar/g'        -> echo ... | sd 'foo' 'bar'

よく使う:
  sd 'foo' 'bar' file      ファイル内置換 (デフォルトで全体)
  sd 'foo' 'bar' file1 file2 ...   複数ファイル
  sd -p 'foo' 'bar' file   preview (ファイル変更せず diff 表示)
  echo "foo" | sd 'foo' 'bar'  パイプで使用

注意: sd は正規表現がデフォルト (Rust regex)。エスケープは sed と微妙に異なる。複雑なケースは sed のまま使う方が安全。

## hyperfine — ベンチマーク (旧: time)

旧コマンドからの逆引き:
  time CMD                  -> hyperfine 'CMD'
  time CMD1; time CMD2      -> hyperfine 'CMD1' 'CMD2'  (比較)

よく使う:
  hyperfine 'cmd'                  基本 (デフォルト 10 回)
  hyperfine --warmup 3 'cmd'       3 回 warmup してから計測
  hyperfine --runs 50 'cmd'        50 回実行
  hyperfine 'a' 'b'                A と B の比較 (相対倍率も出る)
  hyperfine -L file a.json,b.json 'jq . {file}'  パラメータ化

## tldr — コマンドの要約 (旧: man)

旧コマンドからの逆引き:
  man tar (長い)            -> tldr tar (実用例 5 個)
  man --help                -> tldr <command>

よく使う:
  tldr tar                  代表的な使用例
  tldr --update             キャッシュを最新化
  tldr -l                   利用可能なコマンド一覧
  tldr -p linux tar         プラットフォーム指定

tealdeer (Rust 実装) を使うと高速。`cargo install tealdeer`。

## jless — JSON ビューア (旧: jq | less)

旧コマンドからの逆引き:
  cat foo.json | jq .       -> jless foo.json
  curl ... | jq . | less    -> curl ... | jless

よく使う:
  jless foo.json            ファイルを開く
  cmd | jless               パイプから
  (起動中) j/k              上下移動
  (起動中) h/l              折りたたみ / 展開
  (起動中) e/E              全展開 / 全折りたたみ
  (起動中) /pattern         検索
  (起動中) y                現在のパスを yank (jq 用)

## tokei — コード行数カウント (旧: wc -l)

旧コマンドからの逆引き:
  wc -l **/*.py             -> tokei -t Python
  find . -name '*.py' | xargs wc -l   -> tokei -t Python

よく使う:
  tokei                     カレント以下を言語別に集計
  tokei path/               指定パス
  tokei -t Python,Rust      言語フィルタ
  tokei --files             ファイル別の内訳
  tokei -o json             JSON 出力

## zoxide — 学習する cd (旧: cd)

導入 (.bashrc に既に書かれているか確認):
  eval "$(zoxide init bash)"

使い方:
  z foo                     "foo" を含む頻度の高いディレクトリへジャンプ
  z foo bar                 "foo" と "bar" 両方を含む方を優先
  zi                        fzf で対話選択 (fzf 必要)
  z -                       直前のディレクトリ
  zoxide query foo          ジャンプ先候補を表示 (デバッグ)

仕組み: cd した履歴を frecency (頻度 × 最近度) で記憶。最初は学習が必要なので、慣れるまでは普通の cd を併用してよい。
