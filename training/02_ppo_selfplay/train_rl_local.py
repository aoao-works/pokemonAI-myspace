#!/usr/bin/env python3
"""
train_rl_local.py — PPO self-play RL training for PTCG AI (local CPU).

Run with:
    C:\\venv\\Scripts\\python train_rl_local.py [--iters N] [--games N]

Output:
    submission/ptcg_rl_model.pth  (submission/main.py と互換フォーマット)

学習が終わったら submission/ptcg_baseline_model.pth に上書きコピーすれば
既存エージェントがそのまま新モデルを使う。
"""
import os
import sys
import json
import random
import time
import argparse
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

# ============================================================
# 定数 (submission/main.py と完全に一致させること)
# ============================================================
MAX_CARD_ID = 1267
MAX_ACTIONS = 256
INPUT_DIM   = 5658

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
# カードデータ
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

_card_dict = _build_card_dict()

# ============================================================
# 特徴量抽出 (submission/main.py と同一ロジック)
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

def extract_state_vector(obs):
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
# ルールベースフォールバック (MAIN以外 + MAIN緊急時)
# ============================================================
_ATK_DAMAGE = {}
try:
    from cg.sim import lib as _lib
    for _a in json.loads(_lib.AllAttack().decode()):
        _ATK_DAMAGE[_a["attackId"]] = _a.get("damage", 0) or 0
except Exception:
    pass

_LOSS_CONTEXTS = {
    SelectContext.DISCARD, SelectContext.TO_DECK, SelectContext.TO_DECK_BOTTOM,
    SelectContext.DISCARD_ENERGY_CARD, SelectContext.DISCARD_TOOL_CARD,
    SelectContext.DISCARD_CARD_OR_ATTACHED_CARD, SelectContext.DISCARD_ENERGY,
    SelectContext.TO_DECK_ENERGY, SelectContext.DEVOLVE,
}

_MAIN_PRIORITY = {
    OptionType.EVOLVE:  6,
    OptionType.ABILITY: 5,
    OptionType.PLAY:    4,
    OptionType.ATTACH:  3,
    OptionType.ATTACK:  2,
    OptionType.RETREAT: 1,
    OptionType.END:     0,
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
            if op.type == OptionType.YES:
                return [i]
        return [0]

    if st == SelectType.COUNT:
        best_i, best_val = 0, -1
        for i, op in enumerate(sel.option):
            v = op.number if op.number is not None else (getattr(op, 'count', None) or 0)
            if v > best_val:
                best_val, best_i = v, i
        return [best_i]

    if st == SelectType.ATTACK:
        best_i, best = 0, -1
        for i, op in enumerate(sel.option):
            d = _ATK_DAMAGE.get(op.attackId, 0)
            if d > best:
                best, best_i = d, i
        return [best_i]

    if st == SelectType.MAIN:
        best_i, best_score = 0, -1
        for i, op in enumerate(sel.option):
            score = _MAIN_PRIORITY.get(op.type, 0) * 1000
            if score > best_score:
                best_score, best_i = score, i
        return [best_i]

    try:
        ctx = SelectContext(sel.context)
    except Exception:
        ctx = None
    k_set = sel.minCount if ctx in _LOSS_CONTEXTS else sel.maxCount
    k_set = max(min(k_set, sel.maxCount, n), sel.minCount)
    return list(range(min(k_set, n))) if k_set > 0 else list(range(k))

# ============================================================
# Actor-Critic モデル
# ============================================================
class ActorCritic(nn.Module):
    """
    既存 _Net と同じ trunk を共有し、policy ヘッドと value ヘッドを持つ。
    保存時は fc3 キー名で policy 重みを書き出すため submission/main.py と互換。
    """
    def __init__(self):
        super().__init__()
        self.fc1    = nn.Linear(INPUT_DIM, 1024)
        self.ln1    = nn.LayerNorm(1024)
        self.fc2    = nn.Linear(1024, 512)
        self.ln2    = nn.LayerNorm(512)
        self.policy = nn.Linear(512, MAX_ACTIONS)
        self.value  = nn.Linear(512, 1)

    def _trunk(self, x):
        x = F.relu(self.ln1(self.fc1(x)))
        return F.relu(self.ln2(self.fc2(x)))

    def forward(self, x):
        h = self._trunk(x)
        return self.policy(h), self.value(h).squeeze(-1)

def load_pretrained(model, model_path):
    """既存 ptcg_baseline_model.pth を trunk + policy に読み込む。"""
    src = torch.load(model_path, map_location='cpu', weights_only=True)
    dst = model.state_dict()
    mapping = {
        'fc1.weight': 'fc1.weight', 'fc1.bias': 'fc1.bias',
        'ln1.weight': 'ln1.weight', 'ln1.bias': 'ln1.bias',
        'fc2.weight': 'fc2.weight', 'fc2.bias': 'fc2.bias',
        'ln2.weight': 'ln2.weight', 'ln2.bias': 'ln2.bias',
        'fc3.weight': 'policy.weight', 'fc3.bias': 'policy.bias',
    }
    loaded = 0
    for src_key, dst_key in mapping.items():
        if src_key in src and dst_key in dst:
            dst[dst_key] = src[src_key]
            loaded += 1
    model.load_state_dict(dst)
    return loaded

def save_policy(model, out_path):
    """submission/main.py (_Net) と互換フォーマットで保存。"""
    torch.save({
        'fc1.weight': model.fc1.weight.data,
        'fc1.bias':   model.fc1.bias.data,
        'ln1.weight': model.ln1.weight.data,
        'ln1.bias':   model.ln1.bias.data,
        'fc2.weight': model.fc2.weight.data,
        'fc2.bias':   model.fc2.bias.data,
        'ln2.weight': model.ln2.weight.data,
        'ln2.bias':   model.ln2.bias.data,
        'fc3.weight': model.policy.weight.data,
        'fc3.bias':   model.policy.bias.data,
    }, out_path)

# ============================================================
# デッキ読み込み
# ============================================================
def load_deck():
    path = os.path.join(HERE, "submission", "deck.csv")
    with open(path, "r") as f:
        rows = f.read().split("\n")
    return [int(rows[i]) for i in range(60)]

# ============================================================
# 自己対戦ゲーム収集
# ============================================================
# 各遷移のフォーマット: (norm_sv, action, log_prob, value_est, n_valid)
Transition = tuple  # (np.ndarray, int, float, float, int)

def collect_game(
    model: ActorCritic,
    norm_mean: np.ndarray,
    norm_std: np.ndarray,
    deck: list,
    seed: int,
) -> tuple[list[Transition], list[Transition], int]:
    """
    自己対戦を1ゲーム実行し、両プレイヤーの MAIN 選択遷移を収集する。

    Returns:
        (trans_p0, trans_p1, result)
        result: 0=p0勝ち, 1=p1勝ち, 2=引き分け, -1=エラー
    """
    random.seed(seed)
    trans: dict[int, list[Transition]] = {0: [], 1: []}
    turn_actions: dict[int, int] = {0: 0, 1: 0}
    last_turn:    dict[int, int] = {0: -1, 1: -1}

    obs_dict, _ = battle_start(deck, deck)
    if obs_dict is None:
        return [], [], -1

    model.eval()
    result = -1

    for _step in range(4000):
        obs = to_observation_class(obs_dict)
        cur = obs.current

        if cur is not None and cur.result != -1:
            result = cur.result
            break
        if obs.select is None:
            break

        sel  = obs.select
        who  = cur.yourIndex if cur is not None else 0

        # 無限ループガード
        if cur is not None:
            if cur.turn != last_turn[who]:
                last_turn[who]    = cur.turn
                turn_actions[who] = 0
            turn_actions[who] += 1

        is_main = False
        try:
            is_main = (SelectType(sel.type) == SelectType.MAIN)
        except Exception:
            pass

        # MAIN かつ状態ベクトルが取れる場合 → NN でサンプリング
        if is_main and turn_actions[who] <= 40:
            sv = extract_state_vector(obs)
            if sv is not None:
                norm_sv = (sv - norm_mean) / (norm_std + 1e-8)
                x       = torch.FloatTensor(norm_sv).unsqueeze(0)
                n_valid = len(sel.option)

                with torch.no_grad():
                    logits, v_est = model(x)
                    mask = torch.zeros(MAX_ACTIONS, dtype=torch.bool)
                    mask[n_valid:] = True
                    logits = logits[0].masked_fill(mask, -1e9).unsqueeze(0)
                    dist   = torch.distributions.Categorical(logits=logits)
                    action = dist.sample()
                    lp     = dist.log_prob(action)

                a_idx = action.item()
                trans[who].append((norm_sv.copy(), a_idx, lp.item(), v_est.item(), n_valid))
                obs_dict = battle_select([a_idx])
                continue

        # それ以外 → ルールベース
        obs_dict = battle_select(rule_pick(obs))

    battle_finish()
    return trans[0], trans[1], result

# ============================================================
# GAE (Generalized Advantage Estimation)
# ============================================================
def compute_gae(
    transitions: list[Transition],
    final_reward: float,
    gamma: float = 0.99,
    lam: float   = 0.95,
) -> tuple[list[float], list[float]]:
    """
    疎報酬用 GAE。中間報酬=0、最終ステップのみ final_reward。
    Returns: (advantages, returns)
    """
    n = len(transitions)
    if n == 0:
        return [], []

    values = np.array([t[3] for t in transitions], dtype=np.float32)
    advantages = np.zeros(n, dtype=np.float32)
    last_adv = 0.0

    for t in reversed(range(n)):
        reward  = final_reward if t == n - 1 else 0.0
        is_last = (t == n - 1)
        next_v  = 0.0 if is_last else values[t + 1]
        delta   = reward + gamma * next_v - values[t]
        last_adv = delta + gamma * lam * (0.0 if is_last else last_adv)
        advantages[t] = last_adv

    returns = advantages + values
    return advantages.tolist(), returns.tolist()

# ============================================================
# PPO アップデート
# ============================================================
def ppo_update(
    model:      ActorCritic,
    optimizer:  torch.optim.Optimizer,
    all_trans:  list,          # (sv, action, lp, value, n_valid, advantage, return)
    clip_eps:   float = 0.2,
    ppo_epochs: int   = 4,
    batch_size: int   = 512,
) -> tuple[float, float]:
    if not all_trans:
        return 0.0, 0.0

    states      = torch.FloatTensor(np.array([t[0] for t in all_trans]))
    actions     = torch.LongTensor([t[1] for t in all_trans])
    old_lps     = torch.FloatTensor([t[2] for t in all_trans])
    advantages  = torch.FloatTensor([t[5] for t in all_trans])
    returns     = torch.FloatTensor([t[6] for t in all_trans])
    valid_counts = [t[4] for t in all_trans]

    advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)

    model.train()
    total_p_loss = total_v_loss = n_updates = 0

    for _ in range(ppo_epochs):
        perm = torch.randperm(len(states))
        for start in range(0, len(states), batch_size):
            b = perm[start: start + batch_size]
            b_states  = states[b]
            b_actions = actions[b]
            b_old_lps = old_lps[b]
            b_adv     = advantages[b]
            b_ret     = returns[b]
            b_vc      = [valid_counts[i] for i in b.tolist()]

            logits, values = model(b_states)

            # バッチ内で各サンプルの無効アクションをマスク
            for i, vc in enumerate(b_vc):
                if vc < MAX_ACTIONS:
                    logits[i, vc:] = -1e9

            dist      = torch.distributions.Categorical(logits=logits)
            log_probs = dist.log_prob(b_actions)
            entropy   = dist.entropy().mean()

            ratio  = (log_probs - b_old_lps).exp()
            surr1  = ratio * b_adv
            surr2  = ratio.clamp(1 - clip_eps, 1 + clip_eps) * b_adv
            p_loss = -torch.min(surr1, surr2).mean()
            v_loss = F.mse_loss(values, b_ret)
            loss   = p_loss + 0.5 * v_loss - 0.01 * entropy

            optimizer.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 0.5)
            optimizer.step()

            total_p_loss += p_loss.item()
            total_v_loss += v_loss.item()
            n_updates    += 1

    n = max(n_updates, 1)
    return total_p_loss / n, total_v_loss / n

# ============================================================
# メインループ
# ============================================================
def main():
    ap = argparse.ArgumentParser(description="PPO self-play RL for PTCG")
    ap.add_argument("--iters",  type=int, default=100,  help="学習イテレーション数")
    ap.add_argument("--games",  type=int, default=10,   help="1イテレーションあたりのゲーム数")
    ap.add_argument("--lr",     type=float, default=1e-4)
    ap.add_argument("--gamma",  type=float, default=0.99)
    ap.add_argument("--lam",    type=float, default=0.95)
    ap.add_argument("--clip",   type=float, default=0.2)
    ap.add_argument("--epochs", type=int,   default=4)
    ap.add_argument("--batch",  type=int,   default=512)
    ap.add_argument("--save-every", type=int, default=10)
    ap.add_argument("--seed",   type=int,   default=42)
    args = ap.parse_args()

    deck      = load_deck()
    norm_path = os.path.join(HERE, "submission", "ptcg_normalization.npz")
    norm      = np.load(norm_path)
    norm_mean = norm['mean'].astype(np.float32)
    norm_std  = norm['std'].astype(np.float32)

    model = ActorCritic()
    model_path = os.path.join(HERE, "submission", "ptcg_baseline_model.pth")
    if os.path.exists(model_path):
        n = load_pretrained(model, model_path)
        print(f"事前学習モデルを読み込みました ({n}/10 層)")
    else:
        print("事前学習モデルなし → ランダム初期化")

    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)
    out_path  = os.path.join(HERE, "submission", "ptcg_rl_model.pth")

    log_path = os.path.join(HERE, "train_rl_log.txt")
    log_file = open(log_path, "w", encoding="utf-8", buffering=1)

    def log(msg):
        print(msg, flush=True)
        print(msg, file=log_file, flush=True)

    log(f"\n=== PPO 自己対戦 強化学習 ===")
    log(f"  イテレーション: {args.iters}  ゲーム/iter: {args.games}")
    log(f"  LR={args.lr}  gamma={args.gamma}  lam={args.lam}  clip={args.clip}")
    log(f"  出力: {out_path}\n")

    total_games = 0
    win_history = []

    for it in range(1, args.iters + 1):
        t0 = time.time()
        all_trans = []
        wins = draws = losses = 0

        for g in range(args.games):
            seed = args.seed + total_games + g
            tp0, tp1, result = collect_game(model, norm_mean, norm_std, deck, seed)

            if result == 0:
                r0, r1 = 1.0, -1.0; wins   += 1
            elif result == 1:
                r0, r1 = -1.0, 1.0; losses += 1
            else:
                r0, r1 = 0.0, 0.0;  draws  += 1

            adv0, ret0 = compute_gae(tp0, r0, args.gamma, args.lam)
            adv1, ret1 = compute_gae(tp1, r1, args.gamma, args.lam)

            for i, t in enumerate(tp0):
                all_trans.append((*t, adv0[i], ret0[i]))
            for i, t in enumerate(tp1):
                all_trans.append((*t, adv1[i], ret1[i]))

        total_games += args.games

        p_loss, v_loss = ppo_update(
            model, optimizer, all_trans,
            args.clip, args.epochs, args.batch,
        )

        elapsed = time.time() - t0
        win_rate = wins / max(wins + losses, 1)
        win_history.append(win_rate)
        recent_wr = sum(win_history[-10:]) / min(len(win_history), 10)

        total_trans = len(all_trans)
        log(
            f"[{it:3d}/{args.iters}] "
            f"games={total_games:5d}  "
            f"W/D/L={wins}/{draws}/{losses}  "
            f"wr={win_rate:.0%}(直近{recent_wr:.0%})  "
            f"trans={total_trans:4d}  "
            f"p_loss={p_loss:.4f}  v_loss={v_loss:.4f}  "
            f"{elapsed:.1f}s"
        )

        if it % args.save_every == 0:
            save_policy(model, out_path)
            log(f"  => チェックポイント保存: {out_path}")

    save_policy(model, out_path)
    log(f"\n学習完了。最終モデル保存: {out_path}")
    log(f"提出に使う場合は以下を実行:")
    log(f"  copy submission\\ptcg_rl_model.pth submission\\ptcg_baseline_model.pth")
    log_file.close()


if __name__ == "__main__":
    main()
