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
│   ├── main.py
│   ├── deck.csv
│   └── cg/
├── submission/           # 現在の提出エージェント（NN + ルールベースハイブリッド）
│   ├── main.py           # ハイブリッドエージェント
│   ├── deck.csv          # ルカリオデッキ
│   ├── ptcg_baseline_model.pth   # 学習済みモデル（約24MB）
│   ├── ptcg_normalization.npz    # 正規化パラメータ（mean/std）
│   └── cg/               # ゲームエンジンライブラリ
├── kaggle_training/      # Kaggle自動学習パイプライン
│   ├── kaggle_run.py              # 自動学習スクリプト（push→監視→ダウンロード）
│   ├── kernel-metadata.json       # Kaggle kernelの設定（GPU無効・CPU実行）
│   ├── ptcg_weighted_train.ipynb  # 重み付き模倣学習ノートブック
│   ├── leaderboard.csv            # リーダーボードCSV（任意・重み付き学習用）
│   └── output/                    # ダウンロードされた出力ファイル置き場
├── train_model.py        # 模倣学習スクリプト（ローカル実行用、archive/→モデル生成）
├── train_model_weighted.py  # 重み付き模倣学習スクリプト（ローカル実行用）
├── submission.tar.gz     # Kaggle提出用tarball
├── ルカリオデッキの回し方.txt
└── Competition Rules.txt
```

---

## ゲームエンジン（cg ライブラリ）

`submission/cg/` にプリコンパイル済みバイナリが含まれる：
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
        # 初期デッキ選択: 60枚のCard IDリストを返す
        return read_deck_csv()
    # 通常ターン: obs.select.option のインデックスリストを返す
    return [chosen_index]
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

## 対戦データ

### ローカル archive/
- 約5,063件のJSONファイル
- 各ファイルに1対戦分のステップごとの observation・action・reward が格納
- 報酬: 勝利=1, 敗北=-1, 引き分け=0

### Kaggle エピソードデータセット（日次更新）
- `kaggle/pokemon-tcg-ai-battle-episodes-YYYY-MM-DD` の形式で毎日公開
- 1データセットあたり約5,919件のJSONファイル（約750MB）
- Kaggle kernel 内では `/kaggle/input/datasets/organizations/kaggle/<dataset-name>/` にマウントされる
- `kaggle_run.py` が最新データセットを自動検出して使用する

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

---

## Kaggle 自動学習パイプライン

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
- `enable_gpu: false` — KaggleのCPUで実行（GPU非互換問題を回避、後述）
- `competition_sources: ["pokemon-tcg-ai-battle"]` — EN_Card_Data.csv の取得元
- `dataset_sources: [最新エピソードデータセット]` — 毎回自動更新

### Kaggle 内でのパス構造
```
/kaggle/input/
├── competitions/
│   └── pokemon-tcg-ai-battle/
│       ├── EN_Card_Data.csv      ← CSV_PATH
│       └── ...
└── datasets/
    └── organizations/
        └── kaggle/
            └── pokemon-tcg-ai-battle-episodes-YYYY-MM-DD/
                └── *.json        ← JSON_DIRECTORY
```

---

## 現状の提出モデル

### アーキテクチャ（`ptcg_weighted_train.ipynb` Step 4）
```
FC(5658 → 1024) + LayerNorm + ReLU + Dropout(0.3)
FC(1024 → 512)  + LayerNorm + ReLU + Dropout(0.3)
FC(512 → 256)
```
- 入力次元: 5658（MAX_CARD_ID=1267 基準）
- 出力: 256クラス（選択肢インデックス）
- パラメータ数: 6,454,016

### 最新学習結果（2026-06-28 v7カーネル）
- データ: `episodes-2026-06-27` から1,500ファイル（88,260サンプル）
- ベストエポック: **Epoch 2**（val_loss=1.3931, val_acc=**51.6%**）
- Epoch 15: train_acc=64.2%, val_acc=49.3%（オーバーフィット）
- リーダーボードなし → 全勝者を均等学習

### 現状の問題点

| 問題 | 詳細 |
|------|------|
| 早期オーバーフィット | Epoch 2以降 val_acc が下がる一方。リーダーボード重み付きで改善可能 |
| 模倣学習の限界 | 複数の正解があるため val_acc が ~51% で頭打ち |
| MAINのみNN | YES/NO・カード選択・リトリート先はルールベース任せ |
| CPUのみ | KaggleのGPUはPyTorchと非互換のため CPU学習（10分で完了） |

---

## 既知の技術的問題と対処法

### 1. Kaggle GPU と PyTorch の CUDA 非互換
**症状**: `AcceleratorError: CUDA error: no kernel image is available for execution on the device`  
**原因**: Kaggle が割り当てる GPU（Blackwell 系等）が、インストール済み PyTorch の CUDA カーネルに未対応  
**対処**: `kernel-metadata.json` で `enable_gpu: false` にして CPU 実行。学習時間は約10分で実用的。

### 2. label_smoothing + masked_fill(-1e9) による loss 異常値
**症状**: CrossEntropyLoss が 9700万などの異常値になる  
**原因**: `label_smoothing=0.1` が無効化されたマスク位置（-1e9 logit）にも勾配を分配するため、マスク位置200個 × 390,625 ≈ 7800万の誤差が積み上がる  
**対処**: `nn.CrossEntropyLoss()` で `label_smoothing` を使わない

### 3. Windows の Python 3.13 で torch DLL エラー
**症状**: `ImportError: DLL load failed while importing _C`  
**原因**: ローカル環境の AMD GPU（Radeon 860M）は CUDA 非対応（ROCm は Linux のみ）。torch の DLL 依存関係が壊れている  
**対処**: ローカルでは torch を使わず、学習は Kaggle に委ねる

---

## 次にすべき改善

優先度順：

1. **リーダーボード重み付き学習**（すぐ試せる）
   - `kaggle_training/leaderboard.csv` を Kaggle dataset としてアップロード
   - `kernel-metadata.json` の `dataset_sources` に追加
   - 高スコアプレイヤーの行動を優先的に学習 → オーバーフィット改善が期待できる

2. **MCTSとの組み合わせ**（最効果大）
   - `search_begin` / `search_step` / `search_end` APIを使ったモンテカルロ木探索
   - 現在のNNをMCTSのrollout評価関数として使う
   - 時間制限（例: 1秒/ターン）を設けて探索

3. **データ品質フィルタ**
   - 長いゲーム（例: 30ターン以上）の勝者のみ学習（実力勝ちの可能性が高い）

4. **全SelectTypeをNN化**
   - MAIN以外（カード選択、YES/NO判断など）もNNで学習

5. **強化学習でfine-tune**
   - 模倣学習後にself-playで強化学習

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
- GPU: AMD Radeon 860M（CUDA非対応 → ローカルでの torch 学習不可）
- 学習: Kaggle CPU kernel（`python kaggle_training/kaggle_run.py` で全自動）
- Kaggle認証: `~/.kaggle/kaggle.json`（username: aoao0314）
