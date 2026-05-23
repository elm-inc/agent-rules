---
name: webcam-jetson
description: Jetson (Tailscale 経由) に常駐する webcam サーバ (mediamtx + Python aiohttp) からスナップショット / 録画 / ライブ視聴 URL を取得する。Jetson に Logitech 等の USB カメラを繋いで MJPEG / RTSP / HLS で映像を取り出したいときに使用
argument-hint: <subcommand> [options] | snapshot | record | stream-url | install | status | restart | logs
disable-model-invocation: false
allowed-tools: Bash(uv *) Bash(ssh *) Bash(scp *) Bash(rsync *) Bash(ls *) Bash(cat *) Bash(mkdir *) Bash(test *) Read Write
---

# Webcam Jetson

Jetson (例: `jetson-nano` on Tailscale) に USB カメラ (例: Logitech C920) を接続し、Jetson 側で常駐する 2 つの systemd サービスを介してホスト側 (この CLI) から映像を取り出す。

## アーキテクチャ

```
                    ┌──────────────── Jetson (Tailscale: jetson-nano) ────────────────┐
                    │                                                                  │
   /dev/video0  ──► │  ffmpeg (V4L2 capture, runOnInit)                               │
                    │      │ publish (MJPEG copy)                                      │
                    │      ▼                                                            │
                    │  mediamtx ──► RTSP :8554/cam   HLS :8888/cam   API 127.0.0.1:9997│
                    │      ▲                                                            │
                    │      │ pull (RTSP TCP)                                            │
                    │  webcam_server.py (aiohttp :8088)                                │
                    │      ├─ GET  /snapshot.jpg     (ffmpeg -frames:v 1)              │
                    │      ├─ GET  /stream.mjpg      (ffmpeg -f mpjpeg)                │
                    │      ├─ POST /record?duration  (ffmpeg -t N, mkv copy or mp4)    │
                    │      ├─ GET  /recordings/<n>   (download)                        │
                    │      ├─ GET  /recordings       (list)                            │
                    │      └─ GET  /healthz                                            │
                    └──────────────────────────────────────────────────────────────────┘
                                       ▲                                ▲
                                       │ HTTP (Tailnet)                 │ SSH
                                       │                                │
                                  ┌────┴─────────────────────────────┐  │
                                  │  webcam_jetson.py (this skill)    │──┘
                                  └───────────────────────────────────┘
```

- 1 プロセスで `/dev/video0` を占有する制約は mediamtx に集約。Python は ffmpeg を spawn する薄い HTTP ラッパー。
- mediamtx の RTSP/HLS/WebRTC エンドポイントは Tailnet 経由でそのまま VLC / mpv / ブラウザから視聴可。

## 接続先の解決順

各オプションは以下の順で解決される (上が優先):

1. CLI 引数 (`--host`, `--port`, `--ssh-host`)
2. 環境変数 (`WCAM_HTTP_HOST`, `WCAM_HTTP_PORT`, `WCAM_SSH_HOST`)
3. `~/.config/webcam-jetson.toml`
4. デフォルト (`jetson-nano:8088`, `elmo@jetson-nano`)

### 設定ファイルの例

`~/.config/webcam-jetson.toml`:

```toml
http_host = "jetson-nano"
http_port = 8088
ssh_host  = "elmo@jetson-nano"
```

## 実行スクリプト

`scripts/webcam_jetson.py` は PEP 723 inline metadata で依存 (`httpx`) を宣言した uv self-contained スクリプト。

```bash
uv run ${SKILL_DIR}/scripts/webcam_jetson.py <subcommand> [options]
```

手動で叩く場合は agent-rules リポ配下の `skills/webcam-jetson/scripts/webcam_jetson.py`、または `install.sh` 実行後の symlink `~/.claude/skills/webcam-jetson/scripts/webcam_jetson.py` を指定する。

## サブコマンド

### `install`

`server/` を SSH 越しに Jetson にコピーし、Jetson 上で `install.sh` を実行する。idempotent。

```bash
uv run ${SKILL_DIR}/scripts/webcam_jetson.py install
uv run ${SKILL_DIR}/scripts/webcam_jetson.py install --ssh-host elmo@jetson-nano
```

install.sh が Jetson 上で行うこと:

1. `apt install ffmpeg python3-venv v4l-utils curl` (system 依存)
2. `mediamtx` aarch64 バイナリを GitHub Releases から取得し `/usr/local/bin/mediamtx` へ配置
3. `/etc/webcam-jetson/mediamtx.yml` に config 配置
4. `/opt/webcam-jetson/venv` を作成し `aiohttp` を入れる
5. `webcam_server.py` を `/opt/webcam-jetson/` に配置
6. `/var/lib/webcam-jetson/recordings/` を作成
7. systemd unit `webcam-mediamtx.service` / `webcam-server.service` を enable + start
8. 接続用 URL を表示

ユーザは `video` グループに追加される (sudo 必要)。初回は再ログインが必要なケースあり。

### `snapshot`

カメラから 1 枚 JPEG を取得し保存。

```bash
uv run ${SKILL_DIR}/scripts/webcam_jetson.py snapshot
uv run ${SKILL_DIR}/scripts/webcam_jetson.py snapshot -o desk.jpg
uv run ${SKILL_DIR}/scripts/webcam_jetson.py snapshot --width 640 --height 360
```

デフォルトファイル名: `snapshot_YYYYMMDD_HHMMSS.jpg`

| オプション | 説明 |
|---|---|
| `-o <path>` | 出力ファイルパス |
| `--width <px>` `--height <px>` | リサイズ (`scale=W:H`) |

### `record`

N 秒録画して MKV/MP4 で保存。Jetson 側で録画 → 完了後に HTTP でダウンロード。

```bash
uv run ${SKILL_DIR}/scripts/webcam_jetson.py record -d 10
uv run ${SKILL_DIR}/scripts/webcam_jetson.py record -d 30 -f mp4 -o robot_run.mp4
```

| オプション | 説明 |
|---|---|
| `-d, --duration <sec>` | 録画秒数 (1〜3600、デフォルト 10) |
| `-f, --format mkv\|mp4` | `mkv`=MJPEG copy (低 CPU)、`mp4`=H.264 re-encode (libx264 veryfast) |
| `-o <path>` | 出力ファイルパス |

Jetson 側の `/var/lib/webcam-jetson/recordings/` には直近 50 ファイルを残し古いものは自動削除される。

### `stream-url`

ライブ視聴の URL とコピペ用コマンドを表示する。

```bash
uv run ${SKILL_DIR}/scripts/webcam_jetson.py stream-url mjpeg     # ブラウザ / mpv / ffplay
uv run ${SKILL_DIR}/scripts/webcam_jetson.py stream-url rtsp      # vlc / ffplay / mpv (低 latency)
uv run ${SKILL_DIR}/scripts/webcam_jetson.py stream-url hls       # ブラウザ (Safari ネイティブ)
```

| プロトコル | URL 形式 | 用途 |
|---|---|---|
| `mjpeg` | `http://<host>:8088/stream.mjpg` | ブラウザ直接視聴・最低 latency |
| `rtsp`  | `rtsp://<host>:8554/cam` | OBS / VLC / 解析パイプライン |
| `hls`   | `http://<host>:8888/cam/index.m3u8` | iOS Safari / 長時間視聴 |

### `status`

`systemctl status` (SSH 経由) と `/healthz` JSON を表示。

```bash
uv run ${SKILL_DIR}/scripts/webcam_jetson.py status
```

### `restart`

Jetson 上で両 service を再起動 (sudo 経由)。

```bash
uv run ${SKILL_DIR}/scripts/webcam_jetson.py restart
```

### `logs`

`journalctl -u` を SSH 越しに引く。

```bash
uv run ${SKILL_DIR}/scripts/webcam_jetson.py logs
uv run ${SKILL_DIR}/scripts/webcam_jetson.py logs --unit webcam-mediamtx -n 200
```

## 引数の解釈

`$ARGUMENTS` を以下の流れで解釈する:

1. 先頭トークンがサブコマンド (`snapshot` / `record` / `stream-url` / `install` / `status` / `restart` / `logs`) であることを確認
2. 残りを Python 側の argparse にそのまま渡す
3. サブコマンドが省略された場合はユーザに用途を確認する (画像 1 枚? 録画? ライブ視聴?)

## ポート一覧

| port | サービス | 用途 |
|---|---|---|
| 8088 | webcam-server (aiohttp) | HTTP API (snapshot / mjpeg / record / healthz) |
| 8554 | mediamtx | RTSP |
| 8888 | mediamtx | HLS |
| 9997 | mediamtx | local API (127.0.0.1 のみ bind) |

Tailnet 内 (jetson-nano) で全て直接到達可。外部公開する場合は Tailscale ACL / Funnel で絞ること。

## 注意事項

- 初回 `install` 時は SSH パスフレーズ + Jetson 側の sudo パスワードを聞かれる。`ssh-agent` と `sudoers` 設定済みなら無人で完走する。
- mediamtx の V4L2 → RTSP 経路は内部で ffmpeg を spawn する (MJPEG copy なので CPU ほぼゼロ)。
- C920 の MJPEG ネイティブ解像度は 1080p30 / 720p30。`server/mediamtx.yml` の解像度・FPS を変更したら `restart` する。
- 録画 mp4 (libx264) は Orin Nano で 720p30 が実時間以上で書ける。古い Jetson Nano (Maxwell) では遅い可能性あり。
- 同時 RTSP クライアントは mediamtx が無制限で fan-out するが、Tailscale の上り帯域に注意。
