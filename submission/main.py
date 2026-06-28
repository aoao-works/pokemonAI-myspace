import os
import re
import json
import numpy as np

from cg.api import (to_observation_class, Observation, SelectType, OptionType,
                    SelectContext, EnergyType, all_card_data, all_attack)
from cg.sim import lib

# ============================================================
# Constants
# ============================================================
MAX_CARD_ID = 1267
MAX_ACTIONS = 256
INPUT_DIM   = 5658  # 6 + 2*(47 + 5*47 + 5 + 3 + (MAX_CARD_ID+1)*2)

TYPE_VOCAB = [
    '{G}', '{R}', '{W}', '{L}', '{P}', '{F}', '{D}', '{M}', '{C}', '竜',
    '{A}', '{A}{A}', '{Team Rocket}{Team Rocket}', '{C}{C}{C}',
]
WEAKNESS_VOCAB = ['{G}', '{R}', '{W}', '{L}', '{P}', '{F}', '{D}', '{M}', '{C}', '竜']

_ENERGY_TYPE_STR = {
    EnergyType.COLORLESS:   '{C}',
    EnergyType.GRASS:       '{G}',
    EnergyType.FIRE:        '{R}',
    EnergyType.WATER:       '{W}',
    EnergyType.LIGHTNING:   '{L}',
    EnergyType.PSYCHIC:     '{P}',
    EnergyType.FIGHTING:    '{F}',
    EnergyType.DARKNESS:    '{D}',
    EnergyType.METAL:       '{M}',
    EnergyType.DRAGON:      '竜',
    EnergyType.RAINBOW:     '{A}',
    EnergyType.TEAM_ROCKET: '{Team Rocket}{Team Rocket}',
}

# ============================================================
# Card dict (built from game engine API — no CSV needed)
# ============================================================
def _build_card_dict():
    atk_map = {a.attackId: a for a in all_attack()}
    d = {}
    for c in all_card_data():
        type_str = _ENERGY_TYPE_STR.get(c.energyType, 'None')
        weak_str = _ENERGY_TYPE_STR.get(c.weakness, 'None') if c.weakness is not None else 'None'
        first_atk = atk_map.get(c.attacks[0]) if c.attacks else None
        d[c.cardId] = {
            'HP':       c.hp,
            'Retreat':  c.retreatCost,
            'Type':     type_str,
            'Weakness': weak_str,
            'Damage':   first_atk.damage        if first_atk else 0,
            'Cost':     len(first_atk.energies) if first_atk else 0,
            'is_ex':    1 if (c.ex or c.megaEx) else 0,
        }
    return d

try:
    _card_dict = _build_card_dict()
except Exception:
    _card_dict = {}

# ============================================================
# Feature extraction (must match train_model.py exactly)
# ============================================================
def _one_hot(val, vocab):
    v = [0] * len(vocab)
    if val in vocab:
        v[vocab.index(val)] = 1
    return v

def _pokemon_feat(poke):
    empty = [0] * (7 + 2 + len(TYPE_VOCAB) + len(WEAKNESS_VOCAB) + len(TYPE_VOCAB))
    if poke is None:
        return empty

    ci      = _card_dict.get(poke.id, {})
    tool_id = poke.tools[0].id if poke.tools else 0

    en_type_counts = [0] * len(TYPE_VOCAB)
    for ec in (poke.energyCards or []):
        etype = _card_dict.get(ec.id, {}).get('Type', 'None')
        if etype in TYPE_VOCAB:
            en_type_counts[TYPE_VOCAB.index(etype)] += 1

    return (
        [poke.id, poke.hp, ci.get('HP', 0), len(poke.energies),
         ci.get('Retreat', 0), ci.get('is_ex', 0), tool_id]
        + [ci.get('Damage', 0), ci.get('Cost', 0)]
        + _one_hot(ci.get('Type',    'None'), TYPE_VOCAB)
        + _one_hot(ci.get('Weakness','None'), WEAKNESS_VOCAB)
        + en_type_counts
    )

def _player_feat(p):
    features = []
    features.extend(_pokemon_feat(p.active[0] if p.active else None))
    bench = p.bench or []
    for i in range(5):
        features.extend(_pokemon_feat(bench[i] if i < len(bench) else None))
    features.extend([int(p.poisoned), int(p.burned), int(p.asleep),
                     int(p.paralyzed), int(p.confused)])
    prize_count = sum(1 for pr in p.prize if pr is not None)
    features.extend([p.handCount, p.deckCount, prize_count])

    hand_v    = [0] * (MAX_CARD_ID + 1)
    discard_v = [0] * (MAX_CARD_ID + 1)
    for c in (p.hand or []):
        if 0 <= c.id <= MAX_CARD_ID:
            hand_v[c.id] += 1
    for c in (p.discard or []):
        if 0 <= c.id <= MAX_CARD_ID:
            discard_v[c.id] += 1
    features.extend(hand_v)
    features.extend(discard_v)
    return features

def _extract_state_vector(obs):
    state = obs.current
    if state is None or len(state.players) < 2:
        return None

    stadium_id = state.stadium[0].id if state.stadium else 0
    global_f = [
        stadium_id,
        int(state.supporterPlayed),
        int(state.energyAttached),
        int(state.retreated),
        state.firstPlayer,
        state.turn,
    ]

    my_idx = state.yourIndex
    op_idx = 1 - my_idx
    return np.array(
        global_f
        + _player_feat(state.players[my_idx])
        + _player_feat(state.players[op_idx]),
        dtype=np.float32
    )

# ============================================================
# Model loading (lazy — runs once at import)
# ============================================================
_model      = None
_norm_mean  = None
_norm_std   = None

def _agent_dir():
    d = "/kaggle_simulations/agent"
    return d if os.path.exists(d) else os.path.dirname(os.path.abspath(__file__))

def _load_model():
    global _model, _norm_mean, _norm_std
    try:
        import torch
        import torch.nn as nn
        import torch.nn.functional as F

        class _Net(nn.Module):
            def __init__(self):
                super().__init__()
                self.fc1 = nn.Linear(INPUT_DIM, 1024)
                self.ln1 = nn.LayerNorm(1024)
                self.fc2 = nn.Linear(1024, 512)
                self.ln2 = nn.LayerNorm(512)
                self.fc3 = nn.Linear(512, MAX_ACTIONS)
            def forward(self, x):
                x = F.relu(self.ln1(self.fc1(x)))
                x = F.relu(self.ln2(self.fc2(x)))
                return self.fc3(x)

        base       = _agent_dir()
        model_path = os.path.join(base, "ptcg_baseline_model.pth")
        norm_path  = os.path.join(base, "ptcg_normalization.npz")
        if not os.path.exists(model_path) or not os.path.exists(norm_path):
            return

        norm = np.load(norm_path)
        _norm_mean = norm['mean']
        _norm_std  = norm['std']

        net = _Net()
        net.load_state_dict(torch.load(model_path, map_location='cpu', weights_only=True))
        net.eval()
        _model = net
    except Exception:
        pass

_load_model()

# ============================================================
# Neural network inference
# ============================================================
def _nn_pick(obs, valid_count):
    if _model is None:
        return None
    try:
        import torch
        sv = _extract_state_vector(obs)
        if sv is None:
            return None

        norm_sv = (sv - _norm_mean) / _norm_std
        x    = torch.tensor(norm_sv, dtype=torch.float32).unsqueeze(0)
        mask = (torch.arange(MAX_ACTIONS) >= valid_count).unsqueeze(0)
        with torch.no_grad():
            logits = _model(x)
            action = logits.masked_fill(mask, -1e9).argmax(dim=1).item()

        return action if 0 <= action < valid_count else None
    except Exception:
        return None

# ============================================================
# Rule-based fallbacks
# ============================================================
_ATK_DAMAGE = {}
try:
    for _a in json.loads(lib.AllAttack().decode()):
        _ATK_DAMAGE[_a["attackId"]] = _a.get("damage", 0) or 0
except Exception:
    pass

_MAIN_PRIORITY = {
    OptionType.EVOLVE:  6,
    OptionType.ABILITY: 5,
    OptionType.PLAY:    4,
    OptionType.ATTACH:  3,
    OptionType.ATTACK:  2,
    OptionType.RETREAT: 1,
    OptionType.END:     0,
}

_LOSS_CONTEXTS = {
    SelectContext.DISCARD, SelectContext.TO_DECK, SelectContext.TO_DECK_BOTTOM,
    SelectContext.DISCARD_ENERGY_CARD, SelectContext.DISCARD_TOOL_CARD,
    SelectContext.DISCARD_CARD_OR_ATTACHED_CARD, SelectContext.DISCARD_ENERGY,
    SelectContext.TO_DECK_ENERGY, SelectContext.DEVOLVE,
}

_STATE = {"turn": -1, "turn_actions": 0}


def read_deck_csv():
    path = "deck.csv"
    if not os.path.exists(path):
        path = "/kaggle_simulations/agent/deck.csv"
    with open(path, "r") as f:
        rows = f.read().split("\n")
    return [int(rows[i]) for i in range(60)]


def _safe_default(sel):
    n = len(sel.option)
    k = max(sel.minCount, 1)
    k = min(k, sel.maxCount, n)
    return list(range(k))


def _rule_pick_main(sel):
    best_i, best_score = 0, -1
    for i, op in enumerate(sel.option):
        score = _MAIN_PRIORITY.get(op.type, 0) * 1000
        if score > best_score:
            best_score, best_i = score, i
    return [best_i]


def _pick_count(sel):
    best_i, best_val = 0, -1
    for i, op in enumerate(sel.option):
        v = op.number if op.number is not None else (op.count or 0)
        if v > best_val:
            best_val, best_i = v, i
    return [best_i]


def _pick_yesno(sel):
    for i, op in enumerate(sel.option):
        if op.type == OptionType.YES:
            return [i]
    return [0]


def _pick_set(sel):
    n = len(sel.option)
    try:
        ctx = SelectContext(sel.context)
    except Exception:
        ctx = None
    k = sel.minCount if ctx in _LOSS_CONTEXTS else sel.maxCount
    k = max(min(k, sel.maxCount, n), sel.minCount)
    return list(range(min(k, n))) if k > 0 else []


# ============================================================
# Agent entry point
# ============================================================
def agent(obs_dict):
    obs = to_observation_class(obs_dict)

    if obs.select is None:
        return read_deck_csv()

    sel = obs.select

    try:
        cur = obs.current
        if cur is not None:
            if cur.turn != _STATE["turn"]:
                _STATE["turn"]         = cur.turn
                _STATE["turn_actions"] = 0
            _STATE["turn_actions"] += 1
    except Exception:
        pass

    try:
        st = SelectType(sel.type)
    except Exception:
        return _safe_default(sel)

    try:
        if st == SelectType.MAIN:
            # Infinite-loop guard
            if _STATE["turn_actions"] > 40:
                for i, op in enumerate(sel.option):
                    if op.type == OptionType.ATTACK:
                        return [i]
                for i, op in enumerate(sel.option):
                    if op.type == OptionType.END:
                        return [i]
            # Neural network decision
            nn_action = _nn_pick(obs, len(sel.option))
            if nn_action is not None:
                return [nn_action]
            # Rule-based fallback
            return _rule_pick_main(sel)

        elif st == SelectType.YES_NO:
            return _pick_yesno(sel)

        elif st == SelectType.COUNT:
            return _pick_count(sel)

        elif st == SelectType.ATTACK:
            best_i, best = 0, -1
            for i, op in enumerate(sel.option):
                d = _ATK_DAMAGE.get(op.attackId, 0)
                if d > best:
                    best, best_i = d, i
            return [best_i]

        else:
            return _pick_set(sel)

    except Exception:
        return _safe_default(sel)
