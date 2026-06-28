#!/usr/bin/env python3
"""eval_1000.py: 指定モデル vs baseline を N 戦して勝率を計測"""
import os, sys, json, random, time, argparse
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "PTCGstadium"))

from cg.api import (
    to_observation_class, SelectType, SelectContext, OptionType,
    EnergyType, all_card_data, all_attack,
)
from cg.game import battle_start, battle_select, battle_finish

MAX_CARD_ID = 1267
MAX_ACTIONS = 256
INPUT_DIM   = 5658

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
    for i in range(5):
        f.extend(_pokemon_feat(bench[i] if i < len(bench) else None))
    f.extend([int(p.poisoned), int(p.burned), int(p.asleep), int(p.paralyzed), int(p.confused)])
    f.extend([p.handCount, p.deckCount, sum(1 for pr in p.prize if pr is not None)])
    hv, dv = [0]*(MAX_CARD_ID+1), [0]*(MAX_CARD_ID+1)
    for c in (p.hand or []):
        if 0 <= c.id <= MAX_CARD_ID: hv[c.id] += 1
    for c in (p.discard or []):
        if 0 <= c.id <= MAX_CARD_ID: dv[c.id] += 1
    f.extend(hv); f.extend(dv)
    return f

def extract_state_vector(obs):
    s = obs.current
    if s is None or len(s.players) < 2: return None
    gf = [s.stadium[0].id if s.stadium else 0,
          int(s.supporterPlayed), int(s.energyAttached), int(s.retreated),
          s.firstPlayer, s.turn]
    mi = s.yourIndex
    return np.array(gf + _player_feat(s.players[mi]) + _player_feat(s.players[1-mi]), dtype=np.float32)

_ATK_DAMAGE = {}
try:
    from cg.sim import lib as _lib
    for _a in json.loads(_lib.AllAttack().decode()):
        _ATK_DAMAGE[_a["attackId"]] = _a.get("damage", 0) or 0
except Exception:
    pass

_LOSS_CTX = {
    SelectContext.DISCARD, SelectContext.TO_DECK, SelectContext.TO_DECK_BOTTOM,
    SelectContext.DISCARD_ENERGY_CARD, SelectContext.DISCARD_TOOL_CARD,
    SelectContext.DISCARD_CARD_OR_ATTACHED_CARD, SelectContext.DISCARD_ENERGY,
    SelectContext.TO_DECK_ENERGY, SelectContext.DEVOLVE,
}
_MAIN_PRI = {
    OptionType.EVOLVE: 6, OptionType.ABILITY: 5, OptionType.PLAY: 4,
    OptionType.ATTACH: 3, OptionType.ATTACK: 2, OptionType.RETREAT: 1, OptionType.END: 0,
}

def rule_pick(obs):
    sel = obs.select
    n = len(sel.option)
    k = max(getattr(sel, 'minCount', 1), 1)
    k = min(k, getattr(sel, 'maxCount', 1), n)
    try:
        st = SelectType(sel.type)
    except Exception:
        return list(range(k))
    if st == SelectType.YES_NO:
        for i, op in enumerate(sel.option):
            if op.type == OptionType.YES: return [i]
        return [0]
    if st == SelectType.COUNT:
        best_i, best = 0, -1
        for i, op in enumerate(sel.option):
            v = op.number if op.number is not None else (getattr(op, 'count', None) or 0)
            if v > best: best, best_i = v, i
        return [best_i]
    if st == SelectType.ATTACK:
        best_i, best = 0, -1
        for i, op in enumerate(sel.option):
            d = _ATK_DAMAGE.get(op.attackId, 0)
            if d > best: best, best_i = d, i
        return [best_i]
    if st == SelectType.MAIN:
        best_i, best = 0, -1
        for i, op in enumerate(sel.option):
            s = _MAIN_PRI.get(op.type, 0) * 1000
            if s > best: best, best_i = s, i
        return [best_i]
    try:
        ctx = SelectContext(sel.context)
    except Exception:
        ctx = None
    ks = sel.minCount if ctx in _LOSS_CTX else sel.maxCount
    ks = max(min(ks, sel.maxCount, n), sel.minCount)
    return list(range(min(ks, n))) if ks > 0 else list(range(k))

class _Net(nn.Module):
    def __init__(self):
        super().__init__()
        self.fc1 = nn.Linear(INPUT_DIM, 1024); self.ln1 = nn.LayerNorm(1024)
        self.fc2 = nn.Linear(1024, 512);       self.ln2 = nn.LayerNorm(512)
        self.fc3 = nn.Linear(512, MAX_ACTIONS)
    def forward(self, x):
        x = F.relu(self.ln1(self.fc1(x)))
        x = F.relu(self.ln2(self.fc2(x)))
        return self.fc3(x)

def load_net(path):
    net = _Net()
    net.load_state_dict(torch.load(path, map_location='cpu', weights_only=True))
    net.eval()
    return net

def nn_pick(net, obs, norm_mean, norm_std):
    sel = obs.select
    sv = extract_state_vector(obs)
    if sv is None: return rule_pick(obs)
    nsv = (sv - norm_mean) / (norm_std + 1e-8)
    x = torch.FloatTensor(nsv).unsqueeze(0)
    n_valid = len(sel.option)
    with torch.no_grad():
        logits = net(x)[0, :n_valid]
    return [logits.argmax().item()]

def play_one(net_a, net_b, norm_mean, norm_std, deck, seed, a_idx):
    random.seed(seed)
    obs_dict, _ = battle_start(deck, deck)
    if obs_dict is None:
        battle_finish()
        return -1
    result = -1
    turn_actions = {0: 0, 1: 0}
    last_turn    = {0: -1, 1: -1}
    for _ in range(4000):
        obs = to_observation_class(obs_dict)
        cur = obs.current
        if cur is not None and cur.result != -1:
            result = cur.result; break
        if obs.select is None:
            break
        who = cur.yourIndex if cur is not None else 0
        if cur is not None:
            if cur.turn != last_turn[who]:
                last_turn[who] = cur.turn; turn_actions[who] = 0
            turn_actions[who] += 1
        is_main = False
        try:
            is_main = SelectType(obs.select.type) == SelectType.MAIN
        except Exception:
            pass
        net = (net_a if who == a_idx else net_b)
        if net is not None and is_main and turn_actions[who] <= 40:
            obs_dict = battle_select(nn_pick(net, obs, norm_mean, norm_std))
        else:
            obs_dict = battle_select(rule_pick(obs))
    battle_finish()
    return result

def run_match(challenger_path, baseline_path, norm_path, deck, n_games, label):
    norm = np.load(norm_path)
    mean = norm['mean'].astype(np.float32)
    std  = norm['std'].astype(np.float32)
    chall = load_net(challenger_path)
    base  = load_net(baseline_path)

    wins = losses = draws = 0
    t0 = time.time()
    for g in range(n_games):
        a_idx = 0 if g % 2 == 0 else 1
        result = play_one(chall, base, mean, std, deck, seed=42+g, a_idx=a_idx)
        if result == a_idx:      wins   += 1
        elif result == 1-a_idx:  losses += 1
        else:                    draws  += 1
        if (g+1) % 100 == 0:
            elapsed = time.time() - t0
            wr = wins / (wins+losses) if (wins+losses) > 0 else 0
            print(f"  {label}: {g+1}/{n_games}  W/D/L={wins}/{draws}/{losses}  wr={wr:.1%}  {elapsed:.0f}s", flush=True)
    elapsed = time.time() - t0
    wr = wins / (wins+losses) if (wins+losses) > 0 else 0
    print(f"\n{'='*60}", flush=True)
    print(f"{label} vs baseline  ({n_games} 戦)", flush=True)
    print(f"  勝: {wins} / 引: {draws} / 負: {losses}", flush=True)
    print(f"  勝率 (引分除外): {wr:.1%}  ({wins}/{wins+losses})", flush=True)
    print(f"  所要時間: {elapsed:.0f}s", flush=True)
    print(f"{'='*60}\n", flush=True)
    return wins, draws, losses

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=1000)
    args = ap.parse_args()

    SUB = os.path.join(HERE, "..", "submission")
    deck_path    = os.path.join(SUB, "deck.csv")
    baseline_pth = os.path.join(SUB, "ptcg_baseline_model.pth")
    best_pth     = os.path.join(SUB, "ptcg_best_model.pth")
    league_pth   = os.path.join(SUB, "ptcg_league_model.pth")
    norm_path    = os.path.join(SUB, "ptcg_normalization.npz")

    with open(deck_path) as f:
        rows = f.read().split("\n")
    deck = [int(rows[i]) for i in range(60)]

    print(f"=== {args.games} 戦評価 ===\n", flush=True)

    run_match(best_pth,    baseline_pth, norm_path, deck, args.games, "ptcg_best_model   (iter150)")
    run_match(league_pth,  baseline_pth, norm_path, deck, args.games, "ptcg_league_model (学習前)")

if __name__ == "__main__":
    main()
