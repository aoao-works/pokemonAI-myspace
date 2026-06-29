import os
import json
import time
import math
import random
import numpy as np
from collections import Counter

from cg.api import (to_observation_class, Observation, SelectType, OptionType,
                    SelectContext, EnergyType, all_card_data, all_attack,
                    search_begin, search_step, search_end, search_release)
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
# Card dict
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
            'basic':    c.basic,
        }
    return d

try:
    _card_dict = _build_card_dict()
except Exception:
    _card_dict = {}

# ============================================================
# Feature extraction
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
# Model loading
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

        base = _agent_dir()
        # best > league > rl > baseline の優先順位でモデルを選択
        for candidate in ("ptcg_best_model.pth", "ptcg_league_model.pth", "ptcg_rl_model.pth", "ptcg_baseline_model.pth"):
            model_path = os.path.join(base, candidate)
            if os.path.exists(model_path):
                break
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

        norm_sv = (sv - _norm_mean) / (_norm_std + 1e-8)
        x    = torch.tensor(norm_sv, dtype=torch.float32).unsqueeze(0)
        mask = (torch.arange(MAX_ACTIONS) >= valid_count).unsqueeze(0)
        with torch.no_grad():
            logits = _model(x)
            action = logits.masked_fill(mask, -1e9).argmax(dim=1).item()

        return action if 0 <= action < valid_count else None
    except Exception:
        return None

# ============================================================
# Rule-based helpers
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

# ============================================================
# MCTS
# ============================================================
MCTS_TIME_BUDGET = 0.3   # seconds per MAIN selection
MCTS_MAX_DEPTH   = 20    # max rollout steps per simulation
MCTS_C           = math.sqrt(2)

_GAME_STATE = {
    "full_deck": None,  # list[int]: our 60-card deck
}


def _remove_known_cards(full: Counter, player, include_hand=True):
    """Subtract cards visible on the field from a Counter."""
    def sub(card_id):
        if full[card_id] > 0:
            full[card_id] -= 1

    def sub_poke(poke):
        if poke is None:
            return
        sub(poke.id)
        for ec in poke.energyCards:
            sub(ec.id)
        for tc in poke.tools:
            sub(tc.id)

    if include_hand and player.hand:
        for c in player.hand:
            sub(c.id)
    if player.discard:
        for c in player.discard:
            sub(c.id)
    if player.active:
        for p in player.active:
            sub_poke(p)
    for p in player.bench:
        sub_poke(p)
    for prize in player.prize:
        if prize is not None:
            sub(prize.id)


def _predict_my_info(obs, my_index):
    """Return (predicted_deck, predicted_prize) for our side."""
    if _GAME_STATE["full_deck"] is None or obs.current is None:
        return [], []
    player = obs.current.players[my_index]
    full = Counter(_GAME_STATE["full_deck"])
    _remove_known_cards(full, player, include_hand=True)

    remaining = [cid for cid, cnt in full.items() for _ in range(max(0, cnt))]
    random.shuffle(remaining)

    n_prize_unknown = sum(1 for p in player.prize if p is None)
    n_deck = player.deckCount
    needed = n_prize_unknown + n_deck
    while len(remaining) < needed:
        remaining.append(_GAME_STATE["full_deck"][0])

    return remaining[n_prize_unknown:needed], remaining[:n_prize_unknown]


def _predict_opp_info(obs, my_index):
    """Return (opp_deck, opp_prize, opp_hand) using our deck as template."""
    if _GAME_STATE["full_deck"] is None or obs.current is None:
        return [], [], []
    opp_index = 1 - my_index
    player = obs.current.players[opp_index]
    full = Counter(_GAME_STATE["full_deck"])
    # Subtract cards we can see on opponent's side (no hand access)
    _remove_known_cards(full, player, include_hand=False)

    remaining = [cid for cid, cnt in full.items() for _ in range(max(0, cnt))]
    random.shuffle(remaining)

    n_prize = len(player.prize)
    n_deck  = player.deckCount
    n_hand  = player.handCount
    needed  = n_prize + n_deck + n_hand
    while len(remaining) < needed:
        remaining.append(_GAME_STATE["full_deck"][0])
    remaining = remaining[:needed]

    return remaining[n_prize:n_prize + n_deck], remaining[:n_prize], remaining[n_prize + n_deck:]


def _find_basic_pokemon_id():
    """Return the card ID of the first basic Pokémon in our deck."""
    if not _GAME_STATE["full_deck"]:
        return None
    for cid in _GAME_STATE["full_deck"]:
        if _card_dict.get(cid, {}).get('basic', False):
            return cid
    return _GAME_STATE["full_deck"][0]


def _heuristic_value(obs, my_index):
    """Estimate state value in [0, 1] (0=losing, 1=winning)."""
    if obs is None or obs.current is None or len(obs.current.players) < 2:
        return 0.5

    my_p  = obs.current.players[my_index]
    opp_p = obs.current.players[1 - my_index]

    # Prize advantage: fewer remaining prizes = closer to winning
    prize_adv = (len(opp_p.prize) - len(my_p.prize)) / 6.0

    # HP advantage on active
    def hp_ratio(p):
        if p.active and p.active[0] is not None:
            pk = p.active[0]
            return pk.hp / pk.maxHp if pk.maxHp > 0 else 0.5
        return 0.5

    hp_adv = hp_ratio(my_p) - hp_ratio(opp_p)

    return max(0.0, min(1.0, 0.5 + prize_adv * 0.35 + hp_adv * 0.15))


def _rollout(start_id, start_obs, my_index):
    """
    Random rollout from start_id. Releases all states it creates internally.
    Does NOT release start_id. Returns value in [0, 1].
    """
    created = []
    current_id  = start_id
    current_obs = start_obs

    try:
        for _ in range(MCTS_MAX_DEPTH):
            cur = current_obs.current
            if cur is not None and cur.result != -1:
                w = cur.result
                return 1.0 if w == my_index else (0.5 if w == 2 else 0.0)

            sel = current_obs.select
            if sel is None or not sel.option:
                return _heuristic_value(current_obs, my_index)

            n_opt  = len(sel.option)
            min_c  = max(getattr(sel, 'minCount', 1), 1)
            max_c  = min(getattr(sel, 'maxCount', 1), n_opt)
            k      = max(min_c, 1)
            k      = min(k, max_c)
            acts   = random.sample(range(n_opt), min(k, n_opt))
            try:
                next_s = search_step(current_id, acts)
            except Exception:
                return _heuristic_value(current_obs, my_index)

            current_id  = next_s.searchId
            current_obs = next_s.observation
            created.append(current_id)

        return _heuristic_value(current_obs, my_index)

    finally:
        for sid in reversed(created):
            try:
                search_release(sid)
            except Exception:
                pass


def _mcts_search(obs):
    """
    Flat UCB1 MCTS for a MAIN selection.
    Returns best action index, or None on failure.
    """
    if obs.search_begin_input is None:
        return None
    if obs.current is None or _GAME_STATE["full_deck"] is None:
        return None

    my_index = obs.current.yourIndex

    try:
        my_deck, my_prize = _predict_my_info(obs, my_index)
        opp_deck, opp_prize, opp_hand = _predict_opp_info(obs, my_index)

        # Handle face-down opponent active (rare but must be handled)
        opp_active = []
        opp_p = obs.current.players[1 - my_index]
        if opp_p.active and opp_p.active[0] is None:
            basic_id = _find_basic_pokemon_id()
            if basic_id is not None:
                opp_active = [basic_id]
            else:
                return None

        root = search_begin(
            obs, my_deck, my_prize, opp_deck, opp_prize, opp_hand, opp_active
        )
    except Exception:
        return None

    n = len(obs.select.option)
    visits = [0] * n
    values = [0.0] * n
    total  = 0

    deadline = time.time() + MCTS_TIME_BUDGET

    try:
        while time.time() < deadline:
            # UCB1 action selection
            if total == 0:
                action = random.randrange(n)
            else:
                log_t = math.log(total + 1)
                best_ucb, action = -1.0, 0
                for i in range(n):
                    if visits[i] == 0:
                        action = i
                        break
                    ucb = values[i] / visits[i] + MCTS_C * math.sqrt(log_t / visits[i])
                    if ucb > best_ucb:
                        best_ucb, action = ucb, i

            # Expand: one step from root with this action
            try:
                child = search_step(root.searchId, [action])
            except Exception:
                visits[action] += 1
                values[action] += 0.5
                total += 1
                continue

            # Rollout (releases all states it creates)
            value = _rollout(child.searchId, child.observation, my_index)

            # Release child after rollout
            try:
                search_release(child.searchId)
            except Exception:
                pass

            visits[action] += 1
            values[action] += value
            total += 1

    finally:
        try:
            search_end()
        except Exception:
            pass

    if total == 0:
        return None

    # Best action = most visited (robust choice over highest win rate)
    return max(range(n), key=lambda i: visits[i])


# ============================================================
# Deck reading
# ============================================================
def read_deck_csv():
    path = "deck.csv"
    if not os.path.exists(path):
        path = "/kaggle_simulations/agent/deck.csv"
    with open(path, "r") as f:
        rows = f.read().split("\n")
    deck = [int(rows[i]) for i in range(60)]
    _GAME_STATE["full_deck"] = deck
    return deck


# ============================================================
# Rule-based fallbacks
# ============================================================
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

            # NN (primary)
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
