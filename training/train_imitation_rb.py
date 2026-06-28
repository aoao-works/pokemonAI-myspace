#!/usr/bin/env python3
"""
train_imitation_rb.py — ルールベースエージェントの模倣学習

ルールベース同士の対戦から勝者の MAIN 決定を収集し、
NN に CrossEntropy 損失で教師学習させる。

期待効果: NN が rb の MAIN 決定を模倣 → 勝率 ≈ 50%

使い方:
  C:\\venv\\Scripts\\python training\\train_imitation_rb.py --games 800 --epochs 30
"""
import os, sys, random, time, argparse, importlib.util
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

HERE    = os.path.dirname(os.path.abspath(__file__))
ROOT    = os.path.normpath(os.path.join(HERE, ".."))
STADIUM = os.path.normpath(os.path.join(ROOT, "PTCGstadium"))
SUB     = os.path.normpath(os.path.join(ROOT, "submission"))
sys.path.insert(0, STADIUM)

from cg.api import (
    to_observation_class, SelectType, EnergyType, all_card_data, all_attack,
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

def extract_state_vector(obs):
    s = obs.current
    if s is None or len(s.players) < 2: return None
    gf = [s.stadium[0].id if s.stadium else 0,
          int(s.supporterPlayed), int(s.energyAttached), int(s.retreated),
          s.firstPlayer, s.turn]
    mi = s.yourIndex
    return np.array(gf + _player_feat(s.players[mi]) + _player_feat(s.players[1-mi]),
                    dtype=np.float32)

# ============================================================
# ルールベースモジュールのロード
# ============================================================
def _load_rb_module(name: str):
    main_path = os.path.join(STADIUM, "agents", "baseline", "main.py")
    spec = importlib.util.spec_from_file_location(name, main_path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.read_deck_csv = lambda: []
    return mod

def reset_rb_state(mod):
    mod._last_seen_turn           = -1
    mod._non_boss_supporter_played = False
    mod._luna_cycle_used           = False

# ============================================================
# モデル定義
# ============================================================
class PolicyNet(nn.Module):
    def __init__(self):
        super().__init__()
        self.fc1 = nn.Linear(INPUT_DIM, 1024); self.ln1 = nn.LayerNorm(1024)
        self.fc2 = nn.Linear(1024, 512);        self.ln2 = nn.LayerNorm(512)
        self.fc3 = nn.Linear(512, MAX_ACTIONS)
    def forward(self, x):
        x = F.relu(self.ln1(self.fc1(x)))
        x = F.relu(self.ln2(self.fc2(x)))
        return self.fc3(x)

def load_model(path):
    net = PolicyNet()
    src = torch.load(path, map_location='cpu', weights_only=True)
    dst = net.state_dict()
    # fc3 形式 or そのまま読み込み
    key_map = {
        'fc3.weight': 'fc3.weight', 'fc3.bias': 'fc3.bias',
        'policy.weight': 'fc3.weight', 'policy.bias': 'fc3.bias',
    }
    for sk, dk in key_map.items():
        if sk in src and dk in dst:
            dst[dk] = src[sk]
    for k in ['fc1.weight','fc1.bias','ln1.weight','ln1.bias',
               'fc2.weight','fc2.bias','ln2.weight','ln2.bias']:
        if k in src and k in dst:
            dst[k] = src[k]
    net.load_state_dict(dst)
    return net

def save_model(net, path):
    torch.save({k: v for k, v in net.state_dict().items()}, path)

# ============================================================
# データ収集: ルールベース vs ルールベース
# ============================================================
def collect_game(rb_p0, rb_p1, norm_mean, norm_std, deck, seed):
    """
    ルールベース同士の対戦を実行し、勝者の MAIN 決定を返す。
    返値: (list of (state_vector, action_idx, n_valid), winner_idx)
    """
    reset_rb_state(rb_p0)
    reset_rb_state(rb_p1)
    random.seed(seed)

    # 各プレイヤーの MAIN 遷移を収集
    trans = {0: [], 1: []}
    result = -1

    obs_dict, _ = battle_start(deck, deck)
    if obs_dict is None:
        return [], -1

    for _step in range(4000):
        obs = to_observation_class(obs_dict)
        cur = obs.current
        if cur is not None and cur.result != -1:
            result = cur.result; break
        if obs.select is None:
            break

        who = cur.yourIndex if cur is not None else 0
        agent = rb_p0 if who == 0 else rb_p1

        is_main = False
        try:
            is_main = (SelectType(obs.select.type) == SelectType.MAIN)
        except Exception:
            pass

        action = agent.agent(obs_dict)
        a_idx  = action[0] if action else 0

        if is_main:
            sv = extract_state_vector(obs)
            if sv is not None:
                nsv = (sv - norm_mean) / (norm_std + 1e-8)
                n_valid = len(obs.select.option)
                if 0 <= a_idx < n_valid:  # 有効なアクションのみ記録
                    trans[who].append((nsv.copy(), a_idx, n_valid))

        obs_dict = battle_select(action)  # 複数選択に対応 (COUNT型等)

    battle_finish()

    if result in (0, 1):
        return trans[result], result
    else:
        # 引き分け: 両方の遷移を使う
        return trans[0] + trans[1], result

# ============================================================
# 教師学習
# ============================================================
def train_epoch(model, optimizer, all_data, batch_size=256):
    model.train()
    indices = list(range(len(all_data)))
    random.shuffle(indices)
    total_loss = correct = n_total = 0

    for start in range(0, len(indices), batch_size):
        b   = indices[start:start+batch_size]
        svs = torch.FloatTensor(np.array([all_data[i][0] for i in b]))
        acts = torch.LongTensor([all_data[i][1] for i in b])
        vcs  = [all_data[i][2] for i in b]

        logits = model(svs)

        # 無効アクションをマスク
        logits_m = logits.clone()
        for j, vc in enumerate(vcs):
            if vc < MAX_ACTIONS:
                logits_m[j, vc:] = -1e9

        loss = F.cross_entropy(logits_m, acts)
        optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()

        total_loss += loss.item() * len(b)
        preds      = logits_m.argmax(dim=1)
        correct    += (preds == acts).sum().item()
        n_total    += len(b)

    return total_loss / max(n_total, 1), correct / max(n_total, 1)

# ============================================================
# 評価: NN vs ルールベース
# ============================================================
def eval_vs_rb(model, rb_opp, rb_helper, norm_mean, norm_std, deck, n_games, seed=9999):
    model.eval()
    wins = 0
    for g in range(n_games):
        reset_rb_state(rb_opp)
        reset_rb_state(rb_helper)
        random.seed(seed + g)
        main_idx = g % 2  # 先攻/後攻を交互に

        obs_dict, _ = battle_start(deck, deck)
        if obs_dict is None:
            continue

        result = -1
        for _step in range(4000):
            obs = to_observation_class(obs_dict)
            cur = obs.current
            if cur is not None and cur.result != -1:
                result = cur.result; break
            if obs.select is None:
                break

            who = cur.yourIndex if cur is not None else 0
            is_main = False
            try:
                is_main = (SelectType(obs.select.type) == SelectType.MAIN)
            except Exception:
                pass

            if who == main_idx:
                if is_main:
                    sv = extract_state_vector(obs)
                    if sv is not None:
                        nsv = (sv - norm_mean) / (norm_std + 1e-8)
                        x   = torch.FloatTensor(nsv).unsqueeze(0)
                        n_valid = len(obs.select.option)
                        with torch.no_grad():
                            logits = model(x)
                            mask = torch.zeros(MAX_ACTIONS, dtype=torch.bool)
                            mask[n_valid:] = True
                            a_idx = logits[0].masked_fill(mask, -1e9).argmax().item()
                        if 0 <= a_idx < n_valid:
                            obs_dict = battle_select([a_idx])
                            continue
                obs_dict = battle_select(rb_helper.agent(obs_dict))
            else:
                obs_dict = battle_select(rb_opp.agent(obs_dict))

        battle_finish()
        if result == main_idx:
            wins += 1

    return wins / max(n_games, 1)

# ============================================================
# デッキ読み込み
# ============================================================
def read_deck():
    deck_path = os.path.join(SUB, "deck.csv")
    with open(deck_path) as f:
        return [int(l.strip()) for l in f if l.strip()]

# ============================================================
# メイン
# ============================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games",      type=int,   default=800,  help="データ収集ゲーム数")
    ap.add_argument("--epochs",     type=int,   default=30,   help="教師学習エポック数")
    ap.add_argument("--lr",         type=float, default=3e-4, help="学習率")
    ap.add_argument("--batch",      type=int,   default=256)
    ap.add_argument("--eval-games", type=int,   default=50,   help="評価ゲーム数")
    ap.add_argument("--seed",       type=int,   default=42)
    ap.add_argument("--also-loser", action="store_true", help="敗者の遷移も訓練に含める")
    args = ap.parse_args()

    log_path = os.path.join(ROOT, "training", "train_imitation_log.txt")
    out_path = os.path.join(SUB, "ptcg_rb_model.pth")
    norm     = np.load(os.path.join(SUB, "ptcg_normalization.npz"))
    norm_mean = norm['mean'].astype(np.float32)
    norm_std  = norm['std'].astype(np.float32)
    deck = read_deck()

    def log(msg):
        print(msg, end='', flush=True)
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(msg)

    with open(log_path, 'w', encoding='utf-8') as f:
        f.write("")

    log("=== ルールベース模倣学習 ===\n")
    log(f"  データ収集: {args.games} ゲーム (rb vs rb)\n")
    log(f"  教師学習: {args.epochs} エポック, lr={args.lr}, batch={args.batch}\n")
    log(f"  評価: {args.eval_games} ゲーム (NN vs rb)\n\n")

    # ルールベースモジュールをロード (3インスタンス)
    rb_p0     = _load_rb_module("_rb_p0_imitation")
    rb_p1     = _load_rb_module("_rb_p1_imitation")
    rb_opp    = _load_rb_module("_rb_opp_imitation")
    rb_helper = _load_rb_module("_rb_helper_imitation")

    # モデルをロード (ptcg_best_model.pth から開始)
    best_path = os.path.join(SUB, "ptcg_best_model.pth")
    if os.path.exists(best_path):
        model = load_model(best_path)
        log(f"初期モデル: {best_path}\n")
    else:
        model = PolicyNet()
        log("初期モデル: ランダム初期化\n")

    # 初期評価
    log("\n初期評価中 (vs ルールベース)...\n")
    t0 = time.time()
    init_wr = eval_vs_rb(model, rb_opp, rb_helper, norm_mean, norm_std, deck, args.eval_games, seed=args.seed)
    log(f"初期勝率: {init_wr*100:.1f}% ({int(init_wr*args.eval_games)}/{args.eval_games}) [{time.time()-t0:.1f}s]\n\n")

    # ============================================================
    # データ収集: ルールベース同士の対戦
    # ============================================================
    log(f"データ収集開始: {args.games} ゲーム...\n")
    all_data = []
    wins_p0  = 0
    t_collect = time.time()

    for g in range(args.games):
        seed = args.seed + g
        trans, winner = collect_game(rb_p0, rb_p1, norm_mean, norm_std, deck, seed)
        if args.also_loser:
            # 敗者側遷移も追加（ただし重みは薄くしない）
            other_who = 1 - winner if winner in (0, 1) else 0
            # 全遷移を追加（ただし敗者ラベルは反転しない）
            pass
        all_data.extend(trans)
        if winner == 0:
            wins_p0 += 1
        if (g + 1) % 100 == 0:
            elapsed = time.time() - t_collect
            log(f"  [{g+1}/{args.games}] 収集サンプル数={len(all_data)}, "
                f"p0勝率={wins_p0/(g+1)*100:.1f}%, 経過={elapsed:.1f}s\n")

    collect_elapsed = time.time() - t_collect
    log(f"\nデータ収集完了: {len(all_data)} サンプル ({collect_elapsed:.1f}s)\n")
    log(f"1ゲームあたりの平均 MAIN 遷移数: {len(all_data)/args.games:.1f}\n\n")

    if not all_data:
        log("エラー: データが収集できませんでした\n")
        return

    # ============================================================
    # 教師学習
    # ============================================================
    log(f"教師学習開始: {args.epochs} エポック...\n")
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer, T_max=args.epochs, eta_min=args.lr / 10)
    t_train = time.time()

    for ep in range(args.epochs):
        loss, acc = train_epoch(model, optimizer, all_data, args.batch)
        scheduler.step()
        if (ep + 1) % 5 == 0:
            log(f"  epoch {ep+1:3d}/{args.epochs}: loss={loss:.4f}, acc={acc*100:.1f}%"
                f", lr={scheduler.get_last_lr()[0]:.2e}\n")

    log(f"教師学習完了 ({time.time()-t_train:.1f}s)\n\n")

    # ============================================================
    # 評価 & 保存
    # ============================================================
    log("評価中 (vs ルールベース)...\n")
    t_eval = time.time()
    final_wr = eval_vs_rb(model, rb_opp, rb_helper, norm_mean, norm_std, deck,
                          args.eval_games, seed=args.seed + 1000)
    log(f"最終勝率: {final_wr*100:.1f}% ({int(final_wr*args.eval_games)}/{args.eval_games}) "
        f"[{time.time()-t_eval:.1f}s]\n")
    log(f"改善: {init_wr*100:.1f}% → {final_wr*100:.1f}% "
        f"(+{(final_wr-init_wr)*100:.1f}%)\n\n")

    if final_wr >= init_wr - 0.01:  # 初期値以上なら保存（小さな劣化は許容）
        save_model(model, out_path)
        log(f"モデル保存: {out_path}\n")
        if final_wr > 0.40:
            best_out = os.path.join(SUB, "ptcg_best_model.pth")
            save_model(model, best_out)
            log(f"ptcg_best_model.pth も上書き (勝率 {final_wr*100:.1f}% > 40%)\n")
    else:
        log(f"保存スキップ (初期値 {init_wr*100:.1f}% より {(init_wr-final_wr)*100:.1f}% 低いため)\n")

    log("\n=== 完了 ===\n")

if __name__ == "__main__":
    main()
