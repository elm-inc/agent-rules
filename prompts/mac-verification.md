# Prompt: Mac 側 iOS 実機検証

Linux 側で CI build が green になった iOS プロジェクトを、Mac 側のセッションで `xcodegen` → Xcode → iPhone 実機の流れで動作確認するときに使う Claude Code 起動時のプロンプト。

## 前提

Mac 側で事前に:

- `agent-rules` を `~/repos/github.com/elm-inc/agent-rules` に clone + `install.sh` 完了
- 該当プロジェクト repo を clone 済み
- Xcode 16+, xcodegen (brew), gh CLI (`tomohisa-masaki` プロファイル active) が揃う

詳細手順は各プロジェクトの `docs/design/mac-verification.md` に置く (drive-partner に標準形のサンプルあり)。

---

## 最短版

```
このリポジトリ (iOS プロジェクト) を Mac の iPhone 実機で動作確認したい。
docs/design/mac-verification.md の手順に従って進めてください。
途中で詰まったらエラー解析を提案、設計レベルの問題なら /adr-new も提案して。
```

---

## フル版

```
このリポジトリを Mac の iPhone 実機で動作確認するセッションです。
Linux 側で CI build は green になっています。

事前確認:
- agent-rules が clone 済 & install.sh 完了状態か
- gh CLI で tomohisa-masaki プロファイルが active か (`gh auth status` 実行)
- Xcode と xcodegen が入っているか

手順 (詳細は docs/design/mac-verification.md):
1. 不足するツールを段階的に確認、見つかったらインストール提案
2. xcodegen generate で .xcodeproj 生成
3. Xcode で開いて Signing & Capabilities を Apple ID チームに設定
4. iPhone を接続してデバイス選択
5. ⌘R で Build & Run
6. アプリ起動後、設定画面で API キーを入力 (該当プロジェクトで Claude API 利用時)
7. 検証項目チェックリスト (docs/design/mac-verification.md の section 8) を順に消化、結果を報告

エラー時の方針:
- ビルドエラー → Mac 側で修正 → commit/push (gh プロファイル確認)
- 設計レベルの問題 → /adr-new で ADR 起票、docs/architecture/ も更新提案
- 不明点は Linux 側セッションに戻って相談

完了報告に含めてほしい内容:
- 検証項目チェックリストの結果 (○/×)
- 気づき・問題点・想定外の挙動
- 修正したらコミットハッシュ
```

---

## 期待される報告内容

Mac セッションが完了したら、Linux 側 / project memory にフィードバックを残す:

- 検証項目チェックリストの ○/× 結果
- 失敗・要修正項目とその対応
- 修正コミット / 起票した ADR の番号

---

## トラブルシュート

| 症状 | 対応 |
|---|---|
| Signing が通らない | Xcode → Settings → Accounts で Apple ID 追加、project の Signing & Capabilities で Team 選択 |
| 実機にデプロイできない | iPhone 側「設定 → 一般 → VPN とデバイス管理」で開発者証明書を信頼 |
| `xcodegen` 不在 | `brew install xcodegen` |
| gh push が失敗 (`Repository not found`) | `gh auth switch -u tomohisa-masaki` で elm-inc 用プロファイルに切替 (`_chd` と混同していないか確認) |
| AVFoundation / Speech / CoreLocation 関連の起動時エラー | Info.plist の usage description が project.yml から正しく生成されているか確認 |
| 7 日で失効した | 個人 Apple ID は 7 日で証明書失効。Xcode で再ビルドすれば再発行される (本格運用は Apple Developer Program $99/年) |
