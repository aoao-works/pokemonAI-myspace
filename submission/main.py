import os
import random
import json

from cg.api import to_observation_class, Observation, SelectType, OptionType, SelectContext
from cg.sim import lib

_ATK_DAMAGE = {}
try:
    for a in json.loads(lib.AllAttack().decode()):
        _ATK_DAMAGE[a["attackId"]] = a.get("damage", 0) or 0
except Exception:
    _ATK_DAMAGE = {}

_STATE = {"turn": -1, "turn_actions": 0}

_MAIN_PRIORITY = {
    OptionType.EVOLVE: 6,
    OptionType.ABILITY: 5,
    OptionType.PLAY: 4,
    OptionType.ATTACH: 3,
    OptionType.ATTACK: 2,
    OptionType.RETREAT: 1,
    OptionType.END: 0,
}

_LOSS_CONTEXTS = {
    SelectContext.DISCARD, SelectContext.TO_DECK, SelectContext.TO_DECK_BOTTOM,
    SelectContext.DISCARD_ENERGY_CARD, SelectContext.DISCARD_TOOL_CARD,
    SelectContext.DISCARD_CARD_OR_ATTACHED_CARD, SelectContext.DISCARD_ENERGY,
    SelectContext.TO_DECK_ENERGY, SelectContext.DEVOLVE,
}


def read_deck_csv():
    file_path = "deck.csv"
    if not os.path.exists(file_path):
        file_path = "/kaggle_simulations/agent/" + file_path
    with open(file_path, "r") as f:
        csv = f.read().split("\n")
    return [int(csv[i]) for i in range(60)]


def _safe_default(sel):
    """Always-valid fallback: pick the first minCount (>=1) indices, no dups."""
    n = len(sel.option)
    k = max(sel.minCount, 1)
    k = min(k, sel.maxCount, n)
    return list(range(k))


def _pick_main(sel):
    best_i, best_score = 0, -1
    for i, op in enumerate(sel.option):
        base = _MAIN_PRIORITY.get(op.type, 0)
        # tie-break ATTACK options by damage
        if op.type == OptionType.ATTACK:
            dmg = _ATK_DAMAGE.get(op.attackId, 0)
            score = base * 1000 + dmg
            score = base * 1000
        if score > best_score:
            best_score, best_i = score, i
    return [best_i]


def _pick_count(sel):
    best_i, best_val = 0, -1
    for i, op in enumerate(sel.option):
        v = op.number if op.number is not None else op.count
        v = v if v is not None else 0
        if v > best_val:
            best_val, best_i = v, i
    return [best_i]


def _pick_yesno(sel):
    for i, op in enumerate(sel.option):
        if op.type == OptionType.YES:
            return [i]
    return [0]


def _pick_set(sel):
    """Generic multi-pick: grab maxCount normally, minCount when it's a loss."""
    n = len(sel.option)
    try:
        ctx = SelectContext(sel.context)
    except Exception:
        ctx = None
    if ctx in _LOSS_CONTEXTS:
        k = sel.minCount
    else:
        k = sel.maxCount
    k = max(min(k, sel.maxCount, n), sel.minCount)
    k = min(k, n)
    if k <= 0:
        return []
    return list(range(k))


def agent(obs_dict):
    obs = to_observation_class(obs_dict)

    if obs.select is None:
        return read_deck_csv()

    sel = obs.select

    try:
        cur = obs.current
        if cur is not None:
            if cur.turn != _STATE["turn"]:
                _STATE["turn"] = cur.turn
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
            if _STATE["turn_actions"] > 40:
                for i, op in enumerate(sel.option):
                    if op.type == OptionType.ATTACK:
                        return [i]
                for i, op in enumerate(sel.option):
                    if op.type == OptionType.END:
                        return [i]
            return _pick_main(sel)
        elif st == SelectType.YES_NO:
            return _pick_yesno(sel)
        elif st == SelectType.COUNT:
            return _pick_count(sel)
        elif st == SelectType.ATTACK:
            # pick highest-damage attack
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