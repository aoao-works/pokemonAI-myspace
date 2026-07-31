# Pokemon TCG AI Battle Challenge

**目標**: Kaggle コンペでポケモン TCG の AI エージェントを構築し、銅メダル獲得を目指す。
エージェント同士がリミテッドカードバトルで対戦し、勝率でリーダーボード順位が決まる。
最上位は狙わず、銅メダル（上位10%）ラインを安定して超えることがゴール。締切は
2026-08-16 23:59。

**現在の方針**: NNモデルは廃止し、**完全ルールベースのイワパレス（壁）デッキ**に一本化した。
理由や過去の試行錯誤の経緯はメモリシステム（project memory: `iwaparesu-*` 系）を参照。

---

## 現在の提出エージェント

- **開発本体**: `PTCGstadium/agents/iwaparesu_yoshida_v2/main.py` + `deck.csv`
  ここを編集する。改善のたびに `submission/`（main.py・deck.csv・`PTCGstadium/cg/` の
  エンジンSDK一式）へ同期してから `kaggle competitions submit` で提出する。
- 戦略の核: イワパレスの特性「しんぴのいしやど」＝相手の**ex**ポケモンの攻撃ダメージを
  無効化する壁デッキ。ただし「相手の効果を無視する」ワザ（例: メガミミロップexの
  スパイクホッパー）には貫通されるので無敵ではない（`_ignores_defender_effects()` で対応済み）。
  弱点は炎タイプ（弱点2倍は免除効果と無関係に通る）。
- 過去の主要な発見: 実戦リプレイ解析で「サイド差は互角/有利なのに場のポケモンと手札を
  使い切って負ける」パターンが敗因の大半を占めることが判明（詳細は project memory
  `iwaparesu-replay-analysis-20260731` および `PTCGstadium/agents/iwaparesu_yoshida_v2/IMPROVEMENT_LOG.md`）。
  火力不足ではなくリソース枯渇が本質的な弱点。

---

## 「baseline」について

`PTCGstadium/agents/archive/baseline/` がローカル評価用の固定・最強クラスのルールベース
相手（面白いことに、こちらと同じイシズマイ/イワパレス系統を含むデッキ）。ただし
**ローカルのbaseline勝率は実際のKaggleスコアの信頼できる代理指標ではない**ことが
判明済み（相手プールが狭く、非推移的な相性が確認されている）。ローカルテストは
「クラッシュ・エラーが無いかの確認」用に留め、改善判断の主軸は
**実際のKaggleリプレイデータ解析**に置くこと（下記参照）。

---

## ディレクトリ構成（現状）

```
pokemonAI-myspace/
├── submission/                        # ★ 実際にKaggleへ提出するパッケージ
│   ├── main.py / deck.csv             # iwaparesu_yoshida_v2 と同期させる
│   └── cg/                            # エンジンSDK（PTCGstadium/cg/ からコピー）
├── PTCGstadium/                       # ローカル対戦・評価環境
│   ├── arena.py                       # エージェント間対戦（スモークテスト用）
│   ├── cg/                            # エンジンSDK本体（.dll/.so 含む）
│   └── agents/
│       ├── iwaparesu_yoshida_v2/      # ★ 開発本体（ここを編集）
│       │   └── IMPROVEMENT_LOG.md     # 自動ループの作業ログ（日付順）
│       ├── iwaparesu_yoshida_v3/      # 派生バリアント（比較参考用）
│       └── archive/                   # ローカル対戦相手プール（baseline, sakaki 等）
├── automation/                        # ローカル自動化ループ（下記参照）
│   ├── loop_prompt.txt                # ループのプロンプト本体
│   ├── run_loop.ps1                   # タスクスケジューラから呼ばれるラッパー
│   └── logs/                          # 各実行のログ
└── heroz_replays/                     # 対戦リプレイ抽出ツール（別件）
```

`kaggle_training/`・`training/`・`logs/` 等の旧NN学習パイプラインは廃止・削除済み。

---

## 自動改善ループ

**目的**: 6時間ごとに自動で「Kaggle実戦リプレイを解析 → 根拠のある改善を1つ実施 →
軽くスモークテスト → 提出 → ログに記録してコミット・プッシュ」を繰り返す。

**実行方式（ローカル / Windowsタスクスケジューラ）**:
- タスク名: `IwaparesuKaggleLoop`（6時間おき、スリープからの復帰込みで設定済み）
- 実体: `automation/run_loop.ps1` → `claude -p` を `--permission-mode bypassPermissions`
  で非対話実行し、`automation/loop_prompt.txt` の内容を標準入力で渡す
- ログ: `automation/logs/run_<timestamp>.log`
- **夜間などPCをスリープにしておけば、タイマーで自動的に起きて実行される**想定
  （AC電源接続時のみ有効。バッテリー駆動時はスリープ解除タイマーが無効）
- スクリプト変更時の注意: このプロジェクトのパスは日本語を含むため、`.ps1` ファイルは
  **UTF-8 BOM付き**で保存すること（Windows PowerShell 5.1はBOM無しだとシステムの
  ANSIコードページで読み込み、日本語パスが文字化けする）。プロンプトは長いため
  コマンドライン引数ではなく**標準入力（パイプ）**で渡すこと（cmd.exe経由の
  コマンドライン長制限 約8191文字を超えるため）。

**クラウド版ルーチン（`schedule`スキル / Claude Code routines）は現状使えない**:
Kaggle APIへの外向き通信がクラウド環境のポリシーでブロックされ、GitHubへの書き込み
権限も無い（read-only連携）。直すには claude.ai 側の環境設定・GitHub連携の権限を
変更する必要があるが、具体的な設定場所は未確認。詳細は project memory
`iwaparesu-kaggle-loop-routine` を参照。

**ループの判断方針**:
- ローカルアリーナのbaseline勝率は「壊れていないか」の確認のみに使う（勝率が
  下がった/変わらないだけでは変更を差し戻さない）
- 判断の根拠は `kaggle competitions episodes` / `replay` で取得した**実戦リプレイ**
  （サイド差だけでなく `active`/`bench`/`hand` の最終状態も見ること）
- 1日の提出回数には上限があるので、根拠の薄い変更でむやみに提出しない
- 進捗・知見は必ず `IMPROVEMENT_LOG.md` に追記してからコミット・プッシュする
  （次回実行は毎回まっさらなセッションなので、これが唯一の引き継ぎ手段）

---

## 開発環境

- Python 3.13 / Windows 11
- 仮想環境: `C:\venv`（短パス必須、Windows 260文字制限対策）
- Kaggle認証: `~/.kaggle/kaggle.json`（username: aoao0314）
- コンソール出力で日本語が化ける場合は `PYTHONIOENCODING=utf-8` を設定する

コマンド例・技術的な問題・失敗した試み・次の改善策の詳細はメモリシステム
（project memory）を参照。

---

## 提出要件

- `main.py` の `agent(obs_dict)` 関数が必須エントリーポイント
- デッキは `deck.csv`（60行、同一カード最大4枚、ACE SPECは1枚）
- 提出時は `/kaggle_simulations/agent/` に配置される
- **ネットワーク不可**: 実行中の外部通信禁止（エンジンSDKは `cg/` として同梱すること）
