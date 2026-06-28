# Pokemon TCG AI Battle Challenge

## 概要

**コンペ名**: The Pokémon Company - PTCG AI Battle Challenge Simulation  
**ホスト**: Kaggle (スポンサー: The Pokémon Company)  
**目標**: ポケモントレーディングカードゲーム（TCG）のAIエージェントを構築し、銅メダル獲得を目指す

エージェント同士がリミテッドカードバトルで対戦し、勝率でリーダーボード順位が決まる。

---

## ディレクトリ構成

```
pokemonAI-myspace/
├── archive/              # 対戦リプレイデータ（JSONファイル、約5,063件）
├── card_images/          # カード画像（JPG、1,267枚）
├── data/
│   ├── EN_Card_Data.csv  # カードデータ英語版（MAX_CARD_ID=1267）
│   ├── JP_Card_Data.csv  # カードデータ日本語版
│   ├── Card_ID List_EN.pdf
│   └── Card_ID List_JP.pdf
├── sample_submission/    # サンプルエージェント（ランダム選択）
├── submission/           # 現在の提出エージェント（NN + ルールベースハイブリッド）
│   ├── main.py           # ハイブリッドエージェント（MCTS + NN fallback）
│   ├── deck.csv          # ルカリオデッキ
│   ├── ptcg_best_model.pth      # ★ 現在の最良モデル（53.8% vs baseline）
│   ├── ptcg_league_model.pth    # リーグ学習モデル（51.6% vs baseline）
│   ├── ptcg_rl_model.pth        # PPO自己対戦モデル（参考用）
│   ├── ptcg_baseline_model.pth  # 模倣学習モデル（基準）
│   └── ptcg_normalization.npz   # 正規化パラメータ（mean/std）
├── training/             # 学習スクリプト群
│   ├── train_model.py           # 模倣学習（archive/ → baseline モデル）
│   ├── train_model_weighted.py  # 重み付き模倣学習（Kaggle向け）
│   ├── train_rl_local.py        # PPO自己対戦（ローカルCPU）
│   ├── train_rl_league.py       # リーグ学習 v1
│   ├── train_rl_best.py         # リーグ学習 v2（KLペナルティ・ベスト保存）★推奨
│   └── eval_1000.py             # 1000戦評価スクリプト
├── logs/                 # 学習ログ
│   ├── train_rl_log.txt
│   ├── train_league_log.txt
│   ├── train_best_log.txt
│   └── eval_log.txt
├── kaggle_training/      # Kaggle自動学習パイプライン
│   ├── kaggle_run.py              # 自動学習スクリプト（push→監視→ダウンロード）
│   ├── kernel-metadata.json       # Kaggle kernelの設定（GPU無効・CPU実行）
│   ├── ptcg_weighted_train.ipynb  # 重み付き模倣学習ノートブック
│   ├── leaderboard.csv            # リーダーボードCSV（重み付き学習用）
│   └── output/                    # ダウンロードされた出力ファイル置き場
├── PTCGstadium/          # ローカル対戦・評価環境
│   ├── arena.py          # エージェント間対戦スクリプト
│   ├── play_local.py     # リプレイHTML生成
│   └── agents/
│       ├── baseline/main.py   # baseline モデルエージェント
│       ├── rl/main.py         # RL自己対戦モデルエージェント
│       ├── league/main.py     # リーグモデルエージェント
│       └── best/main.py       # ★ 現在の最良モデルエージェント
├── デッキ集/             # 各種デッキCSV
│   ├── deck_ルカリオ.csv
│   ├── deck_ドラパルト.csv
│   └── deck_イワパレス.csv
├── ルカリオデッキの回し方.txt
└── Competition Rules.txt
```

---

## ゲームエンジン（cg ライブラリ）

`submission/cg/` にプリコンパイル済みバイナリ：
- `cg.dll` (Windows) / `libcg.so` (Linux/Kaggle環境)

### 主要API（`cg/api.py`）

| 関数 | 説明 |
|------|------|
| `to_observation_class(obs_dict)` | dict → Observation クラスに変換 |
| `all_card_data()` | 全カードデータ取得 |
| `all_attack()` | 全アタックデータ取得 |
| `search_begin(...)` | モンテカルロ探索の起点を設定 |
| `search_step(search_id, select)` | 探索を1ステップ進める |
| `search_end()` | 探索終了・メモリ解放 |

### エージェントのインターフェース

```python
def agent(obs_dict: dict) -> list[int]:
    obs = to_observation_class(obs_dict)
    if obs.select is None:
        return read_deck_csv()  # 初期デッキ選択: 60枚のCard IDリスト
    return [chosen_index]       # 通常ターン: obs.select.option のインデックス
```

### Observationの構造

```
Observation
├── select: SelectData | None
│   ├── type: SelectType         # MAIN, CARD, ATTACK, YES_NO, COUNT, ...
│   ├── context: SelectContext
│   ├── minCount / maxCount
│   └── option: list[Option]
├── logs: list[Log]
└── current: State | None
    ├── turn, yourIndex, firstPlayer
    ├── supporterPlayed, energyAttached, retreated
    └── players: list[PlayerState]
        ├── active, bench, hand, deckCount
        ├── discard, prize
        └── poisoned, burned, asleep, paralyzed, confused
```

---

## 現在の提出モデル

### モデルアーキテクチャ（全モデル共通）
```
FC(5658 → 1024) + LayerNorm + ReLU + Dropout(0.3)  ← 模倣学習のみ Dropout あり
FC(1024 → 512)  + LayerNorm + ReLU
FC(512 → 256)   ← 出力: 256クラス（選択肢インデックス）
```
- 入力次元: 5658（MAX_CARD_ID=1267 基準）
- パラメータ数: 6,454,016

### モデル一覧と実力（1000戦 vs baseline 評価済み）

| ファイル | 学習手法 | baseline 勝率 | 備考 |
|----------|---------|-------------|------|
| `ptcg_best_model.pth` | リーグ学習v2 | **53.8%** | ★ 現在の最良・提出用 |
| `ptcg_league_model.pth` | リーグ学習v1 | 51.6% | v2 の出発点 |
| `ptcg_baseline_model.pth` | 模倣学習（Kaggle） | 基準 | — |
| `ptcg_rl_model.pth` | PPO自己対戦 | ~48% | baseline より劣る |

### submission/main.py のモデル優先順位
```python
for candidate in ("ptcg_best_model.pth", "ptcg_league_model.pth",
                  "ptcg_rl_model.pth", "ptcg_baseline_model.pth"):
```

---

## ローカル強化学習パイプライン

### 前提条件
- Python 仮想環境: `C:\venv`（短パスで作成、Windows 260文字制限対策）
- PyTorch CPU only（AMD Radeon 860M は CUDA 非対応）

### 学習スクリプト

#### 1. リーグ学習 v2（推奨）: `training/train_rl_best.py`
```bash
C:\venv\Scripts\python training\train_rl_best.py --iters 650 --games 24
```
**特徴**：
- KLペナルティ（β=0.01）: baseline から大きく逸脱しないよう正則化
- 50iter ごとに baseline と20戦して実力評価・ベストチェックポイント自動保存
- コサイン LR 減衰（5e-5 → 1e-5）
- リーグ初期メンバー3錨（baseline / rl_v0 / league_v0）
- 出力: `submission/ptcg_best_model.pth`

**学習結果（2026-06-28, 約400iter / 9600ゲーム）**：
- ベストチェックポイント: iter 150 で baseline 勝率 **53.8%**（1000戦確認）
- iter 150 以降は評価が 25-50% で不安定（リーグ多様化の影響）

#### 2. リーグ学習 v1: `training/train_rl_league.py`
```bash
C:\venv\Scripts\python training\train_rl_league.py --iters 300 --games 16
```
- 出力: `submission/ptcg_league_model.pth`（51.6% vs baseline）

#### 3. PPO自己対戦: `training/train_rl_local.py`
```bash
C:\venv\Scripts\python training\train_rl_local.py --iters 200 --games 20
```
- 出力: `submission/ptcg_rl_model.pth`
- 注意: 自己対戦はナッシュ均衡に収束するため baseline より弱くなりやすい

### 評価スクリプト: `training/eval_1000.py`
```bash
C:\venv\Scripts\python training\eval_1000.py --games 1000
```
- `ptcg_best_model.pth` vs baseline
- `ptcg_league_model.pth` vs baseline
- 100戦ごとに中間報告

### ローカル対戦アリーナ: `PTCGstadium/arena.py`
```bash
$env:PYTHONIOENCODING='utf-8'
C:\venv\Scripts\python PTCGstadium\arena.py agents/best agents/baseline --games 100
```
- `PTCGstadium/agents/` 以下のエージェントを対戦させる
- `best/`, `league/`, `baseline/`, `rl/` が利用可能

---

## Kaggle 自動学習パイプライン（模倣学習）

### 使い方

```bash
# 最新エピソードで学習・完了まで待機・submission/にコピー（フルパイプライン）
python kaggle_training/kaggle_run.py

# pushのみ（完了を待たない）
python kaggle_training/kaggle_run.py --push

# 現在のステータス確認
python kaggle_training/kaggle_run.py --status

# 出力のダウンロードのみ
python kaggle_training/kaggle_run.py --download
```

### 処理フロー
1. `kaggle API` で最新エピソードデータセットを自動検索
2. `kernel-metadata.json` の `dataset_sources` を更新
3. `kaggle kernels push` でノートブックをKaggle にアップロード・実行開始
4. 60秒ごとにステータスをポーリング
5. COMPLETE になったら `ptcg_baseline_model.pth` と `ptcg_normalization.npz` をダウンロード
6. `submission/` に自動コピー

### kernel-metadata.json の設定
- `enable_gpu: false` — KaggleのCPUで実行（GPU非互換問題を回避）
- `competition_sources: ["pokemon-tcg-ai-battle"]` — EN_Card_Data.csv の取得元
- `dataset_sources: [最新エピソードデータセット]` — 毎回自動更新

---

## 現在のデッキ（ルカリオデッキ）

`submission/deck.csv` に記録。主要ポケモン：
- **メガルカリオex** - メインアタッカー（はどうづき / メガブレイブ）
- **リオル** - メガルカリオexの進化前
- **ハリテヤマ** - サブアタッカー（ワイルドプレス）
- **マクノシタ** - ハリテヤマの進化前
- **ソルロック** - コスモビームで低HP処理
- **ルナトーン** - ルナサイクル特性でエネルギー加速

戦略詳細は `ルカリオデッキの回し方.txt` 参照。
他デッキは `デッキ集/` に保存。

---

## 対戦データ

### ローカル archive/
- 約5,063件のJSONファイル
- 各ファイルに1対戦分のステップごとの observation・action・reward が格納
- 報酬: 勝利=1, 敗北=-1, 引き分け=0

### Kaggle エピソードデータセット（日次更新）
- `kaggle/pokemon-tcg-ai-battle-episodes-YYYY-MM-DD` の形式で毎日公開
- 1データセットあたり約5,919件のJSONファイル（約750MB）
- `kaggle_run.py` が最新データセットを自動検出して使用する

---

## 既知の技術的問題と対処法

### 1. Kaggle GPU と PyTorch の CUDA 非互換
**症状**: `AcceleratorError: CUDA error: no kernel image is available for execution on the device`  
**原因**: Kaggle が割り当てる GPU（Blackwell 系等）が PyTorch の CUDA カーネルに未対応  
**対処**: `kernel-metadata.json` で `enable_gpu: false` にして CPU 実行（約10分）

### 2. label_smoothing + masked_fill(-1e9) による loss 異常値
**症状**: CrossEntropyLoss が 9700万などの異常値になる  
**原因**: `label_smoothing=0.1` が -1e9 マスク位置にも勾配を分配する  
**対処**: `nn.CrossEntropyLoss()` で `label_smoothing` を使わない

### 3. Windows の Python 3.13 で torch DLL エラー
**症状**: `ImportError: DLL load failed while importing _C`  
**原因**: AMD Radeon 860M は CUDA 非対応（ROCm は Linux のみ）  
**対処**: `C:\venv` に CPU-only PyTorch をインストール（短パスで 260 文字制限回避）

### 4. Windows 260 文字パス制限
**症状**: `pip install torch` が OSError で失敗  
**対処**: `C:\venv` という短パスで仮想環境を作成する

### 5. arena.py の UnicodeEncodeError（cp932）
**症状**: 日本語含む print 文がエラー  
**対処**: `$env:PYTHONIOENCODING='utf-8'` を設定してから実行

### 6. PPO自己対戦でのモデル退行
**症状**: 自己対戦で学習したモデルが baseline より弱くなる  
**原因**: 自己対戦はナッシュ均衡（じゃんけん）に収束するため、絶対的な強さにならない  
**対処**: リーグ学習（多様な固定対戦相手）を使う

---

## 次にすべき改善

優先度順：

1. **MCTSとの組み合わせ**（最効果大）
   - `search_begin` / `search_step` / `search_end` APIを使ったモンテカルロ木探索
   - 現在のNNをMCTSのrollout評価関数として使う
   - 時間制限（例: 1秒/ターン）を設けて探索

2. **リーダーボード重み付きリーグ学習**
   - 高スコアプレイヤーの行動を優先的に模倣学習してから RL
   - `kaggle_training/leaderboard.csv` を Kaggle dataset としてアップロード
   - `kernel-metadata.json` の `dataset_sources` に追加

3. **KLベータの調整・長期学習**
   - `train_rl_best.py` で `--kl-beta 0.005` に下げてより自由に探索させる
   - iter 150 付近でのピーク（53.8%）を超えるための実験

4. **データ品質フィルタ**
   - 長いゲーム（例: 30ターン以上）の勝者のみ学習（実力勝ちの可能性が高い）

5. **全SelectTypeをNN化**
   - MAIN以外（カード選択、YES/NO判断など）もNNで学習

---

## 提出要件

- `main.py` の `agent(obs_dict)` 関数が必須エントリーポイント
- デッキは `deck.csv`（60行、各行はCard ID）
- 1デッキ: 同一カードは最大4枚（ACE SPECは1枚）
- 提出時は `/kaggle_simulations/agent/` にファイルが配置される
- **ネットワーク不可**: 実行中の外部通信禁止

---

## 開発環境

- Python 3.13（Windows 11）
- GPU: AMD Radeon 860M（CUDA非対応 → ローカルでの torch 学習は CPU のみ）
- ローカル学習環境: `C:\venv`（CPU-only PyTorch）
- Kaggle 模倣学習: `python kaggle_training/kaggle_run.py` で全自動
- Kaggle認証: `~/.kaggle/kaggle.json`（username: aoao0314）
