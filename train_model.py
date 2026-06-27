"""
ポケモン強化学習.ipynb の内容をスクリプトとして実行
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
from torch.utils.data import Dataset, DataLoader
from tqdm.auto import tqdm

# ============================================================
# 設定パラメータ
# ============================================================
JSON_DIRECTORY = 'archive'
MAX_ACTIONS    = 256
MAX_FILES      = None   # None=全ファイル / 整数=テスト用に制限
BATCH_SIZE     = 256
EPOCHS         = 10
LEARNING_RATE  = 1e-3
MODEL_PATH     = 'ptcg_baseline_model.pth'
NORM_PATH      = 'ptcg_normalization.npz'

# ----------------------------------------------------
# 1. カードデータの読み込み
# ----------------------------------------------------
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

# ----------------------------------------------------
# 2. 特徴量抽出
# ----------------------------------------------------
def extract_detailed_pokemon_features(poke_data, card_dict):
    empty_features = [0] * (7 + 2 + len(TYPE_VOCAB) + len(WEAKNESS_VOCAB) + len(TYPE_VOCAB))
    if not poke_data:
        return empty_features

    card_id     = poke_data.get('id', 0)
    current_hp  = poke_data.get('hp', 0)
    energy_count = len(poke_data.get('energies', []))

    tools   = poke_data.get('tools', [])
    tool_id = tools[0].get('id', 0) if tools else 0

    card_info      = card_dict.get(card_id, {})
    max_hp         = card_info.get('HP', 0)
    retreat_cost   = card_info.get('Retreat', 0)
    attack_damage  = parse_damage(card_info.get('Damage', "0"))
    attack_cost    = parse_cost(card_info.get('Cost', ""))
    is_ex          = 1 if "ex" in str(card_info.get('Rule', "")).lower() else 0

    type_vec    = one_hot_encode(card_info.get('Type', 'None'), TYPE_VOCAB)
    weakness_vec = one_hot_encode(card_info.get('Weakness', 'None'), WEAKNESS_VOCAB)

    energy_cards         = poke_data.get('energyCards', [])
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

# 次元数の計算
expected_player_features_len = 47 + (5 * 47) + 5 + 3 + (MAX_CARD_ID + 1) + (MAX_CARD_ID + 1)
INPUT_DIM = 6 + (2 * expected_player_features_len)

print(f"プレイヤー特徴量: {expected_player_features_len} 次元")
print(f"状態ベクトル合計: {INPUT_DIM} 次元")

# ----------------------------------------------------
# 3. モデル定義
# ----------------------------------------------------
class PTCGBaselineNet(nn.Module):
    def __init__(self, input_dim, hidden_dim=1024, max_actions=256):
        super(PTCGBaselineNet, self).__init__()
        self.fc1 = nn.Linear(input_dim, hidden_dim)
        self.ln1 = nn.LayerNorm(hidden_dim)
        self.fc2 = nn.Linear(hidden_dim, hidden_dim // 2)
        self.ln2 = nn.LayerNorm(hidden_dim // 2)
        self.fc3 = nn.Linear(hidden_dim // 2, max_actions)

    def forward(self, x):
        x      = F.relu(self.ln1(self.fc1(x)))
        x      = F.relu(self.ln2(self.fc2(x)))
        return self.fc3(x)

# ----------------------------------------------------
# 4. Dataset
# ----------------------------------------------------
class PTCGLogDataset(Dataset):
    def __init__(self, json_dir, card_dict, max_card_id, max_actions=256, max_files=None):
        raw_states  = []
        raw_masks   = []
        raw_targets = []

        json_files = sorted(glob.glob(os.path.join(json_dir, "*.json")))
        if max_files is not None:
            json_files = json_files[:max_files]

        print(f"解析対象: {len(json_files)} ファイル")

        skipped_invalid  = 0
        skipped_no_state = 0

        for file_path in tqdm(json_files, desc="JSONパース中"):
            try:
                with open(file_path, 'r') as f:
                    battle_log = json.load(f)
            except Exception:
                continue

            rewards = battle_log.get('rewards', [0, 0])
            if rewards[0] == 1:
                winner_index = 0
            elif rewards[1] == 1:
                winner_index = 1
            else:
                continue  # 引き分けはスキップ

            for step in battle_log.get('steps', []):
                if len(step) <= winner_index:
                    continue

                player_step_data = step[winner_index]

                state_vec = extract_detailed_state_vector(player_step_data, card_dict, max_card_id)
                if state_vec is None:
                    skipped_no_state += 1
                    continue

                selected = player_step_data.get('action')
                if not selected:
                    continue

                obs         = player_step_data.get('observation', {})
                select_data = obs.get('select')
                if not select_data or 'option' not in select_data:
                    continue

                valid_count   = len(select_data['option'])
                target_action = selected[0]

                if target_action >= max_actions or target_action >= valid_count:
                    skipped_invalid += 1
                    continue

                mask_vec = np.arange(max_actions) >= valid_count

                raw_states.append(state_vec)
                raw_masks.append(mask_vec)
                raw_targets.append(target_action)

        print(f"スキップ (state=None): {skipped_no_state}, スキップ (不正action): {skipped_invalid}")
        print(f"有効サンプル数 (正規化前): {len(raw_states)}")

        if not raw_states:
            print("ERROR: 有効サンプルが0件です。")
            self.states = torch.empty(0)
            return

        all_states     = np.stack(raw_states, axis=0)
        self.mean      = all_states.mean(axis=0)
        self.std       = all_states.std(axis=0)
        self.std[self.std == 0] = 1e-8

        np.savez(NORM_PATH, mean=self.mean, std=self.std)
        print(f"正規化パラメータを保存: {NORM_PATH}")

        norm_states = (all_states - self.mean) / self.std

        self.states  = torch.tensor(norm_states,         dtype=torch.float32)
        self.masks   = torch.tensor(np.stack(raw_masks), dtype=torch.bool)
        self.targets = torch.tensor(raw_targets,         dtype=torch.long)

        print(f"有効サンプル数: {len(self.states)}")

    def __len__(self):
        return len(self.states)

    def __getitem__(self, idx):
        return self.states[idx], self.masks[idx], self.targets[idx]

# ----------------------------------------------------
# 5. 学習
# ----------------------------------------------------
print("\n== データ読み込み開始 ==")
dataset = PTCGLogDataset(JSON_DIRECTORY, card_dict, MAX_CARD_ID,
                         max_actions=MAX_ACTIONS, max_files=MAX_FILES)

if len(dataset) == 0:
    raise RuntimeError("有効サンプルなし")

val_size   = int(len(dataset) * 0.2)
train_size = len(dataset) - val_size
train_ds, val_ds = torch.utils.data.random_split(dataset, [train_size, val_size])

train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True,  num_workers=0)
val_loader   = DataLoader(val_ds,   batch_size=BATCH_SIZE, shuffle=False, num_workers=0)

print(f"学習: {train_size} / 検証: {val_size} サンプル")

device    = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
print(f"使用デバイス: {device}")

model     = PTCGBaselineNet(input_dim=INPUT_DIM, max_actions=MAX_ACTIONS).to(device)
criterion = nn.CrossEntropyLoss()
optimizer = optim.Adam(model.parameters(), lr=LEARNING_RATE)
scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='min', factor=0.5, patience=2)

print("\n== 学習開始 ==")
best_val_loss = float('inf')

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
        preds          = masked_outputs.argmax(dim=1)
        train_correct += (preds == targets).sum().item()
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
            preds        = masked_outputs.argmax(dim=1)
            val_correct += (preds == targets).sum().item()
            val_total   += states.size(0)

    t_loss = train_loss / train_total
    v_loss = val_loss   / val_total
    t_acc  = train_correct / train_total * 100
    v_acc  = val_correct   / val_total   * 100

    print(f"Epoch {epoch+1:2d}/{EPOCHS}  "
          f"train loss={t_loss:.4f} acc={t_acc:.1f}%  |  "
          f"val loss={v_loss:.4f} acc={v_acc:.1f}%")

    scheduler.step(v_loss)

    if v_loss < best_val_loss:
        best_val_loss = v_loss
        torch.save(model.state_dict(), MODEL_PATH)
        print(f"  → ベストモデル保存 (val_loss={v_loss:.4f})")

print(f"\n== 学習完了 ==")
print(f"モデル: {MODEL_PATH}")
print(f"正規化パラメータ: {NORM_PATH}")
