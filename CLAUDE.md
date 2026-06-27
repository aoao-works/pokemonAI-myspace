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
│   ├── EN_Card_Data.csv  # カードデータ英語版（2,102カード）
│   ├── JP_Card_Data.csv  # カードデータ日本語版
│   ├── Card_ID List_EN.pdf
│   └── Card_ID List_JP.pdf
├── sample_submission/    # サンプルエージェント（ランダム選択）
│   ├── main.py           # エージェントエントリーポイント
│   ├── deck.csv          # 60枚のデッキ（Card IDのリスト）
│   └── cg/               # ゲームエンジンライブラリ
├── submission/           # 現在の提出エージェント（ルールベース）
│   ├── main.py           # 改良版エージェント
│   ├── deck.csv          # ルカリオデッキ
│   └── cg/               # ゲームエンジンライブラリ
├── ポケモン強化学習.ipynb    # 学習用ノートブック
├── ルカリオデッキの回し方.txt  # デッキ戦略ドキュメント
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
    # 返すリストの長さ: minCount <= len <= maxCount
    return [chosen_index]
```

### Observationの構造

```
Observation
├── select: SelectData | None    # 選択肢情報（デッキ選択時はNone）
│   ├── type: SelectType         # MAIN, CARD, ATTACK, YES_NO, COUNT, ...
│   ├── context: SelectContext   # 何を選択するか
│   ├── minCount / maxCount      # 選択数の制約
│   └── option: list[Option]     # 選択肢リスト
├── logs: list[Log]              # 前回選択からのイベント履歴
└── current: State | None        # 現在の盤面状態
    ├── turn, yourIndex, firstPlayer
    ├── supporterPlayed, energyAttached, retreated
    └── players: list[PlayerState]  # 自分と相手の状態
        ├── active, bench, hand, deckCount
        ├── discard, prize
        └── poisoned, burned, asleep, paralyzed, confused
```

---

## 対戦データ（archive/）

- 約5,063件のJSONファイル（例: `81220630.json`）
- 各ファイルに1対戦分のステップごとのobservation・action・rewardが格納
- 報酬: 勝利=1, 敗北=-1, 引き分け=0
- 学習データとして行動模倣学習（Imitation Learning）に活用可能

---

## 現在のデッキ（ルカリオデッキ）

`submission/deck.csv` に記録。主要ポケモン：
- **メガルカリオex** - メインアタッカー（はどうづき / メガブレイブ）
- **リオル** - メガルカリオexの進化前
- **ハリテヤマ** - サブアタッカー（ワイルドプレス）
- **マクノシタ** - ハリテヤマの進化前
- **ソルロック** - コスモビームで低HP処理
- **ルナトーン** - ルナサイクル特性でエネルギー加速

---

## 戦略メモ（`ルカリオデッキの回し方.txt` 参照）

- **メインアタッカー**: メガルカリオexのはどうづき（HP160以下）/ メガブレイブ（HP140以上）
- **エネルギー管理**: ルナサイクル（ルナトーン特性）でトラッシュからエネルギー回収
- **ベンチ構成目標**: リオル×2 + ソルロック + ルナトーン + マクノシタ
- **ボスの指令**: 相手のexポケモンを優先して呼び出して倒す

---

## 学習アプローチ（Colabで実施予定）

### 方針
1. **Imitation Learning**: `archive/` の対戦データから上位プレイヤーの行動を学習
2. **強化学習**: ゲームエンジンのシミュレーターを使ってself-play
3. **MCTS**: `search_begin` / `search_step` APIを使ったモンテカルロ木探索

### データの使い方
- archiveから上位エージェント（reward=1）の行動を抽出
- 盤面状態（Observation）→ 行動（action）の教師あり学習
- その後強化学習でfine-tune

---

## 提出要件

- `main.py` の `agent(obs_dict)` 関数が必須エントリーポイント
- デッキは `deck.csv`（60行、各行はCard ID）
- 1デッキ: 同一カードは最大4枚（ACE SPECは1枚）
- 提出時は `/kaggle_simulations/agent/` にファイルが配置される
- **ネットワーク不可**: 実行中の外部通信禁止

---

## 開発環境

- Python 3.13
- ゲームエンジン: `cg.dll`（Windows）/ `libcg.so`（Linux）
- Colabでの学習 → Kaggleへの提出
