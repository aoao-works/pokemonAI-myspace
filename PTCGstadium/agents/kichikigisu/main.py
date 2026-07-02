"""
キチキギス耐久エージェント。

コンセプト: キチキギス（特性アドレナフェロモン=悪エネルギーが付いていれば被ダメージ時に
コイン表でダメージを完全無効化）を主軸に、被弾しても倒れない・倒れても回復するを繰り返し
ながら、エナジーフェザー（付いているエネルギー数×30）で少しずつ削り勝つ耐久デッキ。

たね1種だけ(4枚)だと初手にたねが1匹も来ない確率が約60%（マリガン地獄）になるため、
同じ【超】タイプ・にげる1のクレセリア（自分に基本超エネルギーを2枚まで加速）と
メロエッタ（ベンチの超ポケモンを120回復）をたねの頭数として同数採用し、
マリガン率を抑えつつ、キチキギスのエネルギー供給とベンチでの回復ローテーションを助けている。
"""
import os

from cg.api import (
    Observation, SelectType, SelectContext, OptionType, AreaType, EnergyType,
    to_observation_class, all_attack, all_card_data,
)

HERE = os.path.dirname(os.path.abspath(__file__))


def read_deck_csv() -> list[int]:
    with open(os.path.join(HERE, "deck.csv"), "r") as f:
        rows = f.read().split("\n")
    return [int(rows[i]) for i in range(60)]


# --- カードID定数 ---
CID_KICHIKIGISU       = 970   # キチキギス（特性アドレナフェロモン/エナジーフェザー）
CID_CRESELIA          = 764   # クレセリア（みなぎるひかり=超エネルギー加速/オーロラビーム）
CID_MELOETTA          = 765   # メロエッタ（いやしのメロディ=ベンチ回復/マジカルショット）
CID_PSYCHIC_ENERGY    = 5     # 基本【超】エネルギー
CID_DARKNESS_ENERGY   = 7     # 基本【悪】エネルギー（キチキギスの特性発動に必須）
CID_POTION            = 1117  # きずぐすり
CID_ULTRA_BALL        = 1121  # ハイパーボール
CID_SWITCH_ITEM       = 1123  # ポケモンいれかえ
CID_POKE_PAD          = 1152  # ポケパッド
CID_NIGHT_STRETCHER   = 1097  # 夜のタンカ
CID_ENERGY_RETRIEVAL  = 1118  # エネルギー回収
CID_HERO_CAPE         = 1159  # ヒーローマント（ACE SPEC、最大HP+100）
CID_EMERGENCY_BOARD   = 1157  # 緊急ボード（にげるコスト軽減）
CID_LUCKY_HELMET      = 1156  # ラッキーメット（被弾時2枚ドロー）
CID_YUKARI            = 1241  # ユカリ（自分の超ポケモン1匹のHPを150回復）
CID_CHERENE           = 1224  # チェレン（3枚ドロー）
CID_JUDGE             = 1213  # ジャッジマン（手札リセット4枚ドロー）
CID_BELL              = 1190  # ベルのまごころ（HP30以下のポケモンを全回復）
CID_BOSS              = 1182  # ボスの指令（ベンチ指名）

_OUR_SPECIES = (CID_KICHIKIGISU, CID_CRESELIA, CID_MELOETTA)
_SPECIES_PRIORITY = {CID_KICHIKIGISU: 0, CID_CRESELIA: 1, CID_MELOETTA: 2}
_OUR_ENERGY = (CID_PSYCHIC_ENERGY, CID_DARKNESS_ENERGY)
_OUR_TOOLS = (CID_HERO_CAPE, CID_LUCKY_HELMET, CID_EMERGENCY_BOARD)

# --- キャッシュ ---
_attack_cache: dict | None = None
_card_data_cache: dict | None = None


def _get_attack_cache() -> dict:
    global _attack_cache
    if _attack_cache is None:
        _attack_cache = {a.attackId: a for a in all_attack()}
    return _attack_cache


def _get_card_data_cache() -> dict:
    global _card_data_cache
    if _card_data_cache is None:
        _card_data_cache = {c.cardId: c for c in all_card_data()}
    return _card_data_cache


# --- 汎用ヘルパー ---

def _best_attack_damage(pokemon, card_cache: dict, attack_cache: dict) -> int:
    if pokemon is None:
        return 0
    cd = card_cache.get(pokemon.id)
    if cd is None:
        return 0
    return max((attack_cache[aid].damage for aid in cd.attacks if aid in attack_cache), default=0)


def _dodge_ready(poke) -> bool:
    """キチキギスの特性（悪エネルギーが付いていれば被弾を50%無効化）が発動可能か"""
    return poke.id == CID_KICHIKIGISU and EnergyType.DARKNESS in (poke.energies or [])


def _board(your_state) -> list:
    return list(your_state.active or []) + list(your_state.bench or [])


def _board_count(your_state, species=_OUR_SPECIES) -> int:
    return sum(1 for p in _board(your_state) if p.id in species)


def _hp_deficit(your_state) -> int:
    """自分の場のポケモン(3種)の中で最大のHP不足量"""
    best = 0
    for p in _board(your_state):
        if p.id not in _OUR_SPECIES:
            continue
        d = p.maxHp - p.hp
        if d > best:
            best = d
    return best


def _has_low_hp(your_state, threshold: int = 30) -> bool:
    return any(p.id in _OUR_SPECIES and p.hp <= threshold for p in _board(your_state))


def _hand_energy_count(hand) -> int:
    return sum(1 for c in (hand or []) if c.id in _OUR_ENERGY)


# --- 危険判定・退避先選択 ---

def _find_best_bench_idx(bench, threat: int):
    """脅威(threat)を生き残れる中で最良のベンチ候補を返す。(index, 生存可否)"""
    best = None
    best_score = None
    for i, p in enumerate(bench or []):
        if p is None:
            continue
        score = (1 if p.hp > threat else 0, 1 if _dodge_ready(p) else 0, p.hp)
        if best_score is None or score > best_score:
            best_score = score
            best = i
    return best, (best_score[0] == 1 if best_score else False)


def _should_escape(obs: Observation) -> bool:
    """今の相手の最大打点でバトル場が落ちる可能性があり、かつ生き残れる控えがいるなら真"""
    state = obs.current
    if state is None:
        return False
    your_idx = state.yourIndex
    your_state = state.players[your_idx]
    opp_state = state.players[1 - your_idx]
    active = your_state.active[0] if your_state.active else None
    opp_active = opp_state.active[0] if opp_state.active else None
    if active is None or opp_active is None:
        return False
    threat = _best_attack_damage(opp_active, _get_card_data_cache(), _get_attack_cache())
    if threat < active.hp:
        return False
    _, survives = _find_best_bench_idx(your_state.bench, threat)
    return survives


def _select_switch_target(obs: Observation) -> list[int]:
    """にげる／いれかえ／強制交代後のベンチ選択。生存見込み > 特性発動可 > 残りHP"""
    state = obs.current
    options = obs.select.option
    if state is None or not options:
        return [0]
    your_idx = state.yourIndex
    your_state = state.players[your_idx]
    opp_state = state.players[1 - your_idx]
    opp_active = opp_state.active[0] if opp_state.active else None
    threat = _best_attack_damage(opp_active, _get_card_data_cache(), _get_attack_cache()) if opp_active else 0

    def score(i):
        opt = options[i]
        area = getattr(opt, "area", None)
        idx = getattr(opt, "index", None)
        if area == AreaType.BENCH and idx is not None and 0 <= idx < len(your_state.bench):
            p = your_state.bench[idx]
            return (1 if p.hp > threat else 0, 1 if _dodge_ready(p) else 0, p.hp)
        return (-1, -1, -1)

    best_i = max(range(len(options)), key=score)
    return [best_i]


# --- ダメージ計算対象の選択（ボスの指令） ---

def _select_boss_target(obs: Observation) -> list[int]:
    """KOできる相手を最優先、次点でエネルギーを多く抱えた脅威を指名する"""
    state = obs.current
    options = obs.select.option
    max_count = obs.select.maxCount
    if state is None or not options:
        return list(range(min(max_count, len(options))))
    your_idx = state.yourIndex
    opp_idx = 1 - your_idx
    your_state = state.players[your_idx]
    active = your_state.active[0] if your_state.active else None
    our_dmg = len(active.energies) * 30 if active is not None else 0

    def get_poke(opt):
        pi = opt.playerIndex if opt.playerIndex is not None else opp_idx
        ps = state.players[pi]
        if opt.area == AreaType.BENCH and opt.index is not None and 0 <= opt.index < len(ps.bench):
            return ps.bench[opt.index]
        if opt.area == AreaType.ACTIVE and ps.active:
            return ps.active[0]
        return None

    def score(i):
        p = get_poke(options[i])
        if p is None:
            return (9, 0, 0)
        can_ko = our_dmg > 0 and p.hp <= our_dmg
        return (0 if can_ko else 1, -len(p.energies or []), p.hp)

    ranked = sorted(range(len(options)), key=score)
    return ranked[:max_count]


def _should_play_boss(obs: Observation) -> bool:
    state = obs.current
    your_state = state.players[state.yourIndex]
    opp_state = state.players[1 - state.yourIndex]
    active = your_state.active[0] if your_state.active else None
    if active is None:
        return False
    our_dmg = len(active.energies) * 30
    if our_dmg <= 0:
        return False
    return any(p is not None and p.hp <= our_dmg for p in (opp_state.bench or []))


# --- デッキ／トラッシュからのポケモン探索 ---

def _select_deck_search_target(obs: Observation) -> list[int]:
    state = obs.current
    options = obs.select.option
    max_count = obs.select.maxCount
    deck = obs.select.deck or []
    your_state = state.players[state.yourIndex]
    counts = {cid: sum(1 for p in _board(your_state) if p.id == cid) for cid in _OUR_SPECIES}

    def score(i):
        idx = getattr(options[i], "index", None)
        if idx is None or not (0 <= idx < len(deck)):
            return (9, 9, i)
        cid = deck[idx].id
        have = counts.get(cid, 0)
        return (0 if have == 0 else 1, _SPECIES_PRIORITY.get(cid, 9), i)

    ranked = sorted(range(len(options)), key=score)
    return ranked[:max_count]


def _select_from_discard(obs: Observation) -> list[int]:
    """夜のタンカ等: 盤面に足りない自分のポケモン > 手札に無いエネルギー の順で回収"""
    state = obs.current
    options = obs.select.option
    max_count = obs.select.maxCount
    your_state = state.players[state.yourIndex]
    discard = your_state.discard or []
    counts = {cid: sum(1 for p in _board(your_state) if p.id == cid) for cid in _OUR_SPECIES}
    hand_energy = _hand_energy_count(your_state.hand)

    def score(i):
        idx = getattr(options[i], "index", None)
        if idx is None or not (0 <= idx < len(discard)):
            return (9, 9, i)
        cid = discard[idx].id
        if cid in counts:
            return (0 if counts[cid] == 0 else 2, _SPECIES_PRIORITY.get(cid, 9), i)
        if cid in _OUR_ENERGY and hand_energy == 0:
            return (1, 0, i)
        return (5, 0, i)

    ranked = sorted(range(len(options)), key=score)
    return ranked[:max_count]


def _select_heal_target(obs: Observation) -> list[int]:
    """ユカリ／ベルのまごころ等: 最もHPが減っている自分のポケモンを選ぶ"""
    state = obs.current
    options = obs.select.option
    your_state = state.players[state.yourIndex]

    def get_poke(opt):
        if opt.area == AreaType.ACTIVE:
            return your_state.active[0] if your_state.active else None
        if opt.area == AreaType.BENCH and opt.index is not None and 0 <= opt.index < len(your_state.bench):
            return your_state.bench[opt.index]
        return None

    def deficit(p):
        return (p.maxHp - p.hp) if p is not None else -1

    best_i = max(range(len(options)), key=lambda i: deficit(get_poke(options[i])))
    return [best_i]


def _route_card_selection(obs: Observation) -> list[int]:
    state = obs.current
    options = obs.select.option
    max_count = obs.select.maxCount
    if state is None or not options:
        return list(range(min(max_count, len(options))))

    opp_idx = 1 - state.yourIndex
    first = options[0]
    opt_pi = getattr(first, "playerIndex", None)
    opt_area = getattr(first, "area", None)

    if opt_pi == opp_idx and opt_area in (AreaType.BENCH, AreaType.ACTIVE):
        return _select_boss_target(obs)
    if opt_area == AreaType.DECK:
        return _select_deck_search_target(obs)
    if opt_area == AreaType.DISCARD:
        return _select_from_discard(obs)
    return list(range(min(max_count, len(options))))


# --- ATTACH（エネルギー／どうぐの貼り付け先） ---

def _energy_fit(cid: int, tgt) -> int:
    """数値が小さいほど良い貼り先。悪エネルギーはキチキギスの特性発動を最優先で満たす"""
    if cid == CID_PSYCHIC_ENERGY:
        return 0
    if cid == CID_DARKNESS_ENERGY:
        if tgt.id == CID_KICHIKIGISU:
            return -1 if not _dodge_ready(tgt) else 1
        return 3  # クレセリア/メロエッタには無駄になるので後回し
    return 2


def _best_attach_index(matches: list[int], options, obs: Observation):
    state = obs.current
    if state is None:
        return matches[0] if matches else None
    your_state = state.players[state.yourIndex]
    hand = your_state.hand or []
    active = your_state.active[0] if your_state.active else None
    bench = your_state.bench or []

    def target_poke(opt):
        if opt.inPlayArea == AreaType.ACTIVE:
            return active
        if opt.inPlayArea == AreaType.BENCH and opt.inPlayIndex is not None and 0 <= opt.inPlayIndex < len(bench):
            return bench[opt.inPlayIndex]
        return None

    def hand_cid(opt):
        if opt.area == AreaType.HAND and opt.index is not None and 0 <= opt.index < len(hand):
            return hand[opt.index].id
        return None

    energy_opts, tool_opts, fallback = [], [], []
    for idx in matches:
        opt = options[idx]
        cid = hand_cid(opt)
        tgt = target_poke(opt)
        if tgt is None or tgt.id not in _OUR_SPECIES:
            fallback.append(idx)
            continue
        if cid in _OUR_ENERGY:
            energy_count = len(tgt.energies or [])
            overload = 1 if (tgt is active and energy_count >= 6 and bench) else 0
            is_active = 1 if tgt is active else 0
            key = (_energy_fit(cid, tgt), overload, -is_active, energy_count)
            energy_opts.append((key, idx))
        elif cid in _OUR_TOOLS:
            if tgt.tools:
                continue  # 既にどうぐ装備済み
            rank = {CID_HERO_CAPE: 0, CID_LUCKY_HELMET: 1, CID_EMERGENCY_BOARD: 2}.get(cid, 9)
            is_active = 1 if tgt is active else 0
            tool_opts.append(((rank, -is_active), idx))
        else:
            fallback.append(idx)

    if energy_opts:
        energy_opts.sort(key=lambda x: x[0])
        return energy_opts[0][1]
    if tool_opts:
        tool_opts.sort(key=lambda x: x[0])
        return tool_opts[0][1]
    return fallback[0] if fallback else None


# --- PLAY（トレーナーズの使用判断） ---

def _should_play_yukari(obs: Observation) -> bool:
    return _hp_deficit(obs.current.players[obs.current.yourIndex]) >= 10


def _should_play_bell(obs: Observation) -> bool:
    return _has_low_hp(obs.current.players[obs.current.yourIndex])


def _should_play_judge(obs: Observation) -> bool:
    state = obs.current
    your_state = state.players[state.yourIndex]
    opp_state = state.players[1 - state.yourIndex]
    your_hand = len(your_state.hand or [])
    return opp_state.handCount >= 6 or (opp_state.handCount - your_hand) >= 3


def _should_search(obs: Observation) -> bool:
    return _board_count(obs.current.players[obs.current.yourIndex]) < 3


def _can_afford_discard(obs: Observation) -> bool:
    return len(obs.current.players[obs.current.yourIndex].hand or []) >= 3


def _should_play_stretcher(obs: Observation) -> bool:
    your_state = obs.current.players[obs.current.yourIndex]
    discard = your_state.discard or []
    if any(c.id in _OUR_SPECIES for c in discard) and _board_count(your_state) < 3:
        return True
    if any(c.id in _OUR_ENERGY for c in discard) and _hand_energy_count(your_state.hand) == 0:
        return True
    return False


def _should_retrieve_energy(obs: Observation) -> bool:
    your_state = obs.current.players[obs.current.yourIndex]
    discard_energy = sum(1 for c in (your_state.discard or []) if c.id in _OUR_ENERGY)
    return _hand_energy_count(your_state.hand) <= 1 and discard_energy >= 1


# 優先度: 数値が小さいほど優先（回復・退避などの生存行動を最優先）
def _play_priority(cid: int, obs: Observation):
    if cid in _OUR_SPECIES:
        return -1  # 手札の自分のポケモンはノーコストでベンチに出せるので無条件最優先
    if cid == CID_YUKARI and _should_play_yukari(obs):
        return 0
    if cid == CID_SWITCH_ITEM and _should_escape(obs):
        return 1
    if cid == CID_BELL and _should_play_bell(obs):
        return 2
    if cid == CID_BOSS and _should_play_boss(obs):
        return 3
    if cid == CID_POTION and _should_play_yukari(obs):  # HP不足があれば安いうちに使う
        return 4
    if cid == CID_POKE_PAD and _should_search(obs):
        return 5
    if cid == CID_ULTRA_BALL and _should_search(obs) and _can_afford_discard(obs):
        return 6
    if cid == CID_NIGHT_STRETCHER and _should_play_stretcher(obs):
        return 7
    if cid == CID_ENERGY_RETRIEVAL and _should_retrieve_energy(obs):
        return 8
    if cid == CID_JUDGE and _should_play_judge(obs):
        return 9
    if cid == CID_CHERENE:
        return 10
    return None


def _best_play_index(matches: list[int], options, obs: Observation):
    state = obs.current
    if state is None:
        return matches[0] if matches else None
    hand = state.players[state.yourIndex].hand or []
    scored = []
    for idx in matches:
        pos = options[idx].index
        if pos is None or not (0 <= pos < len(hand)):
            continue
        pr = _play_priority(hand[pos].id, obs)
        if pr is not None:
            scored.append((pr, idx))
    if not scored:
        return None
    scored.sort(key=lambda x: x[0])
    return scored[0][1]


# --- ATTACK（技の選択） ---

def _best_attack_index(matches: list[int], options, obs: Observation) -> int:
    """
    キチキギス: ワザは1つのみ(エナジーフェザー)なのでそのまま使う。
    クレセリア: 自身のエネルギーが3枚未満ならエネルギー加速(みなぎるひかり)を優先。
    メロエッタ: ベンチに要回復ポケモンがいれば回復(いやしのメロディ)を優先。
    """
    state = obs.current
    your_state = state.players[state.yourIndex]
    active = your_state.active[0] if your_state.active else None
    if active is None:
        return matches[0]
    card_cache = _get_card_data_cache()
    cd = card_cache.get(active.id)
    attacks = cd.attacks if cd else []
    id_to_idx = {options[i].attackId: i for i in matches}

    if active.id == CID_CRESELIA and len(attacks) >= 2:
        support_id, dmg_id = attacks[0], attacks[1]
        if support_id in id_to_idx and len(active.energies or []) < 3:
            return id_to_idx[support_id]
        if dmg_id in id_to_idx:
            return id_to_idx[dmg_id]

    if active.id == CID_MELOETTA and len(attacks) >= 2:
        heal_id, dmg_id = attacks[0], attacks[1]
        needs_heal = any(p.hp < p.maxHp for p in (your_state.bench or []) if p.id in _OUR_SPECIES)
        if heal_id in id_to_idx and needs_heal:
            return id_to_idx[heal_id]
        if dmg_id in id_to_idx:
            return id_to_idx[dmg_id]

    return matches[0]


# --- MAIN行動の優先度 ---

def _select_main_action(obs: Observation) -> list[int]:
    options = obs.select.option
    priority_order = [
        OptionType.ATTACH,
        OptionType.PLAY,
        OptionType.ABILITY,
        OptionType.ATTACK,
        OptionType.RETREAT,
        OptionType.END,
    ]
    for opt_type in priority_order:
        matches = [i for i, o in enumerate(options) if o.type == opt_type]
        if not matches:
            continue
        if opt_type == OptionType.ATTACH:
            idx = _best_attach_index(matches, options, obs)
            if idx is not None:
                return [idx]
            continue
        if opt_type == OptionType.PLAY:
            idx = _best_play_index(matches, options, obs)
            if idx is not None:
                return [idx]
            continue
        if opt_type == OptionType.ABILITY:
            return [matches[0]]
        if opt_type == OptionType.ATTACK:
            return [_best_attack_index(matches, options, obs)]
        if opt_type == OptionType.RETREAT:
            if _should_escape(obs):
                return [matches[0]]
            continue
        return [matches[0]]  # END
    return [len(options) - 1]


# --- YES/NO ---

def _select_yes_no(obs: Observation) -> list[int]:
    options = obs.select.option
    context = obs.select.context

    def _yes():
        idx = [i for i, o in enumerate(options) if o.type == OptionType.YES]
        return idx[:1] if idx else [0]

    def _no():
        idx = [i for i, o in enumerate(options) if o.type == OptionType.NO]
        return idx[:1] if idx else [len(options) - 1]

    if context == SelectContext.IS_FIRST:
        # 後攻を選ぶ: 先攻は初手ドロー無し＆その番は攻撃不可というハンデを負うため、
        # 後攻を取って確実に1ドロー多い状態からスタートし、相手の先制攻撃も1ターン遅らせる。
        return _no()
    if context in (
        SelectContext.MULLIGAN,
        SelectContext.ACTIVATE,
        SelectContext.COIN_HEAD,
        SelectContext.FIRST_EFFECT,
    ):
        return _yes()
    return _yes()


# --- メインエージェント ---

def agent(obs_dict: dict) -> list[int]:
    obs: Observation = to_observation_class(obs_dict)

    if obs.select is None:
        return read_deck_csv()

    options = obs.select.option
    max_count = obs.select.maxCount
    sel_type = obs.select.type

    if sel_type == SelectType.MAIN:
        return _select_main_action(obs)

    if sel_type == SelectType.CARD:
        ctx = obs.select.context
        if ctx == SelectContext.DISCARD:
            return _select_discard_for_ultraball(obs)
        if ctx == SelectContext.HEAL:
            return _select_heal_target(obs)
        if ctx in (SelectContext.SWITCH, SelectContext.TO_ACTIVE):
            return _select_switch_target(obs)
        return _route_card_selection(obs)

    if sel_type == SelectType.YES_NO:
        return _select_yes_no(obs)

    if sel_type == SelectType.COUNT:
        best = max(range(len(options)), key=lambda i: (options[i].number or 0))
        return [best]

    if max_count == 0:
        return []
    return list(range(min(max_count, len(options))))


# --- ハイパーボールの手札トラッシュ選択 ---

# 数値が大きいほど先に捨てる（=価値が低い）
_KEEP_PRIORITY = {
    CID_KICHIKIGISU: 0, CID_CRESELIA: 0, CID_MELOETTA: 0,
    CID_PSYCHIC_ENERGY: 1, CID_DARKNESS_ENERGY: 1,
    CID_YUKARI: 2,
    CID_HERO_CAPE: 2, CID_LUCKY_HELMET: 3, CID_EMERGENCY_BOARD: 3,
}


def _select_discard_for_ultraball(obs: Observation) -> list[int]:
    state = obs.current
    options = obs.select.option
    max_count = obs.select.maxCount
    your_state = state.players[state.yourIndex]
    hand = your_state.hand or []

    def score(i):
        idx = getattr(options[i], "index", None)
        if idx is None or not (0 <= idx < len(hand)):
            return -1
        cid = hand[idx].id
        return -_KEEP_PRIORITY.get(cid, 9)  # 優先度が低い(価値が低い)ものから捨てる

    ranked = sorted(range(len(options)), key=score)
    return ranked[:max_count]
