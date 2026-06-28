#!/usr/bin/env python3
"""
train_rl_best.py — 3時間版・高品質リーグ学習

改善点 (vs train_rl_league.py):
  1. KL ペナルティ: baseline モデルから大きく逸脱しないよう正則化
  2. 定期評価: 50iter ごとに baseline と 20 戦して実力を数値化
  3. ベストモデル保存: 評価 win rate が過去最高なら即保存
  4. コサイン LR スケジュール: 後半は低 LR で安定収束
  5. 3 つの錨: baseline / rl_v0 / league (現ベスト) を全員初期リーグに追加

実行:
    C:\\venv\\Scripts\\python train_rl_best.py

目安所要時間: ~3時間 (650 iter × 24 games)
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
    EnergyType.COLORLESS: '{C}', EnergyType.GRASS: '{G}', EnergyType.FIRE: '{R}',
    EnergyType.WATER: '{W}', EnergyType.LIGHTNING: '{L}', EnergyType.PSYCHIC: '{P}',
    EnergyType.FIGHTING: '{F}', EnergyType.DARKNESS: '{D}', EnergyType.METAL: '{M}',
    EnergyType.DRAGON: '竜', EnergyType.RAINBOW: '{A}',
    EnergyType.TEAM_ROCKET: '{Team Rocket}{Team Rocket}',
}

# ============================================================
# カードデータ・特徴量
# ============================================================
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
    if val in vocab:
        v[vocab.index(val)] = 1
    return v

def _pokemon_feat(poke):
    empty = [0] * (7 + 2 + len(TYPE_VOCAB) + len(WEAKNESS_VOCAB) + len(TYPE_VOCAB))
    if poke is None:
        return empty
    ci = _card_dict.get(poke.id, {})
    tool_id = poke.tools[0].id if poke.tools else 0
    en_tc = [0] * len(TYPE_VOCAB)
    for ec in (poke.energyCards or []):
        et = _card_dict.get(ec.id, {}).get('Type', 'None')
        if et in TYPE_VOCAB:
            en_tc[TYPE_VOCAB.index(et)] += 1
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
    if s is None or len(s.players) < 2:
        return None
    gf = [s.stadium[0].id if s.stadium else 0,
          int(s.supporterPlayed), int(s.energyAttached), int(s.retreated),
          s.firstPlayer, s.turn]
    mi = s.yourIndex
    return np.array(gf + _player_feat(s.players[mi]) + _player_feat(s.players[1-mi]),
                    dtype=np.float32)

# ============================================================
# ルールベース
# ============================================================
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
            if op.type == OptionType.YES:
                return [i]
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

# ============================================================
# Actor-Critic
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
    """fc3-format → ActorCritic"""
    ac  = ActorCritic()
    src = torch.load(path, map_location='cpu', weights_only=True)
    dst = ac.state_dict()
    for sk, dk in [('fc1.weight','fc1.weight'),('fc1.bias','fc1.bias'),
                   ('ln1.weight','ln1.weight'),('ln1.bias','ln1.bias'),
                   ('fc2.weight','fc2.weight'),('fc2.bias','fc2.bias'),
                   ('ln2.weight','ln2.weight'),('ln2.bias','ln2.bias'),
                   ('fc3.weight','policy.weight'),('fc3.bias','policy.bias')]:
        if sk in src and dk in dst:
            dst[dk] = src[sk]
    ac.load_state_dict(dst)
    ac.eval()
    return ac


def save_policy(model, out_path):
    torch.save({
        'fc1.weight': model.fc1.weight.data,   'fc1.bias': model.fc1.bias.data,
        'ln1.weight': model.ln1.weight.data,   'ln1.bias': model.ln1.bias.data,
        'fc2.weight': model.fc2.weight.data,   'fc2.bias': model.fc2.bias.data,
        'ln2.weight': model.ln2.weight.data,   'ln2.bias': model.ln2.bias.data,
        'fc3.weight': model.policy.weight.data, 'fc3.bias': model.policy.bias.data,
    }, out_path)

# ============================================================
# リーグ
# ============================================================
class League:
    def __init__(self, max_size=25):
        self.members: list[tuple[str, dict]] = []
        self.max_size = max_size
        self.anchor_count = 0

    def add(self, name, model, anchor=False):
        state = {k: v.clone().cpu() for k, v in model.state_dict().items()}
        self.members.append((name, state))
        if anchor:
            self.anchor_count += 1
        while len(self.members) > self.max_size:
            self.members.pop(self.anchor_count)

    def sample(self):
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
# ゲーム収集
# ============================================================
def collect_league_game(main_model, opp_model, norm_mean, norm_std, deck, seed, main_idx):
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
            result = cur.result; break
        if obs.select is None:
            break

        sel = obs.select
        who = cur.yourIndex if cur is not None else 0

        if cur is not None:
            if cur.turn != last_turn[who]:
                last_turn[who] = cur.turn; turn_actions[who] = 0
            turn_actions[who] += 1

        is_main_sel = False
        try:
            is_main_sel = (SelectType(sel.type) == SelectType.MAIN)
        except Exception:
            pass

        if who == main_idx:
            if is_main_sel and turn_actions[who] <= 40:
                sv = extract_state_vector(obs)
                if sv is not None:
                    nsv = (sv - norm_mean) / (norm_std + 1e-8)
                    x = torch.FloatTensor(nsv).unsqueeze(0)
                    n_valid = len(sel.option)
                    with torch.no_grad():
                        logits, v_est = main_model(x)
                        mask = torch.zeros(MAX_ACTIONS, dtype=torch.bool)
                        mask[n_valid:] = True
                        lm = logits[0].masked_fill(mask, -1e9).unsqueeze(0)
                        dist = torch.distributions.Categorical(logits=lm)
                        action = dist.sample()
                        lp = dist.log_prob(action)
                    a_idx = action.item()
                    transitions.append((nsv.copy(), a_idx, lp.item(), v_est.item(), n_valid))
                    obs_dict = battle_select([a_idx])
                    continue
            obs_dict = battle_select(rule_pick(obs))
        else:
            if is_main_sel and turn_actions[who] <= 40:
                sv = extract_state_vector(obs)
                if sv is not None:
                    nsv = (sv - norm_mean) / (norm_std + 1e-8)
                    x = torch.FloatTensor(nsv).unsqueeze(0)
                    n_valid = len(sel.option)
                    with torch.no_grad():
                        logits, _ = opp_model(x)
                        a_idx = logits[0, :n_valid].argmax().item()
                    obs_dict = battle_select([a_idx])
                    continue
            obs_dict = battle_select(rule_pick(obs))

    battle_finish()
    reward = 1.0 if result == main_idx else (-1.0 if result == 1 - main_idx else 0.0)
    return transitions, reward


def play_eval_game(main_model, opp_model, norm_mean, norm_std, deck, seed, main_idx):
    """評価用: 遷移を収集せず勝敗だけ返す。"""
    _, reward = collect_league_game(main_model, opp_model, norm_mean, norm_std, deck, seed, main_idx)
    return reward

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
        r = final_reward if t == n-1 else 0.0
        nv = 0.0 if t == n-1 else values[t+1]
        delta = r + gamma * nv - values[t]
        last_adv = delta + gamma * lam * (0.0 if t == n-1 else last_adv)
        advantages[t] = last_adv
    return advantages.tolist(), (advantages + values).tolist()

# ============================================================
# PPO アップデート (KL ペナルティ付き)
# ============================================================
def ppo_update(model, ref_model, optimizer, all_trans,
               clip_eps=0.1, ppo_epochs=4, batch_size=256, kl_beta=0.01):
    if not all_trans:
        return 0.0, 0.0, 0.0

    states      = torch.FloatTensor(np.array([t[0] for t in all_trans]))
    actions     = torch.LongTensor([t[1] for t in all_trans])
    old_lps     = torch.FloatTensor([t[2] for t in all_trans])
    advantages  = torch.FloatTensor([t[5] for t in all_trans])
    returns     = torch.FloatTensor([t[6] for t in all_trans])
    valid_counts = [t[4] for t in all_trans]

    advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)

    model.train()
    tp = tv = tkl = n_upd = 0

    for _ in range(ppo_epochs):
        perm = torch.randperm(len(states))
        for start in range(0, len(states), batch_size):
            b = perm[start: start + batch_size]
            bs, ba, blp = states[b], actions[b], old_lps[b]
            badv, bret  = advantages[b], returns[b]
            bvc = [valid_counts[i] for i in b.tolist()]

            logits, values = model(bs)

            # KL: ref モデルの分布との divergence を計算
            with torch.no_grad():
                ref_logits, _ = ref_model(bs)

            for i, vc in enumerate(bvc):
                if vc < MAX_ACTIONS:
                    logits[i, vc:]     = -1e9
                    ref_logits[i, vc:] = -1e9

            curr_dist = torch.distributions.Categorical(logits=logits)
            ref_dist  = torch.distributions.Categorical(logits=ref_logits)
            kl        = torch.distributions.kl_divergence(curr_dist, ref_dist).mean()

            log_probs = curr_dist.log_prob(ba)
            entropy   = curr_dist.entropy().mean()

            ratio  = (log_probs - blp).exp()
            surr1  = ratio * badv
            surr2  = ratio.clamp(1 - clip_eps, 1 + clip_eps) * badv
            p_loss = -torch.min(surr1, surr2).mean()
            v_loss = F.mse_loss(values, bret)
            loss   = p_loss + 0.5 * v_loss - 0.01 * entropy + kl_beta * kl

            optimizer.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 0.5)
            optimizer.step()

            tp += p_loss.item(); tv += v_loss.item(); tkl += kl.item()
            n_upd += 1

    n = max(n_upd, 1)
    return tp/n, tv/n, tkl/n

# ============================================================
# メイン
# ============================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iters",      type=int,   default=650)
    ap.add_argument("--games",      type=int,   default=24)
    ap.add_argument("--lr",         type=float, default=5e-5)
    ap.add_argument("--lr-min",     type=float, default=1e-5)
    ap.add_argument("--gamma",      type=float, default=0.99)
    ap.add_argument("--lam",        type=float, default=0.95)
    ap.add_argument("--clip",       type=float, default=0.1)
    ap.add_argument("--epochs",     type=int,   default=4)
    ap.add_argument("--batch",      type=int,   default=256)
    ap.add_argument("--kl-beta",    type=float, default=0.01)
    ap.add_argument("--league-size",type=int,   default=25)
    ap.add_argument("--add-every",  type=int,   default=50)
    ap.add_argument("--eval-every", type=int,   default=50,  help="baseline 評価の頻度")
    ap.add_argument("--eval-games", type=int,   default=20,  help="評価ゲーム数")
    ap.add_argument("--seed",       type=int,   default=200)
    args = ap.parse_args()

    SUBMISSION    = os.path.join(HERE, "..", "submission")
    baseline_path = os.path.join(SUBMISSION, "ptcg_baseline_model.pth")
    rl_path       = os.path.join(SUBMISSION, "ptcg_rl_model.pth")
    league_path   = os.path.join(SUBMISSION, "ptcg_league_model.pth")
    out_path      = os.path.join(SUBMISSION, "ptcg_best_model.pth")
    log_path      = os.path.join(HERE, "train_best_log.txt")

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

    # ---- メインモデル: 最良モデルを出発点に ----
    for start_path, name in [(league_path,"league"), (rl_path,"rl"), (baseline_path,"baseline")]:
        if os.path.exists(start_path):
            main_model = load_ac_from_file(start_path)
            log(f"メインモデル初期化: {name} ({start_path})")
            break

    # ---- KL ペナルティ基準: 常に baseline ----
    ref_model = load_ac_from_file(baseline_path)
    ref_model.eval()
    log(f"KL 基準モデル: baseline")

    optimizer = torch.optim.Adam(main_model.parameters(), lr=args.lr)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer, T_max=args.iters, eta_min=args.lr_min
    )

    # ---- リーグ初期化 (3 錨) ----
    league = League(max_size=args.league_size)
    for path, aname in [(baseline_path,"baseline"),(rl_path,"rl_v0"),(league_path,"league_v0")]:
        if os.path.exists(path):
            league.add(aname, load_ac_from_file(path), anchor=True)
            log(f"リーグ追加 (錨): {aname}")

    # baseline エージェント (評価用固定)
    baseline_ac = load_ac_from_file(baseline_path)
    baseline_ac.eval()

    log(f"\n=== PPO リーグ学習 Best Edition ===")
    log(f"  iters={args.iters}  games/iter={args.games}  lr={args.lr}→{args.lr_min}")
    log(f"  clip={args.clip}  kl_beta={args.kl_beta}  league_size={args.league_size}")
    log(f"  初期リーグ: {league.names()}")
    log(f"  出力: {out_path}\n")

    total_games  = 0
    best_eval_wr = 0.0
    eval_history = []

    for it in range(1, args.iters + 1):
        t0 = time.time()
        all_trans = []
        wins = losses = draws = 0

        for g in range(args.games):
            opp_name, opp_model = league.sample()
            main_idx = 0 if g % 2 == 0 else 1
            seed = args.seed + total_games + g
            trans, reward = collect_league_game(
                main_model, opp_model, norm_mean, norm_std, deck, seed, main_idx
            )
            if reward > 0:   wins   += 1
            elif reward < 0: losses += 1
            else:            draws  += 1
            adv, ret = compute_gae(trans, reward, args.gamma, args.lam)
            for i, t in enumerate(trans):
                all_trans.append((*t, adv[i], ret[i]))

        total_games += args.games

        p_loss, v_loss, kl_loss = ppo_update(
            main_model, ref_model, optimizer, all_trans,
            args.clip, args.epochs, args.batch, args.kl_beta,
        )
        scheduler.step()

        elapsed  = time.time() - t0
        win_rate = wins / max(wins + losses, 1)
        cur_lr   = scheduler.get_last_lr()[0]

        log(
            f"[{it:3d}/{args.iters}] "
            f"games={total_games:5d}  W/D/L={wins}/{draws}/{losses}  "
            f"wr={win_rate:.0%}  "
            f"p={p_loss:.4f}  v={v_loss:.4f}  kl={kl_loss:.4f}  "
            f"lr={cur_lr:.1e}  {elapsed:.1f}s"
        )

        # ---- リーグへスナップショット追加 ----
        if it % args.add_every == 0:
            snap = f"iter{it}"
            league.add(snap, main_model)
            log(f"  => リーグ追加: {snap}  ({len(league)} メンバー)")

        # ---- baseline 評価 ----
        if it % args.eval_every == 0:
            eval_wins = 0
            for eg in range(args.eval_games):
                midx = 0 if eg % 2 == 0 else 1
                r = play_eval_game(
                    main_model, baseline_ac, norm_mean, norm_std, deck,
                    seed=args.seed + 99999 + it * 1000 + eg, main_idx=midx,
                )
                if r > 0: eval_wins += 1
            eval_wr = eval_wins / args.eval_games
            eval_history.append((it, eval_wr))
            marker = ""
            if eval_wr > best_eval_wr:
                best_eval_wr = eval_wr
                save_policy(main_model, out_path)
                marker = "  ★ BEST 保存"
            log(f"  [EVAL vs baseline] {eval_wins}/{args.eval_games} = {eval_wr:.0%}{marker}")

    # 最終モデルも保存 (ベストより良ければ上書き)
    final_wins = 0
    for eg in range(40):
        midx = 0 if eg % 2 == 0 else 1
        r = play_eval_game(
            main_model, baseline_ac, norm_mean, norm_std, deck,
            seed=args.seed + 88888 + eg, main_idx=midx,
        )
        if r > 0: final_wins += 1
    final_wr = final_wins / 40
    if final_wr >= best_eval_wr:
        save_policy(main_model, out_path)
        log(f"\n最終モデルが最良 ({final_wr:.0%}) → {out_path} に保存")
    else:
        log(f"\n最終 ({final_wr:.0%}) よりベストチェックポイント ({best_eval_wr:.0%}) を保持")

    log(f"\n=== 学習完了 ===")
    log(f"ベスト評価 win rate vs baseline: {best_eval_wr:.0%}")
    log(f"評価履歴: {[(it, f'{wr:.0%}') for it, wr in eval_history]}")
    log(f"出力: {out_path}")
    log(f"提出に使う場合:")
    log(f"  copy submission\\ptcg_best_model.pth submission\\ptcg_league_model.pth")
    log_file.close()


if __name__ == "__main__":
    main()
