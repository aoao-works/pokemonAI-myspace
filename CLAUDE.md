# Pokemon TCG AI Battle Challenge

## 概要

**コンペ名**: The Pokémon Company - PTCG AI Battle Challenge Simulation  
**ホスト**: Kaggle (スポンサー: The Pokémon Company)  
**目標**: ポケモントレーディングカードゲーム（TCG）のAIエージェントを構築し、銅メダル獲得を目指す

エージェント同士がリミテッドカードバトルで対戦し、勝率でリーダーボード順位が決まる。

---

## ⚠️ 重要：「baseline」の二重定義

このプロジェクトには **2種類の "baseline"** が存在する。混同に注意。

| 呼び名 | 実体 | 場所 |
|--------|------|------|
| **Kaggle NN baseline** | 模倣学習で作った NN エージェント | `submission/ptcg_baseline_model.pth` |
| **ローカルルールベース baseline** | 手書き戦略の強力なルールベース AI（約1400行） | `PTCGstadium/agents/baseline/main.py` |

**ptcg_best_model.pth の 53.8% 勝率は Kaggle NN baseline に対するもの。**  
ローカルルールベース baseline に対しては 21%（NN単体）、34%（ハイブリッド）しか勝てない。

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
├── submission/           # 現在の提出エージェント
│   ├── main.py           # ハイブリッドエージェント（MCTS + NN fallback）
│   ├── deck.csv          # ルカリオデッキ（60枚）
│   ├── ptcg_best_model.pth      # ★ 現在の最良モデル（53.8% vs Kaggle NN baseline）
│   ├── ptcg_rb_model.pth        # ルールベース対戦特化モデル（= ptcg_best_model.pth と同内容）
│   ├── ptcg_league_model.pth    # リーグ学習v1モデル（51.6% vs Kaggle NN baseline）
│   ├── ptcg_rl_model.pth        # PPO自己対戦モデル（参考用）
│   ├── ptcg_baseline_model.pth  # 模倣学習モデル（Kaggle NN baseline）
│   └── ptcg_normalization.npz   # 正規化パラメータ（mean/std）
├── training/             # 学習スクリプト群
│   ├── train_model.py           # 模倣学習（archive/ → baseline モデル）
│   ├── train_model_weighted.py  # 重み付き模倣学習（Kaggle向け）
│   ├── train_rl_local.py        # PPO自己対戦（ローカルCPU）
│   ├── train_rl_league.py       # リーグ学習 v1
│   ├── train_rl_best.py         # リーグ学習 v2（KLペナルティ・ベスト保存）★推奨
│   ├── train_vs_rulebased.py    # PPO vs ローカルルールベース（効果限定的、後述）
│   ├── train_imitation_rb.py    # ルールベース模倣学習（効果なし、後述）
│   └── eval_1000.py             # 1000戦評価スクリプト（vs Kaggle NN baseline）
├── logs/                 # 学習ログ
│   ├── train_rl_log.txt
│   ├── train_league_log.txt
│   ├── train_best_log.txt
│   ├── train_rb_log.txt         # vs ルールベース PPO ログ
│   ├── train_imitation_log.txt  # 模倣学習ログ
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
│       ├── baseline/main.py   # ★ ローカルルールベース baseline（約1400行、強力）
│       ├── rb/main.py         # ハイブリッドエージェント（NN MAIN + rb_helper 非MAIN）
│       ├── rl/main.py         # PPO自己対戦モデルエージェント
│       ├── league/main.py     # リーグモデルエージェント
│       └── best/main.py       # ptcg_rb_model.pth 優先ロードエージェント
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

### ゲームループ（`cg/game.py`）

```python
from cg.game import battle_start, battle_select, battle_finish
obs_dict, _ = battle_start(deck, deck)   # 両プレイヤーのデッキを渡してゲーム開始
obs_dict = battle_select([action_idx])    # アクションを選択して次の状態を取得
battle_finish()                           # ゲーム終了・リソース解放（必須）
```

- `cur.result`: ゲーム終了時の勝者インデックス（-1 = ゲーム中）
- `cur.yourIndex`: 現在の手番プレイヤーのインデックス（0 or 1）

### エージェントのインターフェース

```python
def agent(obs_dict: dict) -> list[int]:
    obs = to_observation_class(obs_dict)
    if obs.select is None:
        return read_deck_csv()  # 初期デッキ選択: 60枚のCard IDリスト
    return [chosen_index]       # 通常ターン: obs.select.option のインデックス
    # COUNT型等の複数選択は [idx1, idx2, ...] のリストを返す
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

## モデルアーキテクチャ（全モデル共通）

```
FC(5658 → 1024) + LayerNorm + ReLU
FC(1024 → 512)  + LayerNorm + ReLU
FC(512 → 256)   ← 出力: 256クラス（選択肢インデックス）
```
- 入力次元: 5658（MAX_CARD_ID=1267 基準）
- パラメータ数: 6,454,016
- Dropout(0.3) は模倣学習時のみ

### モデル一覧と実力

| ファイル | 学習手法 | Kaggle NN baseline 勝率 | ローカル RB 勝率 | 備考 |
|----------|---------|------------------------|----------------|------|
| `ptcg_best_model.pth` | リーグ学習v2 | **53.8%** (1000戦) | 21% (単体) / 34% (ハイブリッド) | ★ 提出用 |
| `ptcg_league_model.pth` | リーグ学習v1 | 51.6% | — | v2 の出発点 |
| `ptcg_baseline_model.pth` | 模倣学習（Kaggle） | 基準 | — | — |
| `ptcg_rl_model.pth` | PPO自己対戦 | ~48% | — | 参考用 |
| `ptcg_rb_model.pth` | RL vs RB (失敗) | — | 34% (ハイブリッド) | = ptcg_best_model.pth と同内容 |

---

## ハイブリッドエージェント（PTCGstadium/agents/rb/main.py）

**NN MAIN + ルールベース非MAIN** の組み合わせ。最もローカル RB に対して強い。

```
MAIN 選択     → NN (ptcg_rb_model.pth)
非MAIN 選択   → ローカルルールベース (baseline/main.py) の完全ロジック
```

- 勝率: **34%** vs ローカルルールベース（200戦確認）
- NN 単体 (21%) から +13% の改善
- 非MAIN をルールベースに委ねることで、カード選択・サポーター対象選択・ボス指定などを最適化

---

## ローカル強化学習パイプライン

### 前提条件
- Python 仮想環境: `C:\venv`（短パスで作成、Windows 260文字制限対策）
- PyTorch CPU only（AMD Radeon 860M は CUDA 非対応）

### 学習スクリプト（Kaggle NN baseline 強化用）

#### 1. リーグ学習 v2（★推奨）: `training/train_rl_best.py`
```powershell
C:\venv\Scripts\python training\train_rl_best.py --iters 650 --games 24
```
**特徴**：
- KLペナルティ（β=0.01）: Kaggle NN baseline から大きく逸脱しないよう正則化
- 50iter ごとに Kaggle NN baseline と20戦して実力評価・ベストチェックポイント自動保存
- コサイン LR 減衰（5e-5 → 1e-5）
- リーグ初期メンバー3錨（baseline / rl_v0 / league_v0）
- 出力: `submission/ptcg_best_model.pth`

**学習結果（2026-06-28, 約400iter / 9600ゲーム）**：
- ベストチェックポイント: iter 150 で **53.8%**（1000戦確認）
- iter 150 以降は評価が 25-50% で不安定（リーグ多様化の影響）

#### 2. リーグ学習 v1: `training/train_rl_league.py`
```powershell
C:\venv\Scripts\python training\train_rl_league.py --iters 300 --games 16
```
- 出力: `submission/ptcg_league_model.pth`（51.6% vs Kaggle NN baseline）

#### 3. PPO自己対戦: `training/train_rl_local.py`
```powershell
C:\venv\Scripts\python training\train_rl_local.py --iters 200 --games 20
```
- 出力: `submission/ptcg_rl_model.pth`
- 注意: 自己対戦はナッシュ均衡に収束するため baseline より弱くなりやすい

### 学習スクリプト（ローカルルールベース強化用 ※現状効果限定）

#### 4. PPO vs ルールベース: `training/train_vs_rulebased.py`
```powershell
C:\venv\Scripts\python training\train_vs_rulebased.py --iters 40 --games 100 --lr 3e-5 --kl-beta 0.0 --eval-every 10 --eval-games 50
```
- 出力: `submission/ptcg_rb_model.pth`
- **結果**: 効果なし。eval が 28-36% で振れ動き、改善しない（後述の失敗分析参照）

#### 5. ルールベース模倣学習: `training/train_imitation_rb.py`
```powershell
C:\venv\Scripts\python training\train_imitation_rb.py --games 800 --epochs 30
```
- 出力: `submission/ptcg_rb_model.pth`（初期値を超えた場合のみ保存）
- **結果**: 効果なし。81% 模倣精度でも eval 16%（後述の失敗分析参照）

---

## 評価スクリプト

### Kaggle NN baseline 対の評価: `training/eval_1000.py`
```powershell
C:\venv\Scripts\python training\eval_1000.py --games 1000
```
- `ptcg_best_model.pth` vs `ptcg_baseline_model.pth`
- 100戦ごとに中間報告

### ローカル対戦アリーナ: `PTCGstadium/arena.py`
```powershell
$env:PYTHONIOENCODING='utf-8'
C:\venv\Scripts\python PTCGstadium\arena.py --p0 agents/rb --p1 agents/baseline --games 200
```
- `--p0 / --p1` でエージェントを指定（`agents/` 以下のディレクトリ名）
- `best/`, `rb/`, `league/`, `baseline/`, `rl/` が利用可能

---

## Kaggle 自動学習パイプライン（模倣学習）

```powershell
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

## ローカルルールベース baseline 攻略の調査記録（2026-06-28）

### ルールベース baseline の実力

`PTCGstadium/agents/baseline/main.py` は約1400行の手書き戦略 AI。
- グローバル状態: `_last_seen_turn`, `_non_boss_supporter_played`, `_luna_cycle_used`
- 複数インスタンスが必要な場合は `importlib.util.module_from_spec` で別々にロードする
- ゲーム間でリセットが必要: `mod._last_seen_turn = -1` 等を明示的にクリア

### 試みた手法と結果

**1. NN MAIN + ルールベース非MAIN ハイブリッド**
- NN が MAIN 選択、ルールベースが CARD/YES_NO/COUNT 等の非MAIN 選択を担当
- 結果: **34%** (200戦)。NN 単体の 21% から +13%
- 非MAINの判断（どのカードをサーチするか、Boss'sOrdersの対象等）はルールベースが最適

**2. PPO RL vs ルールベース（terminal reward のみ）**
- Round 1: 120iter × 20games, lr=1e-4, kl_beta=0.005 → eval 28-36%（最高 60% はノイズ）
- Round 2: 40iter × 100games, lr=3e-5, kl_beta=0.0 → eval 28-36%、改善なし
- **失敗原因**: terminal reward だけでは MAIN 決定への学習信号が弱すぎる。
  ゲームあたり ~42 MAIN 決定があり、勝利は最後の 1 ステップにしか reward が来ない。
  100 games/iter でも std ±4.7% で gradient が信頼できない。

**3. ルールベース模倣学習（rb vs rb の勝者の MAIN 決定を教師学習）**
- 800 ゲーム収集（33726 サンプル）、30 エポック、CE 損失
- 訓練精度 81% に達したが eval は **16%**（50戦）で初期値 28% 以下
- モデル保存せず
- **失敗原因**: ルールベース同士の対戦では「勝者の MAIN 決定 ＝ 敗者の MAIN 決定」
  （決定論的 AI のため同じ状態には同じ行動）。ランダムな結果（ドロー運）で勝者が決まる。
  模倣は「rb の平均行動」を学ぶのみで rb の弱点を突く戦略を失う。
  さらに NN が人間ゲームデータから学んだ「rb への exploit」も上書きしてしまった。

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

### 5. arena.py のコマンド引数形式
**症状**: `python arena.py agents/best agents/baseline` だと引数エラー  
**対処**: `--p0 agents/best --p1 agents/baseline` と明示的なフラグを使う

### 6. arena.py の UnicodeEncodeError（cp932）
**症状**: 日本語含む print 文がエラー  
**対処**: `$env:PYTHONIOENCODING='utf-8'` を設定してから実行

### 7. battle_select に複数選択が必要なケース
**症状**: `battle_select([action[0]])` だと COUNT 型選択で IndexError  
**原因**: COUNT 型（手札複数捨て等）はリスト `[i1, i2, ...]` を渡す必要がある  
**対処**: `battle_select(agent.agent(obs_dict))` と agent の返値をそのまま渡す

### 8. ルールベースモジュールの複数インスタンス
**症状**: 2プレイヤー分のルールベース AI が状態を共有してしまう  
**原因**: グローバル変数 `_last_seen_turn` 等が共有モジュール内に存在する  
**対処**: `importlib.util.module_from_spec` で別名でロードし独立したインスタンスを作る

### 9. PPO自己対戦でのモデル退行
**症状**: 自己対戦で学習したモデルが baseline より弱くなる  
**原因**: 自己対戦はナッシュ均衡（じゃんけん）に収束するため、絶対的な強さにならない  
**対処**: リーグ学習（多様な固定対戦相手）を使う

---

## 次にすべき改善

### Kaggle 本番スコア向上（優先度高）

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

### ローカルルールベース攻略（難度高・詳細は次章参照）

5. **中間報酬付き PPO**（最も有望）
   - KO イベント検出で +0.2 / 自分の KO で -0.1 の中間報酬
   - terminal reward のみでは勾配が弱すぎる問題を解決

6. **MCTS（サーチ API 活用）**
   - 探索深さ 3-5 手でもルールベースとほぼ互角になる可能性あり

---

## ローカルルールベースに勝つための具体的戦略（詳細）

### なぜ現在の RL が機能しないか

ルールベース baseline は **約1400行の手書き最適戦略**。強みの根拠：

| ルールベースの強み | NN の弱み |
|------------------|-----------|
| Boss's Orders でベンチの瀕死ポケモンを正確に狙う | どのベンチを狙うかを HP から計算できない |
| ルナトーンのルナサイクルを最適タイミングで使う | 特性の使用タイミングが学習できていない |
| エネルギー付与の優先順位（主力 → サブ）が完璧 | どのポケモンに付けるかが曖昧 |
| ゲームの流れに応じた序盤展開の最適化 | 状態ベクトルに「盤面の優劣」が十分表現されていない |

### 戦略①：中間報酬付き PPO（推奨・実装コスト中）

**原理**: 勝ち負けだけでなく「KO した」「KO された」にも報酬を与え、学習信号を密にする。

```python
# ゲームループ内でログを監視
prev_opp_active_hp = 999
for step in range(4000):
    obs = to_observation_class(obs_dict)
    # ...
    # NN の MAIN 行動後、相手アクティブの HP 変化をチェック
    if cur.result == main_idx:  # 勝利
        step_reward = 1.0
    elif cur.result == 1 - main_idx:  # 敗北
        step_reward = -1.0
    else:
        step_reward = 0.0
        # 相手がベンチに逃げた = KO の代替シグナル
        opp = s.players[1 - main_idx]
        if opp.active and opp.active[0].hp < prev_opp_active_hp * 0.5:
            step_reward += 0.05  # 大ダメージを与えた
        prev_opp_active_hp = opp.active[0].hp if opp.active else 999
```

**パラメータ推奨値**:
- `--games 200` (iter あたり。std ±3.5% で勾配が信頼できる)
- `--iters 200`（合計 40000 ゲーム、約3時間）
- `--kl-beta 0.0`（模倣 NN との乖離ペナルティなし）
- `--lr 5e-5 --lr-min 1e-5`
- 初期モデル: `ptcg_best_model.pth`（ハイブリッドの 34% を出発点に）

### 戦略②：MCTS（推奨・実装コスト高・効果大）

`search_begin` / `search_step` API を使った **純粋 MCTS（NN不要）**。

```python
from cg.api import search_begin, search_step, search_end

def mcts_select(obs_dict, deck, n_rollouts=50, depth=5):
    """MAIN 選択肢ごとに n_rollouts 回のランダムロールアウトで勝率を推定"""
    obs = to_observation_class(obs_dict)
    options = obs.select.option
    scores = []
    
    for i, opt in enumerate(options):
        wins = 0
        for _ in range(n_rollouts):
            sid = search_begin(obs_dict, deck, deck)
            search_step(sid, i)  # この選択肢を試す
            # depth 手先までランダムにロールアウト
            for d in range(depth):
                r = random_rollout_step(sid)
                if r is not None:  # ゲーム終了
                    if r == obs.current.yourIndex:
                        wins += 1
                    break
            search_end(sid)
        scores.append(wins / n_rollouts)
    
    return scores.index(max(scores))
```

**期待効果**: 50 ロールアウト × depth 5 で 20-30% の勝率向上が見込める。

### 戦略③：状態表現の改善

現在の 5658 次元特徴量に不足している情報：

```python
# 追加候補の特徴量
# 1. 相手アクティブポケモンの残 HP / 最大 HP 比率（KO の近さ）
opp_active = s.players[1-mi].active[0] if s.players[1-mi].active else None
hp_ratio = opp_active.hp / _card_dict[opp_active.id]['HP'] if opp_active else 0.0

# 2. 自分と相手のプライズ差（ゲームの優劣）
my_prizes = sum(1 for p in s.players[mi].prize if p is not None)
opp_prizes = sum(1 for p in s.players[1-mi].prize if p is not None)
prize_diff = my_prizes - opp_prizes  # 正 = 有利

# 3. 手札の行動可能カードフラグ
has_supporter = any(_is_supporter(c.id) for c in s.players[mi].hand)
has_energy = any(_is_energy(c.id) for c in s.players[mi].hand)

# 4. MAIN 選択肢の種類（何が選べるかの summary）
option_types = [0] * 8  # ATTACK, PLAY, EVOLVE, ATTACH, RETREAT, END, ABILITY など
for opt in obs.select.option:
    option_types[opt.type % 8] = 1
```

### 戦略④：非MAIN もNN化（全SelectType対応）

現在は MAIN のみ NN が担当。CARD / YES_NO / COUNT 選択も NN で学習する。

- **CARD 選択**: どのカードをサーチするか（Nest Ball でどのポケモンを出すか）
- **YES_NO**: 使うか使わないか（Irida の発動判断等）
- **COUNT 選択**: 何枚捨てるか / どのカードを捨てるか

各 SelectType ごとに別の小型 NN ヘッドを追加する（マルチヘッドアーキテクチャ）。

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
