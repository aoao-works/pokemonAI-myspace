"""
重み付き模倣学習スクリプト
- リーダーボードスコアを重みとして WeightedRandomSampler を使用
- 高スコアプレイヤーの行動を優先的に学習
"""
import json
import re
import os
import glob
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader, WeightedRandomSampler
from tqdm.auto import tqdm
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import shutil

# ============================================================
# 設定パラメータ
# ============================================================
JSON_DIRECTORY  = 'archive'
LEADERBOARD_CSV = 'pokemon-tcg-ai-battle-publicleaderboard-2026-06-28T01_49_15.csv'
MAX_ACTIONS     = 256
MAX_FILES       = None   # None=全ファイル / 整数=テスト用に制限
BATCH_SIZE      = 256
EPOCHS          = 15
LEARNING_RATE   = 1e-3
MODEL_PATH      = 'submission/ptcg_baseline_model.pth'
NORM_PATH       = 'submission/ptcg_normalization.npz'
PLOT_PATH       = 'training_curve.png'

# ============================================================
# カードデータ読み込み
# ============================================================
csv_file_path = 'data/EN_Card_Data.csv'
df_cards = pd.read_csv(csv_file_path)

df_cards['HP']       = df_cards['HP'].fillna(0).astype(float)
df_cards['Retreat']  = df_cards['Retreat'].fillna(0).astype(float)
df_cards['Type']     = df_cards['Type'].fillna("None")
df_cards['Weakness'] = df_cards['Weakness'].fillna("None")
df_cards['Damage']   = df_cards['Damage'].fillna("0")
df_cards['Cost']     = df_cards['Cost'].fillna("")
df_cards['Rule']     = df_cards['Rule'].fillna("")

df_cards_unique = df_cards.drop_duplicates(subset=['Card ID'], keep='first')
card_dict = df_cards_unique.set_index('Card ID').to_dict(orient='index')
MAX_CARD_ID = int(df_cards['Card ID'].max())

print(f"MAX_CARD_ID: {MAX_CARD_ID}")

TYPE_VOCAB = ['{G}', '{R}', '{W}', '{L}', '{P}', '{F}', '{D}', '{M}', '{C}', '竜',
              '{A}', '{A}{A}', '{Team Rocket}{Team Rocket}', '{C}{C}{C}']
WEAKNESS_VOCAB = ['{G}', '{R}', '{W}', '{L}', '{P}', '{F}', '{D}', '{M}', '{C}', '竜']

def one_hot_encode(val, vocab):
    vector = [0] * len(vocab)
    if val in vocab:
        vector[vocab.index(val)] = 1
    return vector

def parse_damage(damage_str):
    nums = re.findall(r'\d+', str(damage_str))
    return int(nums[0]) if nums else 0

def parse_cost(cost_str):
    cost_str = str(cost_str)
    return cost_str.count('{') + cost_str.count('●')

def encode_card_list(card_list, max_id):
    vector = [0] * (max_id + 1)
    if not card_list:
        return vector
    for card in card_list:
        card_id = card.get('id', 0)
        if 0 <= card_id <= max_id:
            vector[card_id] += 1
    return vector

def count_attached_energy_types(energy_cards, card_dict):
    counts = [0] * len(TYPE_VOCAB)
    for ec in energy_cards:
        eid = ec.get('id', 0)
        etype = card_dict.get(eid, {}).get('Type', 'None')
        if etype in TYPE_VOCAB:
            counts[TYPE_VOCAB.index(etype)] += 1
    return counts

# ============================================================
# 特徴量抽出
# ============================================================
def extract_detailed_pokemon_features(poke_data, card_dict):
    empty_features = [0] * (7 + 2 + len(TYPE_VOCAB) + len(WEAKNESS_VOCAB) + len(TYPE_VOCAB))
    if not poke_data:
        return empty_features

    card_id      = poke_data.get('id', 0)
    current_hp   = poke_data.get('hp', 0)
    energy_count = len(poke_data.get('energies', []))

    tools   = poke_data.get('tools', [])
    tool_id = tools[0].get('id', 0) if tools else 0

    card_info     = card_dict.get(card_id, {})
    max_hp        = card_info.get('HP', 0)
    retreat_cost  = card_info.get('Retreat', 0)
    attack_damage = parse_damage(card_info.get('Damage', "0"))
    attack_cost   = parse_cost(card_info.get('Cost', ""))
    is_ex         = 1 if "ex" in str(card_info.get('Rule', "")).lower() else 0

    type_vec     = one_hot_encode(card_info.get('Type', 'None'), TYPE_VOCAB)
    weakness_vec = one_hot_encode(card_info.get('Weakness', 'None'), WEAKNESS_VOCAB)

    energy_cards          = poke_data.get('energyCards', [])
    attached_energy_types = count_attached_energy_types(energy_cards, card_dict)

    basic_stats  = [card_id, current_hp, max_hp, energy_count, retreat_cost, is_ex, tool_id]
    attack_stats = [attack_damage, attack_cost]

    return basic_stats + attack_stats + type_vec + weakness_vec + attached_energy_types

def extract_detailed_player_features(player_data, card_dict, max_card_id):
    features = []

    active_poke = player_data['active'][0] if player_data.get('active') else None
    features.extend(extract_detailed_pokemon_features(active_poke, card_dict))

    bench_pokes = player_data.get('bench', [])
    for i in range(5):
        if i < len(bench_pokes):
            features.extend(extract_detailed_pokemon_features(bench_pokes[i], card_dict))
        else:
            features.extend(extract_detailed_pokemon_features(None, card_dict))

    status_vec = [
        int(player_data.get('poisoned', False)),
        int(player_data.get('burned', False)),
        int(player_data.get('asleep', False)),
        int(player_data.get('paralyzed', False)),
        int(player_data.get('confused', False))
    ]
    features.extend(status_vec)

    hand_count  = player_data.get('handCount', 0)
    deck_count  = player_data.get('deckCount', 0)
    prize_count = sum(1 for p in player_data.get('prize', []) if p is not None)
    features.extend([hand_count, deck_count, prize_count])

    hand_features    = encode_card_list(player_data.get('hand', []), max_card_id)
    discard_features = encode_card_list(player_data.get('discard', []), max_card_id)

    features.extend(hand_features)
    features.extend(discard_features)

    return features

def extract_detailed_state_vector(step_data, card_dict, max_card_id):
    obs           = step_data.get('observation', {})
    current_state = obs.get('current')
    if not current_state or len(current_state.get('players', [])) < 2:
        return None

    stadium_list     = current_state.get('stadium', [])
    stadium_id       = stadium_list[0].get('id', 0) if stadium_list else 0
    supporter_played = int(current_state.get('supporterPlayed', False))
    energy_attached  = int(current_state.get('energyAttached', False))
    retreated        = int(current_state.get('retreated', False))
    first_player     = int(current_state.get('firstPlayer', -1))
    turn_num         = int(current_state.get('turn', 0))

    global_features = [stadium_id, supporter_played, energy_attached, retreated, first_player, turn_num]

    my_index = current_state.get('yourIndex', 0)
    op_index = 1 - my_index

    my_features = extract_detailed_player_features(current_state['players'][my_index], card_dict, max_card_id)
    op_features = extract_detailed_player_features(current_state['players'][op_index], card_dict, max_card_id)

    return np.array(global_features + my_features + op_features, dtype=np.float32)

# 次元数計算
expected_player_features_len = 47 + (5 * 47) + 5 + 3 + (MAX_CARD_ID + 1) + (MAX_CARD_ID + 1)
INPUT_DIM = 6 + (2 * expected_player_features_len)

print(f"プレイヤー特徴量: {expected_player_features_len} 次元")
print(f"状態ベクトル合計: {INPUT_DIM} 次元")

# ============================================================
# リーダーボード読み込み
# ============================================================
def load_score_map(csv_path):
    lb = pd.read_csv(csv_path)
    lb['TeamName'] = lb['TeamName'].str.strip()
    # スコアを 0-1 に正規化（最小スコアを基準として）
    min_score = lb['Score'].min()
    max_score = lb['Score'].max()
    lb['NormScore'] = (lb['Score'] - min_score) / (max_score - min_score + 1e-8) + 0.1
    return dict(zip(lb['TeamName'], lb['NormScore'])), dict(zip(lb['TeamName'], lb['Score']))

score_map, raw_score_map = load_score_map(LEADERBOARD_CSV)
print(f"リーダーボード読み込み完了: {len(score_map)} チーム")
print(f"スコア範囲: {min(raw_score_map.values()):.1f} ～ {max(raw_score_map.values()):.1f}")

def read_game_header(path):
    """ファイル先頭だけ読んでプレイヤー名・報酬を取得（高速化）"""
    with open(path, 'rb') as f:
        chunk = f.read(2048).decode('utf-8', errors='ignore')
    agents = re.findall(r'"Name":\s*"([^"]+)"', chunk)
    m = re.search(r'"rewards":\s*\[([^\]]+)\]', chunk)
    rewards = []
    if m:
        for x in m.group(1).split(','):
            try:
                rewards.append(int(x.strip()))
            except ValueError:
                rewards.append(0)
    return agents, rewards

# ============================================================
# モデル定義
# ============================================================
class PTCGBaselineNet(nn.Module):
    def __init__(self, input_dim, hidden_dim=1024, max_actions=256):
        super(PTCGBaselineNet, self).__init__()
        self.fc1 = nn.Linear(input_dim, hidden_dim)
        self.ln1 = nn.LayerNorm(hidden_dim)
        self.fc2 = nn.Linear(hidden_dim, hidden_dim // 2)
        self.ln2 = nn.LayerNorm(hidden_dim // 2)
        self.fc3 = nn.Linear(hidden_dim // 2, max_actions)

    def forward(self, x):
        x = F.relu(self.ln1(self.fc1(x)))
        x = F.relu(self.ln2(self.fc2(x)))
        return self.fc3(x)

# ============================================================
# Dataset
# ============================================================
class PTCGWeightedDataset(Dataset):
    def __init__(self, json_dir, card_dict, max_card_id,
                 score_map, max_actions=256, max_files=None):
        raw_states  = []
        raw_masks   = []
        raw_targets = []
        raw_weights = []

        json_files = sorted(glob.glob(os.path.join(json_dir, '*.json')))
        if max_files is not None:
            json_files = json_files[:max_files]

        print(f"解析対象: {len(json_files)} ファイル")
        skipped_unmatched = 0
        skipped_no_state  = 0
        skipped_invalid   = 0
        matched_games     = 0

        for file_path in tqdm(json_files, desc='JSONパース中'):
            try:
                agents, rewards = read_game_header(file_path)
            except Exception:
                continue

            if len(rewards) < 2:
                continue

            if rewards[0] == 1:
                winner_index = 0
                winner_name  = agents[0].strip() if agents else ''
            elif rewards[1] == 1:
                winner_index = 1
                winner_name  = agents[1].strip() if len(agents) > 1 else ''
            else:
                continue  # 引き分けスキップ

            weight = score_map.get(winner_name, 0.0)
            if weight == 0.0:
                skipped_unmatched += 1
                continue

            matched_games += 1

            try:
                with open(file_path, 'r') as f:
                    battle_log = json.load(f)
            except Exception:
                continue

            for step in battle_log.get('steps', []):
                if len(step) <= winner_index:
                    continue

                player_step = step[winner_index]
                state_vec   = extract_detailed_state_vector(player_step, card_dict, max_card_id)
                if state_vec is None:
                    skipped_no_state += 1
                    continue

                selected = player_step.get('action')
                if not selected:
                    continue

                obs         = player_step.get('observation', {})
                select_data = obs.get('select')
                if not select_data or 'option' not in select_data:
                    continue

                valid_count   = len(select_data['option'])
                target_action = selected[0]

                if target_action >= max_actions or target_action >= valid_count:
                    skipped_invalid += 1
                    continue

                raw_states.append(state_vec)
                raw_masks.append(np.arange(max_actions) >= valid_count)
                raw_targets.append(target_action)
                raw_weights.append(weight)

        print(f"\n--- データ収集結果 ---")
        print(f"リーダーボードマッチ試合数: {matched_games}")
        print(f"スキップ (未登録プレイヤー): {skipped_unmatched} 試合")
        print(f"スキップ (state=None): {skipped_no_state}")
        print(f"スキップ (不正action): {skipped_invalid}")
        print(f"有効サンプル数: {len(raw_states)}")

        if not raw_states:
            print("ERROR: 有効サンプルが0件です。")
            self.states  = torch.empty(0)
            self.weights = torch.empty(0)
            return

        # 正規化
        all_states      = np.stack(raw_states, axis=0)
        self.mean       = all_states.mean(axis=0)
        self.std        = all_states.std(axis=0)
        self.std[self.std == 0] = 1e-8

        np.savez(NORM_PATH, mean=self.mean, std=self.std)
        print(f"正規化パラメータを保存: {NORM_PATH}")

        norm_states = (all_states - self.mean) / self.std

        self.states  = torch.tensor(norm_states,           dtype=torch.float32)
        self.masks   = torch.tensor(np.stack(raw_masks),  dtype=torch.bool)
        self.targets = torch.tensor(raw_targets,           dtype=torch.long)
        self.weights = torch.tensor(raw_weights,           dtype=torch.float32)

        w = self.weights
        print(f"重みの分布: min={w.min():.3f} mean={w.mean():.3f} max={w.max():.3f}")

    def __len__(self):
        return len(self.states)

    def __getitem__(self, idx):
        return self.states[idx], self.masks[idx], self.targets[idx]

# ============================================================
# 学習実行
# ============================================================
print("\n== データ読み込み開始 ==")
dataset = PTCGWeightedDataset(
    JSON_DIRECTORY, card_dict, MAX_CARD_ID,
    score_map=score_map,
    max_actions=MAX_ACTIONS, max_files=MAX_FILES
)

if len(dataset) == 0:
    raise RuntimeError("有効サンプルなし。リーダーボードCSVとアーカイブの内容を確認してください。")

val_size   = int(len(dataset) * 0.2)
train_size = len(dataset) - val_size
train_ds, val_ds = torch.utils.data.random_split(
    dataset, [train_size, val_size],
    generator=torch.Generator().manual_seed(42)
)

# WeightedRandomSampler: 高スコアプレイヤーの行動を多くサンプリング
train_weights = dataset.weights[train_ds.indices]
sampler = WeightedRandomSampler(
    weights=train_weights,
    num_samples=len(train_weights),
    replacement=True
)

train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, sampler=sampler,  num_workers=0)
val_loader   = DataLoader(val_ds,   batch_size=BATCH_SIZE, shuffle=False, num_workers=0)

print(f"\n学習: {train_size} サンプル / 検証: {val_size} サンプル")
print(f"WeightedRandomSampler 有効（高スコアプレイヤー優先）")

device    = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
print(f"使用デバイス: {device}")

model     = PTCGBaselineNet(input_dim=INPUT_DIM, max_actions=MAX_ACTIONS).to(device)
criterion = nn.CrossEntropyLoss()
optimizer = optim.Adam(model.parameters(), lr=LEARNING_RATE)
scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='min', factor=0.5, patience=2)

print("\n== 学習開始 ==")
best_val_loss = float('inf')
best_val_acc  = 0.0

history = {
    'train_loss': [], 'val_loss': [],
    'train_acc':  [], 'val_acc':  [],
    'lr':         []
}

for epoch in range(EPOCHS):
    model.train()
    train_loss, train_correct, train_total = 0.0, 0, 0

    for states, masks, targets in tqdm(train_loader, desc=f"Epoch {epoch+1}/{EPOCHS} [train]", leave=False):
        states, masks, targets = states.to(device), masks.to(device), targets.to(device)

        outputs        = model(states)
        masked_outputs = outputs.masked_fill(masks, -1e9)
        loss           = criterion(masked_outputs, targets)

        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        train_loss    += loss.item() * states.size(0)
        train_correct += (masked_outputs.argmax(dim=1) == targets).sum().item()
        train_total   += states.size(0)

    model.eval()
    val_loss, val_correct, val_total = 0.0, 0, 0

    with torch.no_grad():
        for states, masks, targets in val_loader:
            states, masks, targets = states.to(device), masks.to(device), targets.to(device)
            outputs        = model(states)
            masked_outputs = outputs.masked_fill(masks, -1e9)
            loss           = criterion(masked_outputs, targets)

            val_loss    += loss.item() * states.size(0)
            val_correct += (masked_outputs.argmax(dim=1) == targets).sum().item()
            val_total   += states.size(0)

    t_loss = train_loss / train_total
    v_loss = val_loss   / val_total
    t_acc  = train_correct / train_total * 100
    v_acc  = val_correct   / val_total   * 100
    cur_lr = optimizer.param_groups[0]['lr']

    history['train_loss'].append(t_loss)
    history['val_loss'].append(v_loss)
    history['train_acc'].append(t_acc)
    history['val_acc'].append(v_acc)
    history['lr'].append(cur_lr)

    print(f"Epoch {epoch+1:2d}/{EPOCHS}  "
          f"train loss={t_loss:.4f} acc={t_acc:.1f}%  |  "
          f"val loss={v_loss:.4f} acc={v_acc:.1f}%  |  "
          f"lr={cur_lr:.2e}")

    scheduler.step(v_loss)

    if v_loss < best_val_loss:
        best_val_loss = v_loss
        best_val_acc  = v_acc
        torch.save(model.state_dict(), MODEL_PATH)
        print(f"  → ベストモデル保存 (val_loss={v_loss:.4f}, val_acc={v_acc:.1f}%)")

# ============================================================
# 学習曲線の可視化
# ============================================================
epochs_range = range(1, len(history['train_loss']) + 1)

fig, axes = plt.subplots(1, 3, figsize=(16, 5))
fig.suptitle('Weighted Imitation Learning - Training Results', fontsize=14, fontweight='bold')

# Loss
axes[0].plot(epochs_range, history['train_loss'], 'b-o', label='Train Loss', markersize=5)
axes[0].plot(epochs_range, history['val_loss'],   'r-o', label='Val Loss',   markersize=5)
best_ep = history['val_loss'].index(min(history['val_loss'])) + 1
axes[0].axvline(x=best_ep, color='g', linestyle='--', label=f'Best Epoch={best_ep}')
axes[0].set_xlabel('Epoch')
axes[0].set_ylabel('Cross-Entropy Loss')
axes[0].set_title('Loss Curve')
axes[0].legend()
axes[0].grid(True, alpha=0.3)

# Accuracy
axes[1].plot(epochs_range, history['train_acc'], 'b-o', label='Train Acc', markersize=5)
axes[1].plot(epochs_range, history['val_acc'],   'r-o', label='Val Acc',   markersize=5)
axes[1].axvline(x=best_ep, color='g', linestyle='--', label=f'Best Epoch={best_ep}')
axes[1].set_xlabel('Epoch')
axes[1].set_ylabel('Accuracy (%)')
axes[1].set_title('Accuracy Curve')
axes[1].legend()
axes[1].grid(True, alpha=0.3)

# Learning Rate
axes[2].plot(epochs_range, history['lr'], 'g-o', markersize=5)
axes[2].set_xlabel('Epoch')
axes[2].set_ylabel('Learning Rate')
axes[2].set_title('Learning Rate Schedule')
axes[2].set_yscale('log')
axes[2].grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(PLOT_PATH, dpi=150, bbox_inches='tight')
print(f"\n学習曲線を保存: {PLOT_PATH}")

# ============================================================
# 結果サマリ
# ============================================================
print("\n" + "="*60)
print("== 学習完了 ==")
print("="*60)
print(f"ベストエポック:    Epoch {best_ep}")
print(f"ベスト val_loss:   {best_val_loss:.4f}")
print(f"ベスト val_acc:    {best_val_acc:.1f}%")
print(f"最終 train_acc:    {history['train_acc'][-1]:.1f}%")
print(f"モデル保存先:      {MODEL_PATH}")
print(f"正規化パラメータ:  {NORM_PATH}")
print(f"学習曲線:          {PLOT_PATH}")
print("="*60)
