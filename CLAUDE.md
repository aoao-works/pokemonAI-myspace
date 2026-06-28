# Pokemon TCG AI Battle Challenge

**目標**: Kaggle コンペでポケモン TCG の AI エージェントを構築し、銅メダル獲得を目指す。  
エージェント同士がリミテッドカードバトルで対戦し、勝率でリーダーボード順位が決まる。

---

## ⚠️ 重要：「baseline」の二重定義

このプロジェクトには **2種類の "baseline"** が存在する。混同に注意。

| 呼び名 | 実体 | 場所 |
|---|---|---|
| **Kaggle NN baseline** | 模倣学習で作った NN エージェント | `submission/ptcg_baseline_model.pth` |
| **ローカルルールベース baseline** | 手書き戦略の強力なルールベース AI（約1400行） | `PTCGstadium/agents/baseline/main.py` |

**ptcg_best_model.pth の 53.8% 勝率は Kaggle NN baseline に対するもの。**  
ローカルルールベース baseline に対しては 21%（NN単体）、34%（ハイブリッド）しか勝てない。

---

## ディレクトリ構成

```
pokemonAI-myspace/
├── archive/              # 対戦リプレイデータ（JSON、約5,063件）
├── data/                 # カードデータCSV（MAX_CARD_ID=1267）
├── submission/           # ★ 現在の提出エージェント
│   ├── main.py           # ハイブリッドエージェント（MCTS + NN fallback）
│   ├── deck.csv          # ルカリオデッキ（60枚）
│   └── ptcg_best_model.pth  # ★ 現在の最良モデル
├── training/             # 学習スクリプト群
├── logs/                 # 学習ログ
├── kaggle_training/      # Kaggle自動学習パイプライン
│   └── kaggle_run.py     # push→監視→ダウンロードの全自動スクリプト
├── PTCGstadium/          # ローカル対戦・評価環境
│   ├── arena.py          # エージェント間対戦
│   └── agents/
│       ├── baseline/main.py  # ★ ローカルルールベース baseline（強力）
│       ├── rb/main.py        # ハイブリッド（NN MAIN + RB 非MAIN）
│       ├── best/main.py      # ptcg_rb_model.pth 優先ロード
│       ├── league/main.py    # リーグモデル
│       └── rl/main.py        # PPO自己対戦モデル
└── デッキ集/             # ドラパルト・イワパレス等の代替デッキ
```

---

## モデル一覧と実力

| ファイル | 学習手法 | Kaggle NN baseline 勝率 | ローカル RB 勝率 |
|---|---|---|---|
| `ptcg_best_model.pth` | リーグ学習v2 | **53.8%** (1000戦) | 21% 単体 / 34% ハイブリッド |
| `ptcg_league_model.pth` | リーグ学習v1 | 51.6% | — |
| `ptcg_baseline_model.pth` | 模倣学習（Kaggle） | 基準 | — |
| `ptcg_rl_model.pth` | PPO自己対戦 | ~48% | — |
| `ptcg_rb_model.pth` | RL vs RB（失敗） | — | 34% ハイブリッド |

`ptcg_rb_model.pth` = `ptcg_best_model.pth` と同内容。

---

## ハイブリッドエージェント

**NN MAIN + ルールベース非MAIN** の組み合わせ（`PTCGstadium/agents/rb/main.py`）。  
MAIN選択→NN、CARD/YES_NO/COUNT等の非MAIN→ルールベースで処理。ローカルRBに対して最強（34%）。

---

## 開発環境

- Python 3.13 / Windows 11
- 仮想環境: `C:\venv`（短パス必須、Windows 260文字制限対策）
- GPU: AMD Radeon 860M（CUDA非対応 → CPU only PyTorch）
- Kaggle認証: `~/.kaggle/kaggle.json`（username: aoao0314）

コマンド例・技術的な問題・失敗した試み・次の改善策はメモリシステムを参照。

---

## 提出要件

- `main.py` の `agent(obs_dict)` 関数が必須エントリーポイント
- デッキは `deck.csv`（60行、同一カード最大4枚、ACE SPECは1枚）
- 提出時は `/kaggle_simulations/agent/` に配置される
- **ネットワーク不可**: 実行中の外部通信禁止
