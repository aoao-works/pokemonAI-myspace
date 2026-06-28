"""
rb エージェント: NN (MAIN選択) + ルールベース baseline (非MAIN選択) の組み合わせ。
train_vs_rulebased.py の学習設定を arena で完全再現したエージェント。
"""
import os, sys, importlib.util
import torch, torch.nn as nn, torch.nn.functional as F, numpy as np

HERE    = os.path.dirname(os.path.abspath(__file__))
STADIUM = os.path.normpath(os.path.join(HERE, '..', '..'))
SUB     = os.path.normpath(os.path.join(HERE, '..', '..', '..', 'submission'))
sys.path.insert(0, STADIUM)

from cg.api import (
    to_observation_class, SelectType,
    EnergyType, OptionType, all_card_data, all_attack,
)

# ============================================================
# 特徴量抽出 (train_vs_rulebased.py と同一)
# ============================================================
MAX_CARD_ID = 1267
MAX_ACTIONS = 256

TYPE_VOCAB = [
    '{G}', '{R}', '{W}', '{L}', '{P}', '{F}', '{D}', '{M}', '{C}', '竜',
    '{A}', '{A}{A}', '{Team Rocket}{Team Rocket}', '{C}{C}{C}',
]
WEAKNESS_VOCAB = ['{G}', '{R}', '{W}', '{L}', '{P}', '{F}', '{D}', '{M}', '{C}', '竜']
_ENERGY_TYPE_STR = {
    EnergyType.COLORLESS: '{C}', EnergyType.GRASS: '{G}', EnergyType.FIRE: '{R}',
    EnergyType.WATER: '{W}', EnergyType.LIGHTNING: '{L}', EnergyType.PSYCHIC: '{P}',
    EnergyType.FIGHTING: '{F}', EnergyType.DARKNESS: '{D}', EnergyType.METAL: '{M}',
    EnergyType.DRAGON: '竜', EnergyType.RAINBOW: '{A}',
    EnergyType.TEAM_ROCKET: '{Team Rocket}{Team Rocket}',
}

def _build_card_dict():
    atk_map = {a.attackId: a for a in all_attack()}
    d = {}
    for c in all_card_data():
        type_str = _ENERGY_TYPE_STR.get(c.energyType, 'None')
        weak_str = _ENERGY_TYPE_STR.get(c.weakness, 'None') if c.weakness is not None else 'None'
        fa = atk_map.get(c.attacks[0]) if c.attacks else None
        d[c.cardId] = {
            'HP': c.hp, 'Retreat': c.retreatCost, 'Type': type_str, 'Weakness': weak_str,
            'Damage': fa.damage if fa else 0, 'Cost': len(fa.energies) if fa else 0,
            'is_ex': 1 if (c.ex or c.megaEx) else 0, 'basic': c.basic,
        }
    return d

_card_dict = _build_card_dict()

def _one_hot(val, vocab):
    v = [0] * len(vocab)
    if val in vocab: v[vocab.index(val)] = 1
    return v

def _pokemon_feat(poke):
    empty = [0] * (7 + 2 + len(TYPE_VOCAB) + len(WEAKNESS_VOCAB) + len(TYPE_VOCAB))
    if poke is None: return empty
    ci = _card_dict.get(poke.id, {})
    tool_id = poke.tools[0].id if poke.tools else 0
    en_tc = [0] * len(TYPE_VOCAB)
    for ec in (poke.energyCards or []):
        et = _card_dict.get(ec.id, {}).get('Type', 'None')
        if et in TYPE_VOCAB: en_tc[TYPE_VOCAB.index(et)] += 1
    return (
        [poke.id, poke.hp, ci.get('HP', 0), len(poke.energies),
         ci.get('Retreat', 0), ci.get('is_ex', 0), tool_id]
        + [ci.get('Damage', 0), ci.get('Cost', 0)]
        + _one_hot(ci.get('Type', 'None'), TYPE_VOCAB)
        + _one_hot(ci.get('Weakness', 'None'), WEAKNESS_VOCAB)
        + en_tc
    )

def _player_feat(p):
    f = []
    f.extend(_pokemon_feat(p.active[0] if p.active else None))
    bench = p.bench or []
    for i in range(5): f.extend(_pokemon_feat(bench[i] if i < len(bench) else None))
    f.extend([int(p.poisoned), int(p.burned), int(p.asleep), int(p.paralyzed), int(p.confused)])
    f.extend([p.handCount, p.deckCount, sum(1 for pr in p.prize if pr is not None)])
    hv, dv = [0]*(MAX_CARD_ID+1), [0]*(MAX_CARD_ID+1)
    for c in (p.hand or []):
        if 0 <= c.id <= MAX_CARD_ID: hv[c.id] += 1
    for c in (p.discard or []):
        if 0 <= c.id <= MAX_CARD_ID: dv[c.id] += 1
    f.extend(hv); f.extend(dv)
    return f

def _extract_state_vector(obs):
    s = obs.current
    if s is None or len(s.players) < 2: return None
    gf = [s.stadium[0].id if s.stadium else 0,
          int(s.supporterPlayed), int(s.energyAttached), int(s.retreated),
          s.firstPlayer, s.turn]
    mi = s.yourIndex
    return np.array(gf + _player_feat(s.players[mi]) + _player_feat(s.players[1-mi]),
                    dtype=np.float32)

# ============================================================
# NN モデル (ptcg_rb_model.pth)
# ============================================================
class _Net(nn.Module):
    def __init__(self):
        super().__init__()
        self.fc1 = nn.Linear(5658, 1024); self.ln1 = nn.LayerNorm(1024)
        self.fc2 = nn.Linear(1024, 512);  self.ln2 = nn.LayerNorm(512)
        self.fc3 = nn.Linear(512, 256)
    def forward(self, x):
        x = F.relu(self.ln1(self.fc1(x)))
        x = F.relu(self.ln2(self.fc2(x)))
        return self.fc3(x)

_net = _Net()
_rb_path = os.path.join(SUB, 'ptcg_rb_model.pth')
_net.load_state_dict(torch.load(_rb_path, map_location='cpu', weights_only=True))
_net.eval()
_norm = np.load(os.path.join(SUB, 'ptcg_normalization.npz'))
_norm_mean = _norm['mean'].astype(np.float32)
_norm_std  = _norm['std'].astype(np.float32)
print(f"[rb agent] loaded {_rb_path}")

# ============================================================
# ルールベース baseline (非MAIN 選択用)
# ============================================================
def _load_rb_module():
    spec = importlib.util.spec_from_file_location(
        "_rb_helper_arena",
        os.path.join(STADIUM, "agents", "baseline", "main.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.read_deck_csv = lambda: []  # デッキ選択は arena が処理
    return mod

_rb_mod = _load_rb_module()

# MAIN 優先度フォールバック (NN が None を返した場合)
_MAIN_PRI = {
    OptionType.ATTACK: 6, OptionType.EVOLVE: 5, OptionType.PLAY: 4,
    OptionType.ABILITY: 3, OptionType.ATTACH: 2, OptionType.RETREAT: 1, OptionType.END: 0,
}

# ============================================================
# デッキ読み込み
# ============================================================
def read_deck_csv() -> list[int]:
    deck_path = os.path.join(HERE, "deck.csv")
    with open(deck_path, "r") as f:
        rows = f.read().split("\n")
    return [int(rows[i]) for i in range(60)]

# arena.py がゲーム間でリセットするための _STATE
_STATE = {"turn": -1, "turn_actions": 0}

# ============================================================
# エージェント本体
# ============================================================
def agent(obs_dict: dict) -> list[int]:
    obs = to_observation_class(obs_dict)

    if obs.select is None:
        return read_deck_csv()

    is_main = False
    try:
        is_main = (SelectType(obs.select.type) == SelectType.MAIN)
    except Exception:
        pass

    if is_main:
        # NN が MAIN 選択を担当 (train_vs_rulebased.py と同一ロジック)
        sv = _extract_state_vector(obs)
        if sv is not None:
            nsv = (sv - _norm_mean) / (_norm_std + 1e-8)
            x = torch.FloatTensor(nsv).unsqueeze(0)
            n_valid = len(obs.select.option)
            with torch.no_grad():
                logits = _net(x)
                mask = torch.zeros(MAX_ACTIONS, dtype=torch.bool)
                mask[n_valid:] = True
                a_idx = logits[0].masked_fill(mask, -1e9).argmax().item()
            if 0 <= a_idx < n_valid:
                return [a_idx]
        # フォールバック: 優先度ルールで最良 MAIN アクションを選ぶ
        best_i = max(range(len(obs.select.option)),
                     key=lambda i: _MAIN_PRI.get(obs.select.option[i].type, -1))
        return [best_i]

    # 非MAIN 選択: ルールベース baseline が担当
    return _rb_mod.agent(obs_dict)
