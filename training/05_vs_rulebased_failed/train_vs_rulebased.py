#!/usr/bin/env python3
"""
train_vs_rulebased.py — ルールベースエージェント専用 PPO 学習 (1時間版)

目標: PTCGstadium/agents/baseline のルールベースエージェントを 50%+ で撃破。
制約: 1時間以内に完了 (CPU のみ)。

設計:
  固定相手 = ルールベースエージェント (league 不使用)
  初期モデル = ptcg_best_model.pth (21% vs ルールベース → 向上目指す)
  NN プレイヤーの非MAIN選択も rb_helper の完全ロジックを使用 (学習信号をクリーンに)
  LR: 1e-4 → 2e-5 (コサイン、現行の2倍で素早く適応)
  KL beta: 0.005 (baseline NN から離れすぎないよう軽度に拘束)
  clip_eps: 0.15 (現行 0.10 より広い更新範囲)
  120 iter × 20 games = 2400 ゲーム ≈ 55分

出力: submission/ptcg_rb_model.pth (評価最良時に自動保存)
     学習後: submission/ptcg_best_model.pth にも自動上書き (win rate 改善時)
"""
import os, sys, random, time, argparse, importlib.util
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

HERE    = os.path.dirname(os.path.abspath(__file__))
STADIUM = os.path.normpath(os.path.join(HERE, "..", "PTCGstadium"))
sys.path.insert(0, STADIUM)

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
# ルールベースエージェントのロード (2インスタンス: 対戦相手用 + NNプレイヤー非MAIN用)
# ============================================================
def _load_rb_module(name: str):
    """PTCGstadium/agents/baseline/main.py を独立したモジュールとしてロード"""
    main_path = os.path.join(STADIUM, "agents", "baseline", "main.py")
    spec = importlib.util.spec_from_file_location(name, main_path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.read_deck_csv = lambda: []  # デッキ選択は battle_start で処理済み
    return mod

def reset_rb_state(mod):
    """ゲーム間グローバル状態リセット (ターン追跡フラグをクリア)"""
    mod._last_seen_turn          = -1
    mod._non_boss_supporter_played = False
    mod._luna_cycle_used          = False

# ============================================================
# Actor-Critic ネットワーク
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
    """fc3-format ファイル → ActorCritic (value head はゼロ初期化)"""
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


def save_policy(model, path):
    torch.save({
        'fc1.weight': model.fc1.weight.data,    'fc1.bias': model.fc1.bias.data,
        'ln1.weight': model.ln1.weight.data,    'ln1.bias': model.ln1.bias.data,
        'fc2.weight': model.fc2.weight.data,    'fc2.bias': model.fc2.bias.data,
        'ln2.weight': model.ln2.weight.data,    'ln2.bias': model.ln2.bias.data,
        'fc3.weight': model.policy.weight.data, 'fc3.bias': model.policy.bias.data,
    }, path)

# ============================================================
# ゲーム収集: NN vs ルールベース
# ============================================================
def collect_game(main_model, rb_opp, rb_helper, norm_mean, norm_std, deck, seed, main_idx, opp_noise=0.0):
    """
    main_model (NN) vs ルールベースの 1 ゲームを実行し遷移を返す。

    - MAIN select (NN player): NN がサンプリング → 遷移を記録
    - 非MAIN select (NN player): rb_helper の完全ロジックを使用 (学習信号をクリーンに保つ)
    - 全 select (相手): rb_opp の完全ロジック (opp_noise>0 のとき一部ランダム)

    2 つの独立したモジュールインスタンスにより、NN側と相手側のターン追跡が干渉しない。
    """
    reset_rb_state(rb_opp)
    reset_rb_state(rb_helper)
    random.seed(seed)

    transitions  = []
    turn_actions = {0: 0, 1: 0}
    last_turn    = {0: -1, 1: -1}

    obs_dict, _ = battle_start(deck, deck)
    if obs_dict is None:
        return [], 0.0

    main_model.eval()
    result = -1

    # プライズカード差分による中間報酬
    prev_my_prizes  = 6
    prev_opp_prizes = 6
    pending_reward  = 0.0

    for _step in range(4000):
        obs = to_observation_class(obs_dict)
        cur = obs.current
        if cur is not None and cur.result != -1:
            result = cur.result; break
        if obs.select is None:
            break

        # プライズ差分を中間報酬として積算
        if cur is not None and len(cur.players) >= 2:
            my_p  = sum(1 for p in cur.players[main_idx].prize          if p is not None)
            opp_p = sum(1 for p in cur.players[1 - main_idx].prize      if p is not None)
            if my_p  < prev_my_prizes:   pending_reward += 0.3 * (prev_my_prizes  - my_p)
            if opp_p < prev_opp_prizes:  pending_reward -= 0.3 * (prev_opp_prizes - opp_p)
            prev_my_prizes, prev_opp_prizes = my_p, opp_p

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
                # NN が MAIN 選択 → 遷移記録
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
                    transitions.append((nsv.copy(), a_idx, lp.item(), v_est.item(), n_valid, pending_reward))
                    pending_reward = 0.0
                    obs_dict = battle_select([a_idx])
                    continue
            # 非MAIN または turn_actions > 40: rb_helper の完全ロジック
            obs_dict = battle_select(rb_helper.agent(obs_dict))
        else:
            # 相手: rb_opp (opp_noise > 0 のとき一定確率でランダム行動)
            if opp_noise > 0.0 and random.random() < opp_noise:
                _n = len(sel.option)
                _k = max(getattr(sel, 'minCount', 1), 1)
                obs_dict = battle_select(random.sample(range(_n), min(_k, _n)))
            else:
                obs_dict = battle_select(rb_opp.agent(obs_dict))

    battle_finish()
    reward = 1.0 if result == main_idx else (-1.0 if result == 1 - main_idx else 0.0)
    return transitions, reward

# ============================================================
# GAE
# ============================================================
def compute_gae(transitions, final_reward, gamma=0.99, lam=0.95):
    n = len(transitions)
    if n == 0:
        return [], []
    values    = np.array([t[3] for t in transitions], dtype=np.float32)
    step_rews = np.array([t[5] if len(t) > 5 else 0.0 for t in transitions], dtype=np.float32)
    advantages = np.zeros(n, dtype=np.float32)
    last_adv = 0.0
    for t in reversed(range(n)):
        r  = step_rews[t] + (final_reward if t == n - 1 else 0.0)
        nv = 0.0 if t == n - 1 else values[t + 1]
        delta    = r + gamma * nv - values[t]
        last_adv = delta + gamma * lam * (0.0 if t == n - 1 else last_adv)
        advantages[t] = last_adv
    return advantages.tolist(), (advantages + values).tolist()

# ============================================================
# PPO アップデート (KL ペナルティ付き)
# ============================================================
def ppo_update(model, ref_model, optimizer, all_trans,
               clip_eps=0.15, ppo_epochs=4, batch_size=256, kl_beta=0.005):
    if not all_trans:
        return 0.0, 0.0, 0.0

    states       = torch.FloatTensor(np.array([t[0] for t in all_trans]))
    actions      = torch.LongTensor([t[1] for t in all_trans])
    old_lps      = torch.FloatTensor([t[2] for t in all_trans])
    advantages   = torch.FloatTensor([t[6] for t in all_trans])
    returns      = torch.FloatTensor([t[7] for t in all_trans])
    valid_counts = [t[4] for t in all_trans]

    advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)

    model.train()
    tp = tv = tkl = n_upd = 0

    for _ in range(ppo_epochs):
        perm = torch.randperm(len(states))
        for start in range(0, len(states), batch_size):
            b   = perm[start: start + batch_size]
            bs  = states[b]; ba = actions[b]; blp = old_lps[b]
            badv = advantages[b]; bret = returns[b]
            bvc  = [valid_counts[i] for i in b.tolist()]

            logits, values = model(bs)
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
    return tp / n, tv / n, tkl / n

# ============================================================
# メイン
# ============================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iters",      type=int,   default=120, help="学習イテレーション数")
    ap.add_argument("--games",      type=int,   default=20,  help="iter あたりのゲーム数")
    ap.add_argument("--lr",         type=float, default=1e-4)
    ap.add_argument("--lr-min",     type=float, default=2e-5)
    ap.add_argument("--gamma",      type=float, default=0.99)
    ap.add_argument("--lam",        type=float, default=0.95)
    ap.add_argument("--clip",       type=float, default=0.15)
    ap.add_argument("--epochs",     type=int,   default=4)
    ap.add_argument("--batch",      type=int,   default=256)
    ap.add_argument("--kl-beta",    type=float, default=0.005)
    ap.add_argument("--eval-every", type=int,   default=20,  help="評価頻度 (iter)")
    ap.add_argument("--eval-games", type=int,   default=20,  help="評価ゲーム数")
    ap.add_argument("--opp-noise",  type=float, default=0.0, help="対戦相手ノイズ率 0=フルRB / 0.5=半分ランダム")
    ap.add_argument("--time-limit", type=int,   default=0,   help="最大学習時間（分、0=無制限）")
    ap.add_argument("--seed",       type=int,   default=300)
    ap.add_argument("--out-path",   type=str,   default=None, help="出力モデルパス (省略時は ptcg_rb_model.pth)")
    args = ap.parse_args()

    SUBMISSION    = os.path.normpath(os.path.join(HERE, "..", "submission"))
    baseline_path = os.path.join(SUBMISSION, "ptcg_baseline_model.pth")
    best_path     = os.path.join(SUBMISSION, "ptcg_best_model.pth")
    out_path      = args.out_path if args.out_path else os.path.join(SUBMISSION, "ptcg_rb_model.pth")
    log_path      = os.path.join(HERE, "train_rb_log.txt")

    with open(os.path.join(SUBMISSION, "deck.csv"), "r") as f:
        rows = f.read().split("\n")
    deck = [int(rows[i]) for i in range(60)]

    norm      = np.load(os.path.join(SUBMISSION, "ptcg_normalization.npz"))
    norm_mean = norm['mean'].astype(np.float32)
    norm_std  = norm['std'].astype(np.float32)

    # ルールベースモジュールを 2 インスタンスでロード (相手用 / NN非MAIN用)
    print("ルールベースエージェントをロード中...")
    rb_opp    = _load_rb_module("rb_opponent")
    rb_helper = _load_rb_module("rb_helper")
    print("ロード完了")

    log_file = open(log_path, "w", encoding="utf-8", buffering=1)
    def log(msg):
        print(msg, flush=True)
        print(msg, file=log_file, flush=True)

    # メインモデル: ptcg_best_model.pth → ptcg_baseline_model.pth の順で探す
    for start_path, sname in [(best_path, "best"), (baseline_path, "baseline")]:
        if os.path.exists(start_path):
            main_model = load_ac_from_file(start_path)
            log(f"メインモデル初期化: {sname} ({start_path})")
            break
    else:
        raise FileNotFoundError("初期モデルが見つかりません")

    # KL ペナルティ基準: NN baseline (汎用性を維持)
    ref_model = load_ac_from_file(baseline_path)
    ref_model.eval()

    optimizer = torch.optim.Adam(main_model.parameters(), lr=args.lr)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer, T_max=args.iters, eta_min=args.lr_min
    )

    log(f"\n=== ルールベース専用 PPO 学習 ===")
    log(f"  iters={args.iters}  games/iter={args.games}  lr={args.lr}→{args.lr_min}")
    log(f"  clip={args.clip}  kl_beta={args.kl_beta}  epochs={args.epochs}")
    log(f"  対戦相手: PTCGstadium/agents/baseline (ルールベース)")
    log(f"  出力: {out_path}\n")

    # 初期評価
    log("初期評価中 (vs ルールベース)...")
    init_wins = 0
    for eg in range(args.eval_games):
        midx = 0 if eg % 2 == 0 else 1
        _, r = collect_game(main_model, rb_opp, rb_helper, norm_mean, norm_std,
                            deck, seed=args.seed + 50000 + eg, main_idx=midx)
        if r > 0: init_wins += 1
    init_wr = init_wins / args.eval_games
    log(f"初期評価: {init_wins}/{args.eval_games} = {init_wr:.0%}")

    # 初期モデルを即保存 (ベースラインとして、以降は超えた時のみ上書き)
    save_policy(main_model, out_path)
    log(f"初期モデルを {out_path} に保存\n")

    total_games  = 0
    best_eval_wr = init_wr
    eval_history = [(0, init_wr)]
    t_start      = time.time()

    for it in range(1, args.iters + 1):
        t0 = time.time()
        all_trans = []
        wins = losses = draws = 0

        for g in range(args.games):
            main_idx = 0 if g % 2 == 0 else 1
            seed = args.seed + total_games + g
            trans, reward = collect_game(
                main_model, rb_opp, rb_helper, norm_mean, norm_std, deck, seed, main_idx,
                opp_noise=args.opp_noise,
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
        elapsed_total = time.time() - t_start
        win_rate = wins / max(wins + losses, 1)
        cur_lr   = scheduler.get_last_lr()[0]

        log(
            f"[{it:3d}/{args.iters}] "
            f"games={total_games:5d}  W/D/L={wins}/{draws}/{losses}  "
            f"wr={win_rate:.0%}  "
            f"p={p_loss:.4f}  v={v_loss:.4f}  kl={kl_loss:.4f}  "
            f"lr={cur_lr:.1e}  {elapsed:.1f}s  total={elapsed_total/60:.1f}min"
        )

        if args.time_limit > 0 and (time.time() - t_start) / 60 >= args.time_limit:
            log(f"時間制限 {args.time_limit}分 に達したため学習を停止します")
            break

        if it % args.eval_every == 0:
            eval_wins = 0
            for eg in range(args.eval_games):
                midx = 0 if eg % 2 == 0 else 1
                _, r = collect_game(
                    main_model, rb_opp, rb_helper, norm_mean, norm_std, deck,
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
            log(f"  [EVAL vs ルールベース] {eval_wins}/{args.eval_games} = {eval_wr:.0%}{marker}")

    # 最終評価
    log("\n最終評価中...")
    final_wins = 0
    for eg in range(args.eval_games):
        midx = 0 if eg % 2 == 0 else 1
        _, r = collect_game(
            main_model, rb_opp, rb_helper, norm_mean, norm_std, deck,
            seed=args.seed + 88888 + eg, main_idx=midx,
        )
        if r > 0: final_wins += 1
    final_wr = final_wins / args.eval_games
    if final_wr >= best_eval_wr:
        best_eval_wr = final_wr
        save_policy(main_model, out_path)
        log(f"最終モデルが最良 ({final_wr:.0%}) → {out_path} に保存")

    total_min = (time.time() - t_start) / 60
    log(f"\n=== 学習完了 ({total_min:.1f}分) ===")
    log(f"  初期 vs ルールベース: {init_wr:.0%}")
    log(f"  最終 vs ルールベース: {best_eval_wr:.0%}")
    log(f"  評価履歴: {[(it, f'{wr:.0%}') for it, wr in eval_history]}")
    log(f"  出力: {out_path}")
    log(f"\nアリーナで確認:")
    log(f"  $env:PYTHONIOENCODING='utf-8'")
    log(f"  C:\\venv\\Scripts\\python PTCGstadium\\arena.py --p0 agents/rb --p1 agents/baseline --games 100")
    log_file.close()


if __name__ == "__main__":
    main()
