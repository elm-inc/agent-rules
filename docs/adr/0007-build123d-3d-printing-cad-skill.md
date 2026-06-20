# ADR-0007: build123d + cad-khana による 3D プリンタ向け CAD スキル

## ステータス

採択 (2026-06-20)
<!-- /deepseek-redteam レビュー + ユーザー合意済み。境界反転(診断は skill 自前)・スキル名 /cad-print 確定・多材は段階導入。対象機種 Bambu A1 mini / X2D / H2D。 -->

## 文脈

Claude Code から **build123d**(OpenCASCADE/OCP ベースの Python パラメトリック CAD)で 3D プリンタ向けの造形をしたい。各プロジェクトでは具体的な造形指示を与えるが、以下の**横断的な関心事**を毎回手書きするのは非効率で品質も安定しない:

- build123d の**記述規約**(selector 安定化・builder/algebra・パラメータ集約・mm 既定 など)
- **干渉 / クリアランス / 肉厚**などの診断を回す**反復ループ**
- AI が形を判断するための **PNG 視覚フィードバック**
- 3D プリンタの**嵌合較正値**(クリアランス/圧入のオフセット。プリンタ×素材で変わる)

調査の結果、**cad-khana**(`cyberchitta/cad-khana`, Apache-2.0)が実在し、build123d をラップした診断ファーストの CLI + Claude skill であることを確認した。干渉(boolean intersection, epsilon 0.001mm³)・クリアランス(build123d `.distance_to()` = OCCT)・肉厚(三角メッシュからの ray-casting・近似)・オーバーハング(法線×ビルド方向)を `diagnostics.json` に出力し、`khana draw` はヘッドレスで HLR 正投影/等角の**線画 PNG/SVG** を出す。ただし **version 0.0.2 / Pre-Alpha** で API churn リスクがあり、**嵌合較正・シェーディング描画・規約・反復ループ統括**は持たない。

ローカル環境(ubuntu-ws)には CAD 系が一切未導入(build123d/OCP/trimesh/freecad なし、Python 3.12 + uv のみ)。OCP は数百 MB 級の重い依存。

## 決定

agent-rules に **`/cad-print` スキル**を新設し、「**横断知識とループの媒介**」と位置づける。cad-khana は丸ごと wrap せず、**強い領域(診断エンジン)に絞って活用**し、薄い/無い領域は skill が柔軟に実装する。

### 1. CAD 基盤は build123d
mm 既定・selector による topological naming 回避・OCP 由来の堅牢な boolean/distance・cad-khana が build123d 上に構築されている整合性から採用。

### 2. cad-khana は「強みの領域」で活用(pin して使う)
- **活用**: Assembly 組み立て + `assert_no_interference` / `assert_clearance`、`diagnostics.json` の構造化契約、`khana draw`(ヘッドレス正投影/等角の線画)。
- **pre-alpha 対策**: 依存は**コミット pin**し、skill 側に**薄いアダプタ層**(`khana_adapter`)を挟んで `diagnostics.json` スキーマ差異を吸収する(churn の影響を 1 箇所に閉じる)。

### 3. skill が所有する領域(khana が薄い/無い)
- **嵌合較正値**: `calibration.toml`(プリンタ×素材ごとの clearance/sliding/friction/press/elephant_foot)+ モデルが import する `fit()` ヘルパ。マジックナンバーを禁止し較正値を一点管理。
- **build123d 記述規約**の context 注入。
- **シェーディング多視点 PNG**(iso/front/top, trimesh+pyrender オフスクリーン)。khana draw の線画と**併用**(形=シェーディング、寸法/オーバーハング=線画)。
- **反復ループ統括**(編集→診断→描画→所見提示→調整)と **env bootstrap**(専用 uv venv をオンデマンド構築。ADR-0005 の `ensure-vllm` 方式を踏襲)。
- **肉厚の精密化オプション**(khana の ray 近似は FDM 既定として許容しつつ、精度要求時に OCP/voxel フォールバック)、**FDM 以外のプロセス profile**(resin 等)。

### 4. 反復ループ
`part.py 編集 → /cad-print build → (env-ensure → khana check → shaded+線画 render) → diagnostics.json 読込 + PNG 視認 → 調整 → pass で export(STEP/STL/3MF)`。

詳細仕様は [`docs/design/cad-print-skill.md`](../design/cad-print-skill.md)。

## 理由

- **重複排除**: 干渉/クリアランス/正投影は khana が既に堅実。再実装は無駄(ADR-0001 の「重複を作らない」)。
- **媒介価値の最大化**: 較正・規約・視覚ループ・環境という「プロジェクト横断で効く」部分に skill のコードを集中させる。
- **churn 隔離**: pre-alpha 依存をコミット pin + アダプタで囲い、上流変更の波及を局所化。
- **マルチモーダル活用**: シェーディング PNG で Claude が形の妥当性を直接判断でき、診断 JSON と二経路で収束を速める。
- **較正の一点管理**: 嵌合値を `fit()` に集約し、実機較正(`calib gauge`)の結果を全モデルへ即反映。

## 検討した代替案

### 代替案 A: cad-khana を使わず自前フル実装
- Pros: 外部依存ゼロ・完全制御。
- Cons: boolean 干渉・`.distance_to()`・HLR 正投影を作り直す手間。
- 不採用理由: khana の強い領域を捨てる無駄。強みは借り、弱みだけ補う方が得。

### 代替案 B: cad-khana を丸ごと wrap(skill = 薄いシェル)
- Pros: 実装最小。
- Cons: pre-alpha の churn を直に被る / 較正・シェーディング・規約が欠落 / khana のロードマップに縛られる。
- 不採用理由: ユーザー要件(較正・視覚・規約)を満たせず、依存リスクも高い。

### 代替案 C: CadQuery / OpenSCAD を基盤にする
- Pros: CadQuery は実績豊富、OpenSCAD は宣言的で軽量。
- Cons: build123d の selector モデルが優れ、khana も build123d 前提。OpenSCAD は Python 連携・内省が弱い。
- 不採用理由: エコシステム整合と selector 安定性で build123d 優位。

### 代替案 D: build123d-mcp(pzfreo)に描画・計測を委譲
- Pros: `render_view`・measure・FDM printability を持つ MCP。
- Cons: MCP 常駐の結合度・運用増。シェーディング描画は skill 内でも可能。
- 不採用理由: 第一選択にはしない。ただし将来の代替描画経路として design に残す。

## 帰結

### Pros
- 横断知識(較正・規約・ループ・環境)が単一ソース化、プロジェクトは造形指示に集中できる。
- 診断 JSON + シェーディング/線画 PNG の二経路で AI 反復が速く確実。
- 重複なし・churn 隔離・嵌合値の一点管理。

### Cons
- **pre-alpha 依存**(cad-khana 0.0.2): スキーマ/ API 変更リスク → pin + アダプタで緩和。
- **重い env**(OCP 数百 MB): オンデマンド venv 構築で常駐回避、初回のみ重い。
- **ヘッドレス GL リスク**: シェーディング描画に EGL/OSMesa が要る。ubuntu-ws での可否は実機確認(EGL→OSMesa→xvfb のフォールバック順)。
- **肉厚精度**: khana の ray 近似は FDM 既定で許容、精密要求時のみ OCP/voxel に切替。

### 実機検証 / 将来の検討事項
- ubuntu-ws で EGL/OSMesa オフスクリーンが動くか(動かなければ xvfb)。
- cad-khana の pin コミットで `diagnostics.json` スキーマ(現 0.2)を実測検証。
- OCP 入り venv の構築時間と容量を計測し、bootstrap の UX(進捗/タイムアウト)を ADR-0005 に倣って詰める。
- スライサ連携(3MF + プロファイル)は次段スコープ。

### 関連 ADR
- [ADR-0001](0001-multi-llm-development-workflow.md) — 重複排除・設計は Opus 起草 + /deepseek-redteam で redteam。
- [ADR-0005](0005-on-demand-local-llm.md) — オンデマンド env 構築 + アイドル管理パターンを踏襲。
- 詳細設計: [`docs/design/cad-print-skill.md`](../design/cad-print-skill.md)

## 追記 (2026-06-20 — /deepseek-redteam 反映)

DeepSeek-R1 によるレッドチームで Critical 級の指摘が出たため、決定 §2/§3 の**診断の境界を反転**し、要点を是正する(決定の骨子=「媒介スキル + khana の強み活用」は不変、責務配分を見直し)。

- **診断は skill が自前で持つ(境界の反転)**: 干渉 (`(a & b).volume > eps`) とクリアランス (`distance_to`) は build123d で数行かつ**安全クリティカル**なので、pre-alpha 依存に委ねず **skill が所有**する。肉厚・オーバーハングも自前(肉厚は trimesh voxel/SDF を主、ray は補助。細リブ/テーパーの**見逃しを自動フラグ**)。**干渉は独立手段でクロスチェック**し silent な誤判定を防ぐ。
- **cad-khana は唯一固有の価値に縮退して活用**: `khana draw` の **HLR 線画(OCCT・GL 不使用)** を主用途とし、Assembly/joint/animation は任意。**vendored(必要部分を取り込み)+ コミット pin**。khana 不在/失敗でも skill 単独で診断・シェーディング描画が回るよう **optional & degradable** にする。
- **`fit()` の物理セマンティクスを是正(Critical)**: 較正値は「設計クリアランス」ではなく **実機ガウジで実測した経験オフセット**(FDM の穴縮みを織り込む)と定義。`hole/peg/gap` で**符号と適用先を明示**(穴に gap を与えるのか相手を縮めるのか)。**elephant_foot は径オフセットでなく底面 chamfer 推奨**として分離。**XY/Z 異方性**を認め `fit` に軸別 (`xy`/`z`) を持てるようにする。**圧入**は「相手穴を干渉量だけ縮める/ペグを太らせる」を選択式に。
- **反復ループのガバナンス(Critical)**: 診断は pass/fail だけでなく **実測値とマージン**を返し、エージェントは比例調整する。**反復上限・単調改善要件・過補正のダンピング・収束しない時のユーザーエスカレーション**を停止条件に明記(振動/無限ループ防止)。
- **ヘッドレス GL 全滅時の正式フォールバック**: シェーディングが EGL/OSMesa/xvfb すべて不可でも、**HLR 線画(GL 不使用)で視覚ループを継続**。env bootstrap は **システムライブラリ(libgl1 / libosmesa6 / xvfb 等)の有無を確認**し不足を案内する。
- **part.py は subprocess + timeout で実行**: 無限ループ/暴走を遮断(任意コード実行は単一ユーザーの自己責任範囲だが、プロセス分離で巻き込み事故を防ぐ)。
- **selector の残余リスク**: index 禁止に加え、**位置述語・`group_by`・タグ(RigidJoint/label)** での同定を規約化(毎回スクラッチ再構築前提で staleness は持ち越さない)。

詳細は [`docs/design/cad-print-skill.md`](../design/cad-print-skill.md) に反映済み。
