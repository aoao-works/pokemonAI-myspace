#!/usr/bin/env python3
"""
train_rl_league.py — リーグ学習 (League Training) による PPO 強化学習

【コンセプト】
- 「リーグ」: 過去の自分・旧モデル・ベースラインなど複数の固定エージェントの集合
- メインエージェントは毎回ランダムに選ばれたリーグメンバーと対戦
- これにより「じゃんけん的な相性問題」を回避し、汎用的な強さを目指す
- メインのみ PPO で更新。リーグメンバーは凍結（固定重み）

実行:
    C:\\venv\\Scripts\\python train_rl_league.py [--iters N] [--games N]
"""
import os, sys, json, random, time, argparse, copy
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
# 定数
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
    EnergyType.COLORLESS: '{C}', EnergyType.GRASS: '{G}',
    EnergyType.FIRE: '{R}',     EnergyType.WATER: '{W}',
    EnergyType.LIGHTNING: '{L}', EnergyType.PSYCHIC: '{P}',
    EnergyType.FIGHTING: '{F}', EnergyType.DARKNESS: '{D}',
    EnergyType.METAL: '{M}',    EnergyType.DRAGON: '竜',
    EnergyType.RAINBOW: '{A}',  EnergyType.TEAM_ROCKET: '{Team Rocket}{Team Rocket}',
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
            'HP': c.hp, 'Retreat': c.retreatCost,
            'Type': type_str, 'Weakness': weak_str,
            'Damage': first_atk.damage if first_atk else 0,
            'Cost': len(first_atk.energies) if first_atk else 0,
            'is_ex': 1 if (c.ex or c.megaEx) else 0,
            'basic': c.basic,
        }
    return d

_card_dict = _build_card_dict()

# ============================================================
# 特徴量抽出
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
    ci = _card_dict.get(poke.id, {})
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
        + _one_hot(ci.get('Type', 'None'), TYPE_VOCAB)
        + _one_hot(ci.get('Weakness', 'None'), WEAKNESS_VOCAB)
        + en_type_counts
    )

def _player_feat(p):
    features = []
    features.extend(_pokemon_feat(p.active[0] if p.active else None))
    bench = p.bench or []
    for i in range(5):
        features.extend(_pokemon_feat(bench[i] if i < len(bench) else None))
    features.extend([int(p.poisoned), int(p.burned), int(p.asleep), int(p.paralyzed), int(p.confused)])
    prize_count = sum(1 for pr in p.prize if pr is not None)
    features.extend([p.handCount, p.deckCount, prize_count])
    hand_v = [0] * (MAX_CARD_ID + 1)
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
    global_f = [stadium_id, int(state.supporterPlayed), int(state.energyAttached),
                int(state.retreated), state.firstPlayer, state.turn]
    my_idx = state.yourIndex
    return np.array(global_f + _player_feat(state.players[my_idx])
                    + _player_feat(state.players[1 - my_idx]), dtype=np.float32)

# ============================================================
# ルールベースフォールバック
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
    def __init__(self):
        super().__init__()
        self.fc1    = nn.Linear(INPUT_DIM, 1024)
        self.ln1    = nn.LayerNorm(1024)
        self.fc2    = nn.Linear(1024, 512)
        self.ln2    = nn.LayerNorm(512)
        self.policy = nn.Linear(512, MAX_ACTIONS)
        self.value  = nn.Linear(512, 1)

    def _trunk(self, x):
        return F.relu(self.ln2(self.fc2(F.relu(self.ln1(self.fc1(x))))))

    def forward(self, x):
        h = self._trunk(x)
        return self.policy(h), self.value(h).squeeze(-1)


def load_ac_from_file(path):
    """fc3-format ファイル (submission 互換) から ActorCritic を読み込む。"""
    ac  = ActorCritic()
    src = torch.load(path, map_location='cpu', weights_only=True)
    dst = ac.state_dict()
    mapping = {
        'fc1.weight': 'fc1.weight', 'fc1.bias': 'fc1.bias',
        'ln1.weight': 'ln1.weight', 'ln1.bias': 'ln1.bias',
        'fc2.weight': 'fc2.weight', 'fc2.bias': 'fc2.bias',
        'ln2.weight': 'ln2.weight', 'ln2.bias': 'ln2.bias',
        'fc3.weight': 'policy.weight', 'fc3.bias': 'policy.bias',
    }
    for src_k, dst_k in mapping.items():
        if src_k in src and dst_k in dst:
            dst[dst_k] = src[src_k]
    ac.load_state_dict(dst)
    ac.eval()
    return ac


def save_policy(model, out_path):
    """submission/main.py 互換フォーマット (fc3 キー) で保存。"""
    torch.save({
        'fc1.weight': model.fc1.weight.data, 'fc1.bias': model.fc1.bias.data,
        'ln1.weight': model.ln1.weight.data, 'ln1.bias': model.ln1.bias.data,
        'fc2.weight': model.fc2.weight.data, 'fc2.bias': model.fc2.bias.data,
        'ln2.weight': model.ln2.weight.data, 'ln2.bias': model.ln2.bias.data,
        'fc3.weight': model.policy.weight.data, 'fc3.bias': model.policy.bias.data,
    }, out_path)

# ============================================================
# リーグ (League)
# ============================================================
class League:
    """
    固定エージェントの集合。メインエージェントはここから相手を選んで対戦する。
    古い順に削除するが、最初の2つ (baseline, 初期RL) は常に保持する錨として残す。
    """
    def __init__(self, max_size: int = 20):
        self.members: list[tuple[str, dict]] = []  # (name, ac_state_dict)
        self.max_size = max_size
        self.anchor_count = 0  # 錨として保護するメンバー数

    def add(self, name: str, model: ActorCritic, anchor: bool = False):
        state = {k: v.clone().cpu() for k, v in model.state_dict().items()}
        self.members.append((name, state))
        if anchor:
            self.anchor_count += 1
        # 上限を超えたら錨より後ろの最古のものを削除
        while len(self.members) > self.max_size:
            self.members.pop(self.anchor_count)

    def sample(self) -> tuple[str, ActorCritic]:
        name, state = random.choice(self.members)
        ac = ActorCritic()
        ac.load_state_dict(state)
        ac.eval()
        return name, ac

    def __len__(self):
        return len(self.members)

    def names(self):
        return [n for n, _ in self.members]

# ============================================================
# ゲーム収集 (メインのみ学習)
# ============================================================
def collect_league_game(
    main_model:  ActorCritic,
    opp_model:   ActorCritic,
    norm_mean:   np.ndarray,
    norm_std:    np.ndarray,
    deck:        list,
    seed:        int,
    main_idx:    int,           # 0 or 1: メインが担当するプレイヤー番号
) -> tuple[list, float]:
    """
    メインエージェントと固定相手 (opp_model) の1ゲームを実行。
    メインの遷移のみ収集し、(transitions, reward) を返す。
    reward: メインが勝つ=+1, 負け=-1, 引き分け=0
    """
    random.seed(seed)
    transitions = []
    turn_actions = {0: 0, 1: 0}
    last_turn    = {0: -1, 1: -1}

    obs_dict, _ = battle_start(deck, deck)
    if obs_dict is None:
        return [], 0.0

    main_model.eval()
    result = -1

    for _step in range(4000):
        obs = to_observation_class(obs_dict)
        cur = obs.current

        if cur is not None and cur.result != -1:
            result = cur.result
            break
        if obs.select is None:
            break

        sel = obs.select
        who = cur.yourIndex if cur is not None else 0

        if cur is not None:
            if cur.turn != last_turn[who]:
                last_turn[who]    = cur.turn
                turn_actions[who] = 0
            turn_actions[who] += 1

        is_main_sel = False
        try:
            is_main_sel = (SelectType(sel.type) == SelectType.MAIN)
        except Exception:
            pass

        if who == main_idx:
            # ---- メインエージェントのターン ----
            if is_main_sel and turn_actions[who] <= 40:
                sv = extract_state_vector(obs)
                if sv is not None:
                    norm_sv = (sv - norm_mean) / (norm_std + 1e-8)
                    x = torch.FloatTensor(norm_sv).unsqueeze(0)
                    n_valid = len(sel.option)
                    with torch.no_grad():
                        logits, v_est = main_model(x)
                        mask = torch.zeros(MAX_ACTIONS, dtype=torch.bool)
                        mask[n_valid:] = True
                        logits_m = logits[0].masked_fill(mask, -1e9).unsqueeze(0)
                        dist   = torch.distributions.Categorical(logits=logits_m)
                        action = dist.sample()
                        lp     = dist.log_prob(action)
                    a_idx = action.item()
                    transitions.append((norm_sv.copy(), a_idx, lp.item(), v_est.item(), n_valid))
                    obs_dict = battle_select([a_idx])
                    continue
            obs_dict = battle_select(rule_pick(obs))

        else:
            # ---- 相手エージェントのターン (固定・貪欲) ----
            if is_main_sel and turn_actions[who] <= 40:
                sv = extract_state_vector(obs)
                if sv is not None:
                    norm_sv = (sv - norm_mean) / (norm_std + 1e-8)
                    x = torch.FloatTensor(norm_sv).unsqueeze(0)
                    n_valid = len(sel.option)
                    with torch.no_grad():
                        logits, _ = opp_model(x)
                        a_idx = logits[0, :n_valid].argmax().item()
                    obs_dict = battle_select([a_idx])
                    continue
            obs_dict = battle_select(rule_pick(obs))

    battle_finish()

    if result == main_idx:
        reward = 1.0
    elif result == 1 - main_idx:
        reward = -1.0
    else:
        reward = 0.0

    return transitions, reward

# ============================================================
# GAE
# ============================================================
def compute_gae(transitions, final_reward, gamma=0.99, lam=0.95):
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
    return advantages.tolist(), (advantages + values).tolist()

# ============================================================
# PPO アップデート
# ============================================================
def ppo_update(model, optimizer, all_trans, clip_eps=0.1, ppo_epochs=4, batch_size=256):
    if not all_trans:
        return 0.0, 0.0
    states      = torch.FloatTensor(np.array([t[0] for t in all_trans]))
    actions     = torch.LongTensor([t[1] for t in all_trans])
    old_lps     = torch.FloatTensor([t[2] for t in all_trans])
    advantages  = torch.FloatTensor([t[5] for t in all_trans])
    returns     = torch.FloatTensor([t[6] for t in all_trans])
    valid_counts = [t[4] for t in all_trans]
    advantages  = (advantages - advantages.mean()) / (advantages.std() + 1e-8)
    model.train()
    total_p = total_v = n_upd = 0
    for _ in range(ppo_epochs):
        perm = torch.randperm(len(states))
        for start in range(0, len(states), batch_size):
            b = perm[start: start + batch_size]
            b_states, b_actions = states[b], actions[b]
            b_old_lps, b_adv   = old_lps[b], advantages[b]
            b_ret               = returns[b]
            b_vc                = [valid_counts[i] for i in b.tolist()]
            logits, values = model(b_states)
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
            total_p += p_loss.item()
            total_v += v_loss.item()
            n_upd   += 1
    n = max(n_upd, 1)
    return total_p / n, total_v / n

# ============================================================
# メイン
# ============================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iters",       type=int,   default=300)
    ap.add_argument("--games",       type=int,   default=16,  help="1イテレーションあたりのゲーム数")
    ap.add_argument("--lr",          type=float, default=5e-5)
    ap.add_argument("--gamma",       type=float, default=0.99)
    ap.add_argument("--lam",         type=float, default=0.95)
    ap.add_argument("--clip",        type=float, default=0.1)
    ap.add_argument("--epochs",      type=int,   default=4)
    ap.add_argument("--batch",       type=int,   default=256)
    ap.add_argument("--league-size", type=int,   default=20)
    ap.add_argument("--add-every",   type=int,   default=25,  help="何イテレーションごとにリーグへ追加するか")
    ap.add_argument("--save-every",  type=int,   default=25)
    ap.add_argument("--seed",        type=int,   default=100)
    args = ap.parse_args()

    # ---- 各種パス ----
    SUBMISSION = os.path.join(HERE, "..", "submission")
    baseline_path = os.path.join(SUBMISSION, "ptcg_baseline_model.pth")
    rl_path       = os.path.join(SUBMISSION, "ptcg_rl_model.pth")
    out_path      = os.path.join(SUBMISSION, "ptcg_league_model.pth")
    log_path      = os.path.join(HERE, "train_league_log.txt")

    deck = []
    with open(os.path.join(SUBMISSION, "deck.csv"), "r") as f:
        rows = f.read().split("\n")
    deck = [int(rows[i]) for i in range(60)]

    norm = np.load(os.path.join(SUBMISSION, "ptcg_normalization.npz"))
    norm_mean = norm['mean'].astype(np.float32)
    norm_std  = norm['std'].astype(np.float32)

    log_file = open(log_path, "w", encoding="utf-8", buffering=1)
    def log(msg):
        print(msg, flush=True)
        print(msg, file=log_file, flush=True)

    # ---- メインモデル初期化 ----
    main_model = load_ac_from_file(
        rl_path if os.path.exists(rl_path) else baseline_path
    )
    start_name = "rl" if os.path.exists(rl_path) else "baseline"
    log(f"メインモデル初期化: {start_name}")

    optimizer = torch.optim.Adam(main_model.parameters(), lr=args.lr)

    # ---- リーグ初期化 ----
    league = League(max_size=args.league_size)

    # 錨1: 模倣学習ベースラインを必ず追加
    if os.path.exists(baseline_path):
        league.add("baseline", load_ac_from_file(baseline_path), anchor=True)
        log("リーグ追加 (錨): baseline")

    # 錨2: RL モデルがあれば追加
    if os.path.exists(rl_path):
        league.add("rl_v0", load_ac_from_file(rl_path), anchor=True)
        log("リーグ追加 (錨): rl_v0")

    # リーグが空なら自分自身を錨として追加
    if len(league) == 0:
        league.add("init", main_model, anchor=True)
        log("リーグ追加 (錨): init (自分自身)")

    log(f"\n=== PPO リーグ学習 ===")
    log(f"  イテレーション: {args.iters}  ゲーム/iter: {args.games}")
    log(f"  LR={args.lr}  clip={args.clip}  league_size={args.league_size}")
    log(f"  初期リーグメンバー: {league.names()}")
    log(f"  出力: {out_path}\n")

    total_games  = 0
    win_history  = []
    opp_history  = []

    for it in range(1, args.iters + 1):
        t0 = time.time()
        all_trans = []
        wins = losses = draws = 0

        # 1イテレーションのゲーム収集
        for g in range(args.games):
            opp_name, opp_model = league.sample()
            # 先攻/後攻を交互に
            main_idx = 0 if g % 2 == 0 else 1
            seed = args.seed + total_games + g

            trans, reward = collect_league_game(
                main_model, opp_model, norm_mean, norm_std, deck, seed, main_idx
            )

            if reward > 0:
                wins   += 1
            elif reward < 0:
                losses += 1
            else:
                draws  += 1

            adv, ret = compute_gae(trans, reward, args.gamma, args.lam)
            for i, t in enumerate(trans):
                all_trans.append((*t, adv[i], ret[i]))

            opp_history.append(opp_name)

        total_games += args.games

        # PPO 更新
        p_loss, v_loss = ppo_update(
            main_model, optimizer, all_trans,
            args.clip, args.epochs, args.batch,
        )

        elapsed  = time.time() - t0
        win_rate = wins / max(wins + losses, 1)
        win_history.append(win_rate)
        recent_wr = sum(win_history[-10:]) / min(len(win_history), 10)

        # 直近の対戦相手の分布
        recent_opps = opp_history[-args.games:]
        opp_counts  = {}
        for name in recent_opps:
            opp_counts[name] = opp_counts.get(name, 0) + 1
        opp_str = " ".join(f"{n}:{c}" for n, c in sorted(opp_counts.items()))

        log(
            f"[{it:3d}/{args.iters}] "
            f"games={total_games:5d}  "
            f"W/D/L={wins}/{draws}/{losses}  "
            f"wr={win_rate:.0%}(直近{recent_wr:.0%})  "
            f"trans={len(all_trans):4d}  "
            f"p={p_loss:.4f}  v={v_loss:.4f}  "
            f"opps=[{opp_str}]  "
            f"{elapsed:.1f}s"
        )

        # リーグへの追加
        if it % args.add_every == 0:
            snap_name = f"league_iter{it}"
            league.add(snap_name, main_model)
            log(f"  => リーグ追加: {snap_name}  (現在 {len(league)} メンバー: {league.names()})")

        # チェックポイント保存
        if it % args.save_every == 0:
            save_policy(main_model, out_path)
            log(f"  => チェックポイント保存: {out_path}")

    save_policy(main_model, out_path)
    log(f"\n学習完了。最終モデル: {out_path}")
    log(f"提出に使う場合は以下を実行:")
    log(f"  copy submission\\ptcg_league_model.pth submission\\ptcg_rl_model.pth")
    log_file.close()


if __name__ == "__main__":
    main()
