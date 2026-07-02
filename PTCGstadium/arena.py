"""
arena.py — ローカルでエージェント同士を対戦させる対戦場。
 
各エージェントは、自分用の main.py と deck.csv を入れた「フォルダ」として用意する。
エンジンSDK(cg/)は共有で、このスクリプトと同じ場所に置く。
 
構成:
    arena/
    ├── cg/                 (エンジンSDK・共有)
    ├── arena.py            (このファイル)
    ├── play_local.py       (任意。--replay で使用)
    └── agents/
        ├── v1/  (main.py, deck.csv)
        ├── v2/  (main.py, deck.csv)
        └── ...
 
実行(これを実行してください):
    cd PTCGstadium                                            # スクリプトと同じディレクトリに移動

    #いくつかの例:
     python arena.py --p0 agents/v1 --p1 agents/v2 --games 100# 100戦・先攻後攻を入れ替え
    python arena.py --p0 agents/v1 --p1 random                # 組み込みのランダム相手
    python arena.py --p0 agents/v1 --p1 agents/v2 --replay    # 1戦目を replay.html に可視化
 
補足:
- 試合ごとに先攻・後攻を入れ替え、先攻有利を打ち消す。
- 'random' を指定した側は相手と同じデッキでプレイする(デッキではなく方策だけを比較)。
- Linux/WSL か Windows で動作する(エンジンが .so と .dll を同梱)。macOSはWSL/Docker/Kaggleで。
"""
import os
import sys
import json
import random
import argparse
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from cg.game import battle_start, battle_select, battle_finish, visualize_data
from cg.api import to_observation_class


def load_deck(path):
    with open(path, "r") as f:
        rows = f.read().split("\n")
    return [int(rows[i]) for i in range(60)]


def random_choice(obs):
    o = to_observation_class(obs)
    s = o.select
    return random.sample(range(len(s.option)), s.maxCount)


class Agent:
    """Wraps an agent: a callable choosing options + its deck + a reset hook."""
    def __init__(self, name, fn, deck, module=None):
        self.name = name
        self.fn = fn
        self.deck = deck
        self.module = module

    def reset(self):
        if self.module is not None and hasattr(self.module, "_STATE"):
            self.module._STATE.update({"turn": -1, "turn_actions": 0})


def load_agent(spec, slot):
    """spec is 'random' or a folder path containing main.py + deck.csv."""
    if spec == "random":
        return Agent("Random", random_choice, None, None)
    folder = spec if os.path.isabs(spec) else os.path.join(HERE, spec)
    main_path = os.path.join(folder, "main.py")
    deck_path = os.path.join(folder, "deck.csv")
    if not os.path.exists(main_path):
        raise SystemExit(f"main.py not found in {folder}")
    if not os.path.exists(deck_path):
        raise SystemExit(f"deck.csv not found in {folder}")
    modname = f"agent_slot{slot}"
    spec_ = importlib.util.spec_from_file_location(modname, main_path)
    mod = importlib.util.module_from_spec(spec_)
    sys.modules[modname] = mod
    spec_.loader.exec_module(mod)
    if not hasattr(mod, "agent"):
        raise SystemExit(f"{main_path} has no agent() function")
    name = os.path.basename(os.path.normpath(folder))
    return Agent(name, mod.agent, load_deck(deck_path), mod)


def play_game(agentA, agentB, deckA, deckB, seed, capture=False, max_steps=4000):
    """agentA is player 0, agentB is player 1. Returns (result, replay_or_None)."""
    random.seed(seed)
    agentA.reset(); agentB.reset()
    obs, sd = battle_start(deckA, deckB)
    if obs is None:
        return None, None
    steps = 0
    o = to_observation_class(obs)
    while True:
        o = to_observation_class(obs)
        cur = o.current
        if cur is not None and cur.result != -1:
            break
        if o.select is None:
            break
        who = cur.yourIndex
        choice = (agentA.fn if who == 0 else agentB.fn)(obs)
        obs = battle_select(choice)
        steps += 1
        if steps > max_steps:
            break
    result = o.current.result if o.current else -1
    replay = json.loads(visualize_data()) if capture else None
    battle_finish()
    return result, replay


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--p0", required=True, help="agent folder (main.py+deck.csv) or 'random'")
    ap.add_argument("--p1", required=True, help="agent folder (main.py+deck.csv) or 'random'")
    ap.add_argument("--games", type=int, default=50, help="games per matchup (split across both sides)")
    ap.add_argument("--seed", type=int, default=1000, help="base RNG seed")
    ap.add_argument("--replay", action="store_true", help="also write replay.html of the first game")
    ap.add_argument("--images-dir", default="card_images", help="card images for the replay")
    ap.add_argument("--out", default="replay.html")
    args = ap.parse_args()

    a0 = load_agent(args.p0, 0)
    a1 = load_agent(args.p1, 1)

    # resolve decks: a 'random' side borrows the other side's deck
    if a0.deck is None and a1.deck is None:
        raise SystemExit("At least one side must be a real agent folder (random needs a deck to play).")
    if a0.deck is None:
        a0.deck = a1.deck
    if a1.deck is None:
        a1.deck = a0.deck

    n = args.games
    half = n // 2
    rec = {a0.name + "#0": 0, a1.name + "#1": 0, "draw": 0, "error": 0}
    wins0 = wins1 = draws = errs = 0
    first_replay = None

    print(f"Arena: [{a0.name}] vs [{a1.name}]  —  {n} games (sides swapped)\n")
    for g in range(n):
        swap = g >= half  # second half: swap sides
        seed = args.seed + g
        cap = args.replay and g == 0
        if not swap:
            res, rp = play_game(a0, a1, a0.deck, a1.deck, seed, capture=cap)
            # res: 0 -> a0 won, 1 -> a1 won
            won0 = (res == 0); won1 = (res == 1)
            labels = (a0.name, a1.name)
        else:
            res, rp = play_game(a1, a0, a1.deck, a0.deck, seed, capture=cap)
            # res: 0 -> a1 won, 1 -> a0 won
            won0 = (res == 1); won1 = (res == 0)
            labels = (a1.name, a0.name)
        if cap and rp is not None:
            first_replay = (rp, labels, res)
        if res is None:
            errs += 1
        elif won0:
            wins0 += 1
        elif won1:
            wins1 += 1
        else:
            draws += 1

    total = wins0 + wins1 + draws
    wr0 = wins0 / total if total else 0
    print(f"  {a0.name:<16} wins: {wins0:3d}   ({wr0:.1%})")
    print(f"  {a1.name:<16} wins: {wins1:3d}   ({1-wr0 if total else 0:.1%})")
    print(f"  draws/no-result: {draws}   errors: {errs}")
    print(f"\n  => {a0.name} win rate vs {a1.name}: {wr0:.1%}  ({wins0}/{total})")

    if args.replay and first_replay is not None:
        try:
            import play_local as PL
            rp, labels, res = first_replay
            try:
                html = PL.build_html(rp, labels[0], labels[1], res, args.seed, args.images_dir)
            except TypeError:
                # older play_local.py (no --images-dir support): fall back to 5-arg form
                html = PL.build_html(rp, labels[0], labels[1], res, args.seed)
                print("  (note: update play_local.py to the latest version for card images in replays)")
            out_path = os.path.join(HERE, args.out)
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"\n  Replay of game 1 written to {out_path}")
        except Exception as e:
            print(f"\n  (replay skipped: {e})")


if __name__ == "__main__":
    main()
