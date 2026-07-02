# 学習試行履歴と失敗記録

ポケモン TCG AI でこれまで試みた機械学習手法の全記録。

---

## フォルダ構成

```
training/
├── 01_imitation/           # 模倣学習（初期）
│   ├── train_model.py
│   └── train_model_weighted.py
├── 02_ppo_selfplay/        # PPO 自己対戦
│   └── train_rl_local.py
├── 03_league_v1/           # リーグ学習 v1
│   └── train_rl_league.py
├── 04_league_v2_best/      # ★ リーグ学習 v2（現行最良）
│   └── train_rl_best.py
├── 05_vs_rulebased_failed/ # ルールベース攻略実験（失敗）
│   ├── train_vs_rulebased.py
│   └── train_imitation_rb.py
└── eval_1000.py            # 評価スクリプト（Kaggle NN baseline と 1000 戦）
```

---

## モデル実力一覧

| モデルファイル | 学習手法 | Kaggle NN baseline 勝率 | ローカル RB 勝率 |
|---|---|---|---|
| `ptcg_best_model.pth` | リーグ学習 v2 | **53.8%** (1000戦) | 21%（NN単体） |
| `ptcg_league_model.pth` | リーグ学習 v1 | 51.6% (1000戦) | — |
| `ptcg_baseline_model.pth` | 模倣学習（Kaggle） | 基準 (≒50%) | — |
| `ptcg_rl_model.pth` | PPO 自己対戦 | ~48% | — |
| `ptcg_rb_model.pth` | PPO vs ルールベース | — | **31%**（ハイブリッド） |

---

## 試行 ① 初期模倣学習（Imitation Learning）
`01_imitation/train_model.py`

### 概要
- 対戦リプレイデータ（`archive/`、約 5,063 件）から NN に教師学習
- 基本的な MAIN 選択（どのカードを使うか）を人間の行動から学ぶ

### 結果
- `ptcg_baseline_model.pth` として保存
- Kaggle NN baseline 勝率: 約 50%（基準）

### 問題点
- 勝者だけでなく敗者の行動も混在 → ノイズが大きい
- デッキ運（ドロー運）でゲームが左右されるため教師データの質が低い

---

## 試行 ② 重み付き模倣学習（Weighted Imitation Learning）
`01_imitation/train_model_weighted.py`

### 概要
- リーダーボードスコアを重みとして WeightedRandomSampler を使用
- 高スコアプレイヤーの行動を優先して学習

### 結果
- 改善効果は限定的（Kaggle 側での学習で実施、スコア詳細不明）

### 問題点
- リーダーボードスコアが高いプレイヤー = 強い手 とは限らない
- 対戦相手のレベルも異なるため重みの信頼性が低い

---

## 試行 ③ PPO 自己対戦（Self-Play RL）
`02_ppo_selfplay/train_rl_local.py`

### 概要
- NN エージェント同士を対戦させ、PPO で強化学習

### 結果
- `ptcg_rl_model.pth` として保存
- Kaggle NN baseline 勝率: **~48%**（模倣学習より**悪化**）

### 失敗原因
- 自己対戦はナッシュ均衡に収束しやすく、初期の模倣学習知識が失われる
- 学習信号が弱い（ゲームあたり ~42 MAIN 決定に対し terminal reward のみ）

---

## 試行 ④ リーグ学習 v1（League Training v1）
`03_league_v1/train_rl_league.py`

### 概要
- 過去の自分・旧モデル・ベースラインなど複数の固定エージェントの「リーグ」を構成
- メインエージェントはランダムに選ばれたリーグメンバーと対戦
- PPO で更新するのはメインのみ、リーグメンバーは凍結

### 結果
- `ptcg_league_model.pth` として保存（300 iter × 16 games）
- Kaggle NN baseline 勝率: **51.6%** (1000 戦)

### 評価
- 自己対戦より明確に改善したが「じゃんけん的な相性問題」は残る

---

## 試行 ⑤ リーグ学習 v2 / KL ペナルティ付き ★現行最良
`04_league_v2_best/train_rl_best.py`

### 概要
- リーグ学習 v1 の改善版
- **KL ペナルティ**: baseline モデルから逸脱しないよう正則化（β=0.01）
- **定期評価**: 50 iter ごとに baseline と 20 戦して実力を数値化
- **ベストモデル自動保存**: 評価 win rate が過去最高なら即保存
- **コサイン LR スケジュール**: 後半は低 LR で安定収束
- 3 つの錨モデル（baseline / rl_v0 / league）をリーグに追加

### 実行コマンド
```powershell
C:\venv\Scripts\python training\04_league_v2_best\train_rl_best.py --iters 650 --games 24
```

### 結果
- `ptcg_best_model.pth` として保存（650 iter × 24 games）
- Kaggle NN baseline 勝率: **53.8%** (1000 戦) ← iter 150 付近がピーク
- ローカル RB 勝率: **21%**（NN 単体）
- Kaggle スコア: **558.4**（歴代最高、2026-06-18）

### 注意
- iter 150 以降は不安定
- **`ptcg_best_model.pth` は絶対にこのスクリプトで上書きしない**（`--out-path` で別名指定する）

---

## 試行 ⑥ PPO vs ルールベース（失敗）
`05_vs_rulebased_failed/train_vs_rulebased.py`

### 概要
- ローカル RB baseline（約 1,400 行の手書き AI）を倒すために設計
- 初期モデル = `ptcg_best_model.pth`（21% vs RB → 向上目指す）

### 試行パターン

**Round 1**: 120 iter × 20 games、lr=1e-4、kl_beta=0.005  
→ eval 28〜36%（訓練 eval 最高 60% はノイズ）

**Round 2**: 40 iter × 100 games、lr=3e-5、kl_beta=0.0  
→ eval 28〜36%、改善なし

**opp_noise=0.5 カリキュラム（2026-06-29）**:
- Phase 1: opp_noise=0.5（相手 50% ランダム）× 60 iter × 30〜50 games、prize 中間報酬あり
- Phase 2: opp_noise=0.0（フル RB）× 80 iter で追加学習
- → アリーナ 200 戦で **31%** に収束（訓練 eval は 42〜46% と高く出るがノイズ σ≈7%）

### 失敗原因
- Terminal reward のみでは MAIN 決定への学習信号が弱すぎる
- opp_noise=0.5 で学んだ「ランダム相手への勝ち方」がフル RB に転移しない
- **アリーナ 200 戦で 31% が統計的上限の模様**

### 教訓
- 訓練 eval（50 ゲーム、σ≈7%）は信用しない。アリーナ 200 戦で必ず確認
- Phase 2（フル RB での追加学習）は逆効果

---

## 試行 ⑦ ルールベース模倣学習（失敗）
`05_vs_rulebased_failed/train_imitation_rb.py`

### 概要
- RB 同士の対戦から勝者の MAIN 決定を収集し、NN に教師学習

### 結果
- 800 ゲーム収集（33,726 サンプル）、30 エポック、CE 損失
- 訓練精度 81% → eval **16%**（50 戦）
- 初期値 28% **以下に悪化**。モデル保存せず

### 失敗原因
- RB 同士の対戦では「勝者の MAIN 決定 ＝ 敗者の MAIN 決定」（決定論的 AI のため同じ状態には同じ行動）
- ランダムな結果（ドロー運）で勝者が決まるため、模倣は「RB の平均行動」を学ぶだけ
- NN が人間ゲームデータから学んだ「RB へのexploit」も上書きしてしまった

---

## 試行 ⑧ MCTS（ランダムロールアウト）の Kaggle 提出（失敗）

### 概要
- `submission/main.py` に UCB1 フラットバンディット MCTS（0.3 秒/手）を追加

### 結果
- Kaggle スコア: 536.5 → **502.3 に低下**

### 失敗原因
- ランダムロールアウトは対戦相手（NN）の戦略を反映できない
- NN の直接推論の方が優秀
- → **MCTS は無効化済み**（`submission/main.py` 修正完了）
