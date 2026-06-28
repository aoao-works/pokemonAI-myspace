import os

from cg.api import (
    Observation, SelectType, SelectContext, OptionType, AreaType, CardType,
    to_observation_class, all_attack, all_card_data,
)


def read_deck_csv() -> list[int]:
    """deck.csv を読み込んで60枚のカードIDリストを返す"""
    file_path = "deck.csv"
    if not os.path.exists(file_path):
        file_path = "/kaggle_simulations/agent/" + file_path
    with open(file_path, "r") as file:
        csv = file.read().split("\n")
    return [int(csv[i]) for i in range(60)]


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


# --- カードID定数 ---
# 重要: all_card_data() / all_attack() は「英語名」を返すため、日本語名での
# 照合は一切一致しない。デッキのカードは言語非依存な「カードID」で識別する。
# （ID↔名前は基礎情報/JP_Card_Data.csv より。deck.csv の20種）

CID_MAKUNOSHITA        = 673   # マクノシタ
CID_HARITEYAMA         = 674   # ハリテヤマ
CID_LUNATONE           = 675   # ルナトーン（特性ルナサイクル）
CID_SOLROCK            = 676   # ソルロック（コスモビーム=弱点計算しない）
CID_RIOLU              = 677   # リオル
CID_MEGA_LUCARIO       = 678   # メガルカリオex（はどうづき/メガブレイブ）
CID_NIGHT_STRETCHER    = 1097  # 夜のタンカ
CID_ULTRA_BALL         = 1121  # ハイパーボール
CID_SWITCH             = 1123  # ポケモンいれかえ
CID_POWER_PROTEIN      = 1141  # パワープロテイン
CID_FIGHT_GONG         = 1142  # ファイトゴング
CID_POKE_PAD           = 1152  # ポケパッド
CID_MAX_BELT           = 1158  # マキシマムベルト
CID_BALLOON            = 1174  # ふうせん
CID_BOSS               = 1182  # ボスの指令
CID_TAKESHI            = 1210  # タケシのスカウト
CID_JUDGE              = 1213  # ジャッジマン
CID_LILLIE             = 1227  # リーリエの決心
CID_GRAVITY_MOUNTAIN   = 1252  # グラビティーマウンテン
CID_BASIC_FIGHT_ENERGY = 6     # 基本【闘】エネルギー

# 条件付き判断が必要なカード（ID）
_CONDITIONAL_CARDS: frozenset[int] = frozenset({
    CID_MAX_BELT, CID_POWER_PROTEIN, CID_GRAVITY_MOUNTAIN,
})

# 弱点・抵抗を計算しないポケモン（ID）。ソルロックのコスモビームが該当
# （技名照合は英語のため、技を持つポケモンID単位で扱う。ソルロックの技はコスモビームのみ）
_NO_WEAKNESS_POKEMON: frozenset[int] = frozenset({CID_SOLROCK})

# ポケモンID別エネルギー上限オーバーライド（技コストデータより優先）
_ENERGY_CAP_OVERRIDE: dict[int, int] = {
    CID_LUNATONE: 0,   # 特性専用、エネルギー不要
    CID_SOLROCK:  1,   # コスモビームの1枚のみ
}

# エネルギーアタッチ優先度（数値が小さいほど優先）
_ENERGY_ATTACH_PRIORITY: dict[int, int] = {
    CID_SOLROCK:      0,   # 条件付き最優先（_best_attach_index内で条件判定）
    CID_MEGA_LUCARIO: 1,
    CID_RIOLU:        2,
    CID_HARITEYAMA:   3,
    CID_MAKUNOSHITA:  4,
}

# ふうせん貼り先優先度
_BALLOON_TARGET_PRIORITY: dict[int, int] = {
    CID_MAKUNOSHITA:  0,
    CID_HARITEYAMA:   1,
    CID_LUNATONE:     2,
    CID_SOLROCK:      3,
    CID_MEGA_LUCARIO: 4,
    CID_RIOLU:        5,
}

# マキシマムベルト貼り先優先度
_MAX_BELT_TARGET_PRIORITY: dict[int, int] = {
    CID_MEGA_LUCARIO: 0,
    CID_RIOLU:        1,
    CID_HARITEYAMA:   2,
    CID_MAKUNOSHITA:  3,
    CID_SOLROCK:      4,
}

# サポーター（ID）
_SUPPORTER_TAKESHI = CID_TAKESHI
_SUPPORTER_LILLIE  = CID_LILLIE
_SUPPORTER_JUDGE   = CID_JUDGE
_SUPPORTER_BOSS    = CID_BOSS
_SUPPORTER_IDS: frozenset[int] = frozenset({
    CID_TAKESHI, CID_LILLIE, CID_JUDGE, CID_BOSS,
})

# 目標盤面ポケモン（ID: 最大在場数）
_FIELD_TARGETS: dict[int, int] = {
    CID_RIOLU:       2,
    CID_SOLROCK:     1,
    CID_LUNATONE:    1,
    CID_MAKUNOSHITA: 1,
}

# サーチ優先度（ポケパッド・ハイパーボール等）
_SEARCH_PRIORITY: dict[int, int] = {
    CID_SOLROCK:      0,
    CID_LUNATONE:     0,
    CID_RIOLU:        1,
    CID_MEGA_LUCARIO: 2,
    CID_MAKUNOSHITA:  3,
    CID_HARITEYAMA:   4,
}

# にげる例外ポケモン（特性専用、バトル場に出さない）
_RETREAT_EXCEPTIONS: frozenset[int] = frozenset({CID_SOLROCK, CID_LUNATONE})

# ターン内状態追跡
# state.supporterPlayed / state.energyAttached はエンジン提供済みのため不要
# 「非ボスサポーターを使ったか」「ルナサイクルを使ったか」のみグローバルで管理
_last_seen_turn: int = -1
_non_boss_supporter_played: bool = False
_luna_cycle_used: bool = False


# --- ヘルパー ---

def _best_attack_damage(pokemon, card_cache: dict, attack_cache: dict) -> int:
    """そのポケモンが持つ技のうち最大ダメージ値を返す"""
    cd = card_cache.get(pokemon.id)
    if cd is None:
        return 0
    return max(
        (attack_cache[aid].damage for aid in cd.attacks if aid in attack_cache),
        default=0,
    )


def _max_energy_needed(pokemon, card_cache: dict, attack_cache: dict) -> int:
    """そのポケモンの全技を通じて最大のエネルギーコスト数を返す。ID別上限が優先。"""
    if pokemon.id in _ENERGY_CAP_OVERRIDE:
        return _ENERGY_CAP_OVERRIDE[pokemon.id]
    cd = card_cache.get(pokemon.id)
    if cd is None:
        return 0
    return max(
        (len(attack_cache[aid].energies) for aid in cd.attacks if aid in attack_cache),
        default=0,
    )


def _poke_name(poke, card_cache: dict) -> str:
    """ポケモンのカード名を返す（不明なら空文字）。※照合には使わず表示/デバッグ用"""
    cd = card_cache.get(poke.id)
    return cd.name if cd else ""


def _is_ex_pokemon(poke, card_cache: dict) -> bool:
    """exポケモンか判定（言語非依存に CardData.ex / megaEx フィールドで判定）"""
    cd = card_cache.get(poke.id)
    return cd is not None and (bool(cd.ex) or bool(cd.megaEx))


def _count_field_pokemon(your_state, card_cache: dict) -> dict[int, int]:
    """自分のバトル場+ベンチのポケモンをカードIDでカウント"""
    counts: dict[int, int] = {}
    for poke in list(your_state.active) + list(your_state.bench):
        counts[poke.id] = counts.get(poke.id, 0) + 1
    return counts


def _takeshi_needed(obs: Observation) -> bool:
    """タケシのスカウトが必要な盤面か（目標ポケモンが3体以上欠けている）"""
    state = obs.current
    if state is None:
        return False
    your_state = state.players[state.yourIndex]
    card_cache = _get_card_data_cache()
    counts  = _count_field_pokemon(your_state, card_cache)
    present = sum(min(counts.get(cid, 0), maxn) for cid, maxn in _FIELD_TARGETS.items())
    total   = sum(_FIELD_TARGETS.values())
    return present <= total - 3


def _should_play_boss(obs: Observation) -> bool:
    """ボスの指令を使うべき状況か（バトル場を倒せず、ベンチに倒せるターゲットがある）"""
    state = obs.current
    if state is None:
        return True
    your_idx   = state.yourIndex
    opp_idx    = 1 - your_idx
    your_state = state.players[your_idx]
    opp_state  = state.players[opp_idx]
    card_cache   = _get_card_data_cache()
    attack_cache = _get_attack_cache()

    your_active = your_state.active[0] if your_state.active else None
    opp_active  = opp_state.active[0] if opp_state.active else None

    if your_active is None or len(your_active.energies) == 0:
        return False

    best_dmg = _best_attack_damage(your_active, card_cache, attack_cache)

    if opp_active is not None and opp_active.hp <= best_dmg:
        return False  # バトル場を倒せる → ボス不要

    return any(p.hp <= best_dmg for p in opp_state.bench)


def _supporter_sort_key(card_id: int, obs: Observation) -> int:
    """サポーターの使用優先度（小さいほど優先、999=今ターンは使わない）"""
    state = obs.current
    opp_hand = 0
    if state is not None:
        opp_state = state.players[1 - state.yourIndex]
        opp_hand  = len(getattr(opp_state, 'hand', []) or [])

    if card_id == _SUPPORTER_TAKESHI:
        return 0 if _takeshi_needed(obs) else 4
    if card_id == _SUPPORTER_JUDGE:
        return 1 if opp_hand >= 10 else 3
    if card_id == _SUPPORTER_LILLIE:
        return 2 if _should_play_lillie(obs) else 999  # 手札充実時は温存
    if card_id == _SUPPORTER_BOSS:
        return 6 if _should_play_boss(obs) else 999
    return 5  # 未知のサポーター


def _should_play_named_card(card_id: int, obs: Observation) -> bool:
    """
    特定カードを今使うべきかを相手HP・自Pokémon状態で判定する。

    マキシマムベルト / パワープロテイン:
        自分のベストダメージ + 30 で相手バトルポケモンをきぜつできる場合に使用。
        パワープロテインは追加で自分HP > 20 が必要（ダメカン2個で即倒れない）。

    グラビティマウンテン:
        自分のバトル場またはベンチにたねポケモンが1体でもいれば使用。
    """
    state = obs.current
    if state is None:
        return True

    your_idx = state.yourIndex
    opp_idx = 1 - your_idx
    your_state = state.players[your_idx]
    opp_state  = state.players[opp_idx]
    your_active = your_state.active[0] if your_state.active else None
    opp_active  = opp_state.active[0]  if opp_state.active  else None

    attack_cache = _get_attack_cache()
    card_cache   = _get_card_data_cache()

    if card_id == CID_MAX_BELT:
        if your_active is None or opp_active is None:
            return False
        best_dmg = _best_attack_damage(your_active, card_cache, attack_cache)
        # +30 で相手を倒せる、またはきぜつ圏内に入れる場合に使う
        return opp_active.hp <= best_dmg + 30

    if card_id == CID_POWER_PROTEIN:
        if your_active is None or opp_active is None:
            return False
        # ダメカン2個（20ダメージ）で自分がきぜつしないこと
        if your_active.hp <= 20:
            return False
        best_dmg = _best_attack_damage(your_active, card_cache, attack_cache)
        return opp_active.hp <= best_dmg + 30

    if card_id == CID_GRAVITY_MOUNTAIN:
        # バトル場・ベンチにたねポケモンがいれば恩恵あり（basic は言語非依存フィールド）
        all_pokemon = list(your_state.active) + list(your_state.bench)
        return any(
            card_cache.get(p.id) is not None and card_cache.get(p.id).basic
            for p in all_pokemon
        )
        # 注: 相手妨害スタジアムの上書きは英語名照合不可のため Phase 2 へ保留

    return True  # 未知のカードはデフォルトで使用


# --- 補充/サーチ/交代グッズの使用条件（既存の条件分岐を補完、greedyな使いすぎを抑制） ---
# 方針: ドロー/サーチ系は「手札の質・盤面の不足」で判断（人間の条件分岐）。
#       ポケモンいれかえは盤面の交代トレードオフなので V で判断（にげると同性質）。

_ITEM_POKEPAD   = CID_POKE_PAD
_ITEM_FIGHTGONG = CID_FIGHT_GONG
_ITEM_HYPERBALL = CID_ULTRA_BALL
_ITEM_SWITCH    = CID_SWITCH
_POKEMON_SEARCH_ITEMS = frozenset({_ITEM_POKEPAD, _ITEM_FIGHTGONG})


def _need_basic_target(obs: Observation) -> bool:
    """目標たねポケモン（リオル等）が場で上限未満かつ手札に無い → サーチの価値あり"""
    state = obs.current
    if state is None:
        return True
    your_state = state.players[state.yourIndex]
    card_cache = _get_card_data_cache()
    field = _count_field_pokemon(your_state, card_cache)
    hand_ids = {c.id for c in (your_state.hand or [])}
    for cid, maxn in _FIELD_TARGETS.items():
        if field.get(cid, 0) < maxn and cid not in hand_ids:
            return True
    return False


def _need_mega_lucario(obs: Observation) -> bool:
    """リオルが場にいて、メガルカリオexが手札にも場にも無い → 進化先サーチの価値あり"""
    state = obs.current
    if state is None:
        return False
    your_state = state.players[state.yourIndex]
    card_cache = _get_card_data_cache()
    field = _count_field_pokemon(your_state, card_cache)
    if field.get(CID_RIOLU, 0) <= 0 or field.get(CID_MEGA_LUCARIO, 0) > 0:
        return False
    return not any(c.id == CID_MEGA_LUCARIO for c in (your_state.hand or []))


def _should_play_lillie(obs: Observation) -> bool:
    """
    リーリエの決心（手札を山に戻して6枚／サイド6なら8枚引く）を使う価値があるか。
      - 序盤(サイド残6): 8枚ドローで強力 → 使う
      - 手札が少ない(≤4): ドローが純増 → 使う
      - 手札にエネルギーが無く手張り前: 掘りに行く → 使う
      - それ以外（手札が充実）: 良い手札を流したくない → 温存
    """
    state = obs.current
    if state is None:
        return True
    your_state = state.players[state.yourIndex]
    hand = your_state.hand or []
    if len(your_state.prize) >= 6:
        return True
    if len(hand) <= 4:
        return True
    card_cache = _get_card_data_cache()
    has_energy = any(
        card_cache.get(c.id) is not None
        and card_cache[c.id].cardType in (CardType.BASIC_ENERGY, CardType.SPECIAL_ENERGY)
        for c in hand
    )
    return bool(not has_energy and not state.energyAttached)


def _should_play_switch_item(obs: Observation) -> bool:
    """ポケモンいれかえ（エネ不要の交代）: V(交代後) > V(現状) なら使う（にげるコスト0）"""
    state = obs.current
    if state is None:
        return False
    your_idx = state.yourIndex
    your_state = state.players[your_idx]
    card_cache = _get_card_data_cache()
    active = your_state.active[0] if your_state.active else None
    if active is None:
        return False
    cand, _ = _best_bench_switch_candidate(state, your_idx)
    if cand is None:
        return False
    if active.id in _RETREAT_EXCEPTIONS:
        return True
    stay_v   = _evaluate(state, your_idx, active_override=active)
    switch_v = _evaluate(state, your_idx, active_override=cand)
    return switch_v > stay_v


def _should_play_item(card_id: int, obs: Observation) -> bool:
    """汎用グッズの使用可否。サーチ/補充/交代系は条件で温存判断、その他は常に使う。"""
    if card_id in _POKEMON_SEARCH_ITEMS:
        return _need_basic_target(obs)
    if card_id == _ITEM_HYPERBALL:
        return _need_basic_target(obs) or _need_mega_lucario(obs)
    if card_id == _ITEM_SWITCH:
        return _should_play_switch_item(obs)
    return True


# --- 特性後のアタッチ先選択 ---

def _select_attach_target(obs: Observation) -> list[int]:
    """
    CARD選択 / ATTACH_FROM コンテキスト専用。
    ルカリオ等の能力でエネルギーアタッチ先ポケモンを選ぶ際に呼ばれる。

    エネルギーが不足しているポケモンだけを選択し、過剰アタッチを防ぐ。
    アクティブ優先 → ベンチ順。
    min_count を満たせない場合のみ充足済みポケモンで補完する。
    """
    state = obs.current
    options = obs.select.option
    max_count = obs.select.maxCount
    min_count = obs.select.minCount

    if state is None or max_count == 0:
        return list(range(min(max_count, len(options))))

    your_idx     = state.yourIndex
    card_cache   = _get_card_data_cache()
    attack_cache = _get_attack_cache()

    need_active: list[int] = []
    need_bench:  list[int] = []
    full:        list[int] = []

    for i, opt in enumerate(options):
        pi = opt.playerIndex if opt.playerIndex is not None else your_idx
        ps = state.players[pi]

        poke = None
        if opt.area == AreaType.ACTIVE:
            poke = ps.active[0] if ps.active else None
        elif opt.area == AreaType.BENCH and opt.index is not None:
            bench = ps.bench
            if 0 <= opt.index < len(bench):
                poke = bench[opt.index]

        if poke is None:
            full.append(i)
            continue

        needed  = _max_energy_needed(poke, card_cache, attack_cache)
        current = len(poke.energies)
        if needed > 0 and current < needed:
            if opt.area == AreaType.ACTIVE:
                need_active.append(i)
            else:
                need_bench.append(i)
        else:
            full.append(i)

    candidates = (need_active + need_bench)[:max_count]

    # min_count に届かない場合は充足済みで補完（エンジン要求を満たす）
    if len(candidates) < min_count:
        shortage = min_count - len(candidates)
        candidates += full[:shortage]

    return candidates


# --- CARD 選択ハンドラ ---

def _select_boss_target(obs: Observation) -> list[int]:
    """
    ボスの指令 / どすこいキャッチャー のターゲット選択。
    優先度: キチキギスex > KO可能exポケモン > KO可能ポケモン > exポケモン(エネルギー多) > その他
    """
    state = obs.current
    options = obs.select.option
    max_count = obs.select.maxCount

    if state is None or not options:
        return list(range(min(max_count, len(options))))

    your_idx     = state.yourIndex
    opp_idx      = 1 - your_idx
    your_state   = state.players[your_idx]
    card_cache   = _get_card_data_cache()
    attack_cache = _get_attack_cache()

    your_active = your_state.active[0] if your_state.active else None
    best_dmg = _best_attack_damage(your_active, card_cache, attack_cache) if your_active else 0

    def get_poke(opt):
        pi  = getattr(opt, 'playerIndex', opp_idx)
        ps  = state.players[pi]
        if opt.area == AreaType.BENCH and opt.index is not None and 0 <= opt.index < len(ps.bench):
            return ps.bench[opt.index]
        if opt.area == AreaType.ACTIVE and ps.active:
            return ps.active[0]
        return None

    def sort_key(i):
        poke = get_poke(options[i])
        if poke is None:
            return (99, 0)
        is_ex  = _is_ex_pokemon(poke, card_cache)
        can_ko = poke.hp <= best_dmg
        energy = len(poke.energies)
        # 注: キチキギスex等の相手特定カードの最優先は英語名照合不可のため Phase 2 へ保留。
        #     現状は「KO可能ex > KO可能 > ex(エネ多) > その他」で優先。
        if can_ko and is_ex:
            return (-2, -energy)
        if can_ko:
            return (-1, -energy)
        if is_ex:
            return (1, -energy)
        return (2, -energy)

    sorted_opts = sorted(range(len(options)), key=sort_key)
    return sorted_opts[:max_count]


def _select_search_target(obs: Observation) -> list[int]:
    """
    デッキ・トラッシュからのサーチ効果のターゲット選択。
    優先度: ソルロック・ルナトーン > リオル > メガルカリオex > マクノシタ > ハリテヤマ
    在場数が上限に達したカードは優先度を下げる。
    """
    state = obs.current
    options = obs.select.option
    max_count = obs.select.maxCount

    if state is None or not options:
        return list(range(min(max_count, len(options))))

    your_idx   = state.yourIndex
    your_state = state.players[your_idx]
    card_cache = _get_card_data_cache()
    field_counts = _count_field_pokemon(your_state, card_cache)

    def get_card_data(opt):
        # 直接 ID フィールドを持つ場合
        for attr in ('id', 'cardId'):
            cid = getattr(opt, attr, None)
            if cid is not None:
                return card_cache.get(cid)
        # DECK/DISCARD 領域で公開されていれば引ける
        idx = getattr(opt, 'index', None)
        for state_attr in ('deck', 'discard'):
            pile = getattr(your_state, state_attr, None)
            if pile is not None and idx is not None and 0 <= idx < len(pile):
                card_obj = pile[idx]
                cid = getattr(card_obj, 'id', None) or getattr(card_obj, 'cardId', None)
                return card_cache.get(cid) if cid else None
        return None

    scored: list[tuple[int, int]] = []
    for i, opt in enumerate(options):
        cd   = get_card_data(opt)
        cid  = cd.cardId if cd else -1
        prio = _SEARCH_PRIORITY.get(cid, 20)
        if field_counts.get(cid, 0) >= _FIELD_TARGETS.get(cid, 99):
            prio += 30   # 既に在場上限 → 優先度下げ
        scored.append((prio, i))

    scored.sort()
    return [i for _, i in scored[:max_count]]


def _select_discard_target(obs: Observation) -> list[int]:
    """
    DISCARD コンテキスト: 手札から捨てるカードを選ぶ（ハイパーボール等）。

    保持優先度（高いほど捨てない）:
      マキシマムベルト > リーリエの決心(手4+) > ジャッジマン(手4+,リーリエなし)
      > 夜のタンカ(トラッシュに回収先あり) > サポーター > 必要ポケモン
      > ツール/スタジアム > アイテム > エネルギー

    はどうづき使用予定 + トラッシュエネ≤2 の場合はエネルギーを最優先で捨てる。
    """
    state = obs.current
    options = obs.select.option
    max_count = obs.select.maxCount

    if state is None or not options:
        return list(range(min(max_count, len(options))))

    your_idx = state.yourIndex
    your_state = state.players[your_idx]
    card_cache = _get_card_data_cache()
    attack_cache = _get_attack_cache()

    hand = your_state.hand or []
    discard_pile = your_state.discard

    # トラッシュのエネルギー枚数
    trash_energy_count = sum(
        1 for c in discard_pile
        if card_cache.get(c.id) is not None
        and card_cache[c.id].cardType in (CardType.BASIC_ENERGY, CardType.SPECIAL_ENERGY)
    )

    # バトル場がメガルカリオex（はどうづき＝トラッシュ闘エネ参照技を持つ）か
    your_active = your_state.active[0] if your_state.active else None
    active_has_hadoudzuki = your_active is not None and your_active.id == CID_MEGA_LUCARIO

    # エネルギーを優先廃棄すべき状況か
    prioritize_energy_discard = active_has_hadoudzuki and trash_energy_count <= 2

    # 手札のカードIDセット
    hand_ids: set[int] = {c.id for c in hand}
    has_lillie = CID_LILLIE in hand_ids

    # 夜のタンカ: トラッシュにポケモンまたはエネルギーがあれば価値あり → 保持
    night_stretcher_valuable = False
    if CID_NIGHT_STRETCHER in hand_ids:
        for c in discard_pile:
            cd = card_cache.get(c.id)
            if cd and cd.cardType in (
                CardType.POKEMON, CardType.BASIC_ENERGY, CardType.SPECIAL_ENERGY
            ):
                night_stretcher_valuable = True
                break

    field_counts = _count_field_pokemon(your_state, card_cache)

    def discard_score(i: int) -> tuple:
        """スコアが小さいほど捨てやすい"""
        opt = options[i]
        idx = getattr(opt, 'index', None)
        if idx is None or not (0 <= idx < len(hand)):
            return (50, i)
        cid = hand[idx].id
        cd = card_cache.get(cid)
        if cd is None:
            return (40, i)
        ctype = cd.cardType

        if cid == CID_MAX_BELT:
            return (99, i)
        if cid == CID_LILLIE and len(hand) >= 4:
            return (90, i)
        if cid == CID_JUDGE and not has_lillie and len(hand) >= 4:
            return (85, i)
        if cid == CID_NIGHT_STRETCHER and night_stretcher_valuable:
            return (80, i)

        if ctype in (CardType.BASIC_ENERGY, CardType.SPECIAL_ENERGY):
            return (0, i) if prioritize_energy_discard else (20, i)

        if ctype == CardType.POKEMON:
            if field_counts.get(cid, 0) >= _FIELD_TARGETS.get(cid, 1):
                return (10, i)   # 在場上限達成 → 捨てやすい
            return (55, i)       # まだ必要 → 保持

        if ctype == CardType.ITEM:
            return (25, i)
        if ctype in (CardType.TOOL, CardType.STADIUM):
            return (30, i)
        if ctype == CardType.SUPPORTER:
            return (60, i)

        return (35, i)

    scored = sorted(range(len(options)), key=discard_score)
    return scored[:max_count]


def _select_from_discard(obs: Observation) -> list[int]:
    """
    トラッシュからカードを選ぶ（夜のタンカ等）際のターゲット選択。

    優先度:
    ① 盤面に不足している目標ポケモン（リオル×2・ソルロック・ルナトーン・マクノシタ）
    ② メガルカリオex（リオル在場 + 手札にメガルカリオexなし）
    ③ エネルギー（このターン手張りなし + 手札にエネルギーなし）
    ④ その他（低優先度）
    """
    state = obs.current
    options = obs.select.option
    max_count = obs.select.maxCount

    if state is None or not options:
        return list(range(min(max_count, len(options))))

    your_idx = state.yourIndex
    your_state = state.players[your_idx]
    card_cache = _get_card_data_cache()

    # 手札の状況確認
    hand_ids: set[int] = set()
    has_energy_in_hand = False
    for c in (your_state.hand or []):
        hand_ids.add(c.id)
        cd = card_cache.get(c.id)
        if cd and cd.cardType in (CardType.BASIC_ENERGY, CardType.SPECIAL_ENERGY):
            has_energy_in_hand = True

    field_counts = _count_field_pokemon(your_state, card_cache)
    riolu_on_field = field_counts.get(CID_RIOLU, 0) > 0
    mega_lucario_in_hand = CID_MEGA_LUCARIO in hand_ids

    # エネルギーを回収すべきか（条件③: 手張りなし + 手札エネなし）
    need_energy = not state.energyAttached and not has_energy_in_hand

    discard = your_state.discard or []

    def score(i: int) -> tuple:
        opt = options[i]
        idx = getattr(opt, 'index', None)
        if idx is None or not (0 <= idx < len(discard)):
            return (99, i)
        cid = discard[idx].id
        cd = card_cache.get(cid)
        if cd is None:
            return (90, i)
        ctype = cd.cardType

        # ① 盤面に不足している目標ポケモン
        if cid in _FIELD_TARGETS and field_counts.get(cid, 0) < _FIELD_TARGETS[cid]:
            return (_SEARCH_PRIORITY.get(cid, 20), i)

        # ② メガルカリオex（リオル在場 + 手札にない）
        if cid == CID_MEGA_LUCARIO and riolu_on_field and not mega_lucario_in_hand:
            return (5, i)

        # ③ エネルギー（手張りなし + 手札エネなし）
        if ctype in (CardType.BASIC_ENERGY, CardType.SPECIAL_ENERGY) and need_energy:
            return (6, i)

        return (50, i)

    scored = sorted(range(len(options)), key=score)
    return scored[:max_count]


def _route_card_selection(obs: Observation) -> list[int]:
    """
    CARD 選択のコンテキストをオプションの特徴から推定して適切なハンドラに振り分ける。
    - DISCARD → 捨て先優先度ロジック（ハイパーボール等）
    - 相手ポケモン選択 → ボスの指令 / どすこいキャッチャー
    - デッキ / トラッシュ選択 → サーチ系
    - その他 → 先頭 maxCount 個
    """
    state = obs.current
    options = obs.select.option
    max_count = obs.select.maxCount

    if state is None or not options:
        return list(range(min(max_count, len(options))))

    # DISCARD: 手札から捨てるカードを選ぶ（ハイパーボール等）
    if obs.select.context == SelectContext.DISCARD:
        return _select_discard_target(obs)

    your_idx = state.yourIndex
    opp_idx  = 1 - your_idx
    first    = options[0]
    opt_pi   = getattr(first, 'playerIndex', None)
    opt_area = getattr(first, 'area', None)

    # 相手のポケモンを選ぶ → ボスの指令 / どすこいキャッチャー
    if opt_pi == opp_idx and opt_area in (AreaType.BENCH, AreaType.ACTIVE):
        return _select_boss_target(obs)

    # デッキから選ぶ → サーチ系
    if opt_area == AreaType.DECK:
        return _select_search_target(obs)

    # トラッシュから選ぶ（夜のタンカ等）→ トラッシュ回収ロジック
    if opt_area == AreaType.DISCARD:
        return _select_from_discard(obs)

    # デフォルト
    count = min(max_count, len(options))
    return list(range(count))


# --- MAIN アクション選択ヘルパー ---

def _best_attack_index(matches: list[int], options) -> int:
    """最大ダメージのATTACKオプションのインデックスを返す"""
    cache = _get_attack_cache()
    best_idx = matches[0]
    best_damage = -1
    for idx in matches:
        attack_id = options[idx].attackId
        if attack_id is not None and attack_id in cache:
            dmg = cache[attack_id].damage
            if dmg > best_damage:
                best_damage = dmg
                best_idx = idx
    return best_idx


def _best_attach_index(matches: list[int], options, obs: Observation) -> int | None:
    """
    アタッチ先を決定する。
    ・エネルギーカード: 上限チェック後、ポケモン名ベースの優先度でソート
      - ソルロック最優先条件: 相手HP70以下 + ルナトーン・ソルロック在場
      - 通常優先度: メガルカリオex > リオル > ハリテヤマ > マクノシタ
      - 同優先度内はエネルギー枚数の少ない方を優先
    ・ツールカード: カード別の貼り先優先度リストでソート
    ・有効なアタッチ先がなければ None を返す（次の優先度へ）
    """
    state = obs.current
    if state is None:
        for idx in matches:
            if options[idx].inPlayArea == AreaType.ACTIVE:
                return idx
        return matches[0] if matches else None

    your_idx     = state.yourIndex
    opp_idx      = 1 - your_idx
    your_state   = state.players[your_idx]
    opp_state    = state.players[opp_idx]
    card_cache   = _get_card_data_cache()
    attack_cache = _get_attack_cache()

    def get_target(opt):
        if opt.inPlayArea == AreaType.ACTIVE:
            return your_state.active[0] if your_state.active else None
        if opt.inPlayArea == AreaType.BENCH and opt.inPlayIndex is not None:
            bench = your_state.bench
            if 0 <= opt.inPlayIndex < len(bench):
                return bench[opt.inPlayIndex]
        return None

    # ソルロック最優先条件: 相手HP70以下 + ルナトーン・ソルロックが自分の場に存在
    opp_active = opp_state.active[0] if opp_state.active else None
    your_all   = list(your_state.active) + list(your_state.bench)
    solrock_priority = (
        opp_active is not None and opp_active.hp <= 70
        and any(p.id == CID_LUNATONE for p in your_all)
        and any(p.id == CID_SOLROCK for p in your_all)
    )

    # (sort_key, idx)
    energy_candidates: list[tuple[tuple, int]] = []
    tool_candidates:   list[tuple[int, int]]   = []
    fallback:          list[int]               = []

    for idx in matches:
        opt    = options[idx]
        target = get_target(opt)

        card_id = None
        if opt.area == AreaType.HAND and opt.index is not None:
            hand = your_state.hand
            if hand and 0 <= opt.index < len(hand):
                card_id = hand[opt.index].id

        if card_id is not None:
            cd = card_cache.get(card_id)
            if cd is not None and cd.cardType in (CardType.BASIC_ENERGY, CardType.SPECIAL_ENERGY):
                if target is not None:
                    needed  = _max_energy_needed(target, card_cache, attack_cache)
                    current = len(target.energies)
                    if needed > 0 and current < needed:
                        if solrock_priority and target.id == CID_SOLROCK:
                            key: tuple = (-1, current)
                        else:
                            key = (_ENERGY_ATTACH_PRIORITY.get(target.id, 99), current)
                        energy_candidates.append((key, idx))
                else:
                    fallback.append(idx)
            elif cd is not None and cd.cardType == CardType.TOOL:
                if _should_play_named_card(cd.cardId, obs):
                    if target is not None:
                        if cd.cardId == CID_BALLOON:
                            prio = _BALLOON_TARGET_PRIORITY.get(target.id, 99)
                        elif cd.cardId == CID_MAX_BELT:
                            prio = _MAX_BELT_TARGET_PRIORITY.get(target.id, 99)
                        else:
                            prio = 50
                    else:
                        prio = 99
                    tool_candidates.append((prio, idx))
            else:
                fallback.append(idx)
        else:
            # カード識別不能でも、ターゲットのエネルギー必要数でチェック
            if target is not None:
                needed  = _max_energy_needed(target, card_cache, attack_cache)
                current = len(target.energies)
                if needed > 0 and current < needed:
                    if solrock_priority and target.id == CID_SOLROCK:
                        key = (-1, current)
                    else:
                        key = (_ENERGY_ATTACH_PRIORITY.get(target.id, 99), current)
                    energy_candidates.append((key, idx))
            else:
                fallback.append(idx)

    if energy_candidates:
        energy_candidates.sort(key=lambda x: x[0])
        return energy_candidates[0][1]

    if tool_candidates:
        tool_candidates.sort()
        return tool_candidates[0][1]

    return fallback[0] if fallback else None


def _best_play_index(matches: list[int], options, obs: Observation) -> int | None:
    """
    プレイ優先度:
      サポーター（優先度順）> アイテム(汎用) > 条件付きカード > その他
    サポーター優先度: タケシ(条件)>ジャッジマン(opp≥10)>リーリエ>ジャッジマン>タケシ>ボス(条件)
    ボスの指令は条件を満たさない限り使わない（999 = スキップ）。
    全候補が除外された場合は None を返す（次の優先度へ）。
    """
    card_cache = _get_card_data_cache()
    hand = obs.current.players[obs.current.yourIndex].hand if obs.current else None

    supporter_scored: list[tuple[int, int]] = []  # (priority, idx)
    item_idx:         list[int] = []
    conditional_ok:   list[int] = []
    other_idx:        list[int] = []

    for idx in matches:
        hand_pos = options[idx].index
        if hand and hand_pos is not None and 0 <= hand_pos < len(hand):
            card_id = hand[hand_pos].id
            cd = card_cache.get(card_id)
            if cd is None:
                other_idx.append(idx)
            elif cd.cardType == CardType.SUPPORTER:
                prio = _supporter_sort_key(cd.cardId, obs)
                if prio < 999:
                    supporter_scored.append((prio, idx))
                # prio==999 → 条件未達成のボスなど、このターンは使わない
            elif cd.cardType == CardType.ITEM:
                if cd.cardId in _CONDITIONAL_CARDS:
                    if _should_play_named_card(cd.cardId, obs):
                        conditional_ok.append(idx)
                elif _should_play_item(cd.cardId, obs):
                    item_idx.append(idx)
                # 条件未達のサーチ/補充/交代グッズ → 温存（次の優先度へ）
            elif cd.cardType in (CardType.TOOL, CardType.STADIUM):
                if cd.cardId in _CONDITIONAL_CARDS:
                    if _should_play_named_card(cd.cardId, obs):
                        conditional_ok.append(idx)
                else:
                    other_idx.append(idx)
            else:
                other_idx.append(idx)
        else:
            other_idx.append(idx)

    if supporter_scored:
        supporter_scored.sort()
        return supporter_scored[0][1]

    candidates = item_idx or conditional_ok or other_idx
    return candidates[0] if candidates else None


# =====================================================================
# 評価関数アーキテクチャ（Phase 1: 解析型 V）
# ---------------------------------------------------------------------
# 固定優先度の条件分岐に代わり、「盤面を観測可能な特徴量の重み付き和で
# スコア化する評価関数 V」を導入する。各意思決定は「その手が生む盤面の
# V を最大化するか」で判断する。第一段では RETREAT を V 比較に置き換える。
# 特徴量は全て観測可能（相手の盤面ポケモンは付与エネルギーまで可視）。
# =====================================================================

# 評価関数の重み（GAで再最適化可能なように1か所に集約）
_V_WEIGHTS: dict[str, float] = {
    "survive_next":     3.0,   # 相手の次の攻撃を耐えるか（二値）
    "can_ko":           4.0,   # 今ターン相手バトルを倒せるか（二値）
    "prize_lead":       5.0,   # サイド差（相手残り − 自分残り、＋が有利）
    "energy_ready":     1.5,   # 主攻撃役のエネルギー準備度（0〜1）
    "hand_energy":      0.3,   # 手札エネルギー（正規化 0〜1）
    "bench_backup":     0.5,   # 控えベンチの最大HP（正規化 0〜1）
    "opp_bench_threat": -1.0,  # 相手ベンチの潜在打点（正規化 0〜1、脅威=マイナス）
    "retreat_cost":     0.4,   # にげるエネルギーコストのペナルティ係数
    'field_setup': 1.0,  # ← このように追加する
}


def _usable_damage(poke, card_cache: dict, attack_cache: dict, defender=None) -> int:
    """
    そのポケモンが「今の付与エネルギーで実際に撃てる」技の最大ダメージ。

    - 技の要求エネルギー枚数 ≤ 付与枚数 の技だけを対象（枚数ベース）。
    - defender が与えられ、その弱点が攻撃側タイプと一致するなら ×2。
      ただし弱点・抵抗を計算しないポケモン（_NO_WEAKNESS_POKEMON、ソルロックの
      コスモビーム等）は ×2 しない。※技名は英語照合不可のためポケモンID単位で扱う。
    - 各技の実効ダメージの最大を返す。

    既知の未モデル要素（多ターン評価の課題）:
      反動（ワイルドプレス自70）・ロックアウト（メガブレイブ/かそくづき次番不可）・
      技の失敗条件（コスモビームはベンチにルナトーン不在で失敗）。
    """
    if poke is None:
        return 0
    cd = card_cache.get(poke.id)
    if cd is None:
        return 0

    dcd = card_cache.get(defender.id) if defender is not None else None
    weak = (
        dcd is not None and dcd.weakness is not None and dcd.weakness == cd.energyType
        and poke.id not in _NO_WEAKNESS_POKEMON
    )

    avail = len(poke.energies)
    best = 0
    for aid in cd.attacks:
        atk = attack_cache.get(aid)
        if atk is None or len(atk.energies) > avail:
            continue
        dmg = atk.damage
        if dmg > 0 and weak:
            dmg *= 2
        if dmg > best:
            best = dmg
    return best


def _best_bench_switch_candidate(state, your_idx: int):
    """交代先に最適な非例外ベンチポケモンと、そのベンチindexを返す（なければ (None, -1)）。"""
    your_state = state.players[your_idx]
    card_cache = _get_card_data_cache()
    best, best_i, best_hp = None, -1, -1
    for i, p in enumerate(your_state.bench):
        if p.id in _RETREAT_EXCEPTIONS:
            continue
        if p.hp > best_hp:
            best_hp, best, best_i = p.hp, p, i
    return best, best_i


def _evaluate(state, your_idx: int, active_override=None) -> float:
    """
    盤面評価関数 V。active_override を渡すと「そのポケモンがバトル場にいる」
    と仮定して自分側の特徴量を計算する（RETREAT の現状維持 vs 交代の比較用）。
    """
    if state is None:
        return 0.0

    your_state = state.players[your_idx]
    opp_state  = state.players[1 - your_idx]
    card_cache   = _get_card_data_cache()
    attack_cache = _get_attack_cache()

    active = active_override if active_override is not None else (
        your_state.active[0] if your_state.active else None)
    opp_active = opp_state.active[0] if opp_state.active else None

    # --- 攻防の打点（弱点込み） ---
    my_dmg  = _usable_damage(active, card_cache, attack_cache, defender=opp_active)
    opp_dmg = _usable_damage(opp_active, card_cache, attack_cache, defender=active)
    my_hp   = active.hp if active is not None else 0
    opp_hp  = opp_active.hp if opp_active is not None else 0

    survive_next = 1.0 if (active is not None and opp_dmg < my_hp) else 0.0
    can_ko       = 1.0 if (opp_active is not None and my_dmg >= opp_hp) else 0.0
    prize_lead   = float(len(opp_state.prize) - len(your_state.prize))

    # --- エネルギー準備度 ---
    need = _max_energy_needed(active, card_cache, attack_cache) if active is not None else 0
    energy_ready = (min(len(active.energies), need) / need) if (active is not None and need > 0) else 1.0

    # --- 手札エネルギー（正規化） ---
    hand = your_state.hand or []
    hand_energy = sum(
        1 for c in hand
        if card_cache.get(c.id) is not None
        and card_cache[c.id].cardType in (CardType.BASIC_ENERGY, CardType.SPECIAL_ENERGY)
    )
    hand_energy_n = min(hand_energy, 4) / 4.0

    # --- 控えベンチの耐久（正規化） ---
    bench_hps = [
        p.hp for p in your_state.bench
        if p.id not in _RETREAT_EXCEPTIONS
    ]
    bench_backup = (min(max(bench_hps), 300) / 300.0) if bench_hps else 0.0

    # --- 相手ベンチの潜在打点（次ターン脅威、正規化） ---
    opp_bench_threat = 0
    for p in opp_state.bench:
        d = _usable_damage(p, card_cache, attack_cache, defender=active)
        if d > opp_bench_threat:
            opp_bench_threat = d
    opp_bench_threat_n = min(opp_bench_threat, 300) / 300.0

    w = _V_WEIGHTS
    return (
        w["survive_next"]     * survive_next
        + w["can_ko"]         * can_ko
        + w["prize_lead"]     * prize_lead
        + w["energy_ready"]   * energy_ready
        + w["hand_energy"]    * hand_energy_n
        + w["bench_backup"]   * bench_backup
        + w["opp_bench_threat"] * opp_bench_threat_n
    )


def _should_retreat(obs: Observation) -> bool:
    """
    にげる判断（V比較ベース）:
      現状維持の V と、最良ベンチへ交代した後の V を比較し、交代後の方が
      高ければにげる。交代にはエネルギーコスト分のペナルティを課す。

    例外: バトル場が特性専用ポケモン（ソルロック・ルナトーン）の場合は、
          非例外の攻撃役ベンチがいれば即にげる（V計算前のショートカット）。
    """
    state = obs.current
    if state is None:
        return False
    your_idx   = state.yourIndex
    your_state = state.players[your_idx]
    card_cache = _get_card_data_cache()

    active = your_state.active[0] if your_state.active else None
    if active is None:
        return False

    cand, _ = _best_bench_switch_candidate(state, your_idx)
    if cand is None:
        return False  # 交代先がいない

    # 例外ポケモンがバトル場 → 攻撃役へ即交代
    if active.id in _RETREAT_EXCEPTIONS:
        return True

    stay_v   = _evaluate(state, your_idx, active_override=active)
    acd      = card_cache.get(active.id)
    retreat_cost = acd.retreatCost if acd is not None else 0
    switch_v = (_evaluate(state, your_idx, active_override=cand)
                - _V_WEIGHTS["retreat_cost"] * retreat_cost)
    return switch_v > stay_v


def _select_switch_target(obs: Observation) -> list[int]:
    """にげる後のベンチ選択: 非例外ポケモンの中で最大HPを選ぶ"""
    state   = obs.current
    options = obs.select.option

    if state is None or not options:
        return [0]

    your_idx   = state.yourIndex
    your_state = state.players[your_idx]
    card_cache = _get_card_data_cache()

    best_i  = 0
    best_hp = -1

    for i, opt in enumerate(options):
        area  = getattr(opt, 'area', None)
        index = getattr(opt, 'index', None)
        if area == AreaType.BENCH and index is not None and 0 <= index < len(your_state.bench):
            p = your_state.bench[index]
            if p.id not in _RETREAT_EXCEPTIONS and p.hp > best_hp:
                best_hp = p.hp
                best_i  = i

    return [best_i]


def _sync_turn_state(state) -> None:
    """ターンが変わったときに追跡フラグをリセットする"""
    global _last_seen_turn, _non_boss_supporter_played, _luna_cycle_used
    if state is not None and state.turn != _last_seen_turn:
        _last_seen_turn = state.turn
        _non_boss_supporter_played = False
        _luna_cycle_used = False


def _should_use_luna_cycle(obs: Observation) -> bool:
    """
    ルナサイクル（ルナトーンの特性）を使うべきか判定する。

    使う条件（いずれか1つ）:
    a. このターンに非ボスサポーターを使っていない
    b. このターン手張りをした かつ 手札にサポーターがない（次ターンに使えない）
    c. バトル場がはどうづきを持つ かつ トラッシュのエネルギーが2枚以下
    """
    state = obs.current
    if state is None:
        return True

    your_idx = state.yourIndex
    your_state = state.players[your_idx]
    card_cache = _get_card_data_cache()
    attack_cache = _get_attack_cache()

    # 条件a: 非ボスサポーターを使っていない
    if not _non_boss_supporter_played:
        return True

    # 条件b: このターン手張りした かつ 手札にサポーターなし
    if state.energyAttached:
        has_supporter = any(
            card_cache.get(c.id) is not None
            and card_cache[c.id].cardType == CardType.SUPPORTER
            for c in (your_state.hand or [])
        )
        if not has_supporter:
            return True

    # 条件c: バトル場がメガルカリオex（はどうづき＝トラッシュ闘エネ参照）+ トラッシュエネ ≤ 2
    your_active = your_state.active[0] if your_state.active else None
    if your_active is not None and your_active.id == CID_MEGA_LUCARIO:
        trash_energy = sum(
            1 for c in (your_state.discard or [])
            if card_cache.get(c.id) is not None
            and card_cache[c.id].cardType in (
                CardType.BASIC_ENERGY, CardType.SPECIAL_ENERGY
            )
        )
        if trash_energy <= 2:
            return True

    return False


def _select_ability(matches: list[int], options, obs: Observation) -> int | None:
    """
    ABILITYアクションの条件付き選択。

    ルナトーン（ルナサイクル）: _should_use_luna_cycle の条件を満たす場合のみ使用。
    その他のポケモン: 無条件で使用。
    すべての候補が条件未達成なら None を返し、次の優先度（ATTACK）へスキップ。
    """
    global _luna_cycle_used
    state = obs.current
    if state is None:
        return matches[0] if matches else None

    your_idx = state.yourIndex
    your_state = state.players[your_idx]
    card_cache = _get_card_data_cache()

    for idx in matches:
        opt = options[idx]
        poke = None
        if opt.area == AreaType.ACTIVE and your_state.active:
            poke = your_state.active[0]
        elif opt.area == AreaType.BENCH and opt.index is not None:
            bench = your_state.bench
            if 0 <= opt.index < len(bench):
                poke = bench[opt.index]

        if poke is None:
            return idx  # ポケモン特定不可 → デフォルトで使用

        if poke.id == CID_LUNATONE:
            if _should_use_luna_cycle(obs):
                _luna_cycle_used = True
                return idx
            # 条件未達成 → このABILITYをスキップ
        else:
            return idx  # ルナトーン以外は無条件で使用

    return None  # すべてのABILITYが条件未達成


def _select_yes_no(obs: Observation) -> list[int]:
    """
    YES_NO 選択: コンテキストに応じてYES/NOを判断する。

    YES を選ぶ状況（積極的に効果を活用）:
      IS_FIRST   → 先攻を選ぶ
      MULLIGAN   → 追加ドローを受け取る
      ACTIVATE   → 自分の効果を発動する
      COIN_HEAD  → コインは常に表を選ぶ（有利効果が多い）
      FIRST_EFFECT → 効果を先に処理する

    NO を選ぶ状況:
      現在は明示的なNOケースなし（将来の拡張用に構造化）
      ※ 不利効果が判明次第ここに条件を追加すること
    """
    options = obs.select.option
    context = obs.select.context

    def _yes():
        idx = [i for i, o in enumerate(options) if o.type == OptionType.YES]
        return idx[:1] if idx else [0]

    def _no():
        idx = [i for i, o in enumerate(options) if o.type == OptionType.NO]
        return idx[:1] if idx else [len(options) - 1]

    if context in (
        SelectContext.IS_FIRST,
        SelectContext.MULLIGAN,
        SelectContext.ACTIVATE,
        SelectContext.COIN_HEAD,
        SelectContext.FIRST_EFFECT,
    ):
        return _yes()

    # デフォルト: YES（既定の積極的戦略を維持）
    return _yes()


def _select_main_action(obs: Observation) -> list[int]:
    """
    MAIN 選択: 優先度順にアクションを決定する（GA最適化済み: fitness=0.70）
      1. ATTACH  (エネルギー等をつける) w=20.0 ※技コスト超過分はスキップ、不要なら次へ
      2. PLAY    (カードをプレイ)       w= 6.3 ※条件付きカードは状況判断、不要なら次へ
      3. EVOLVE  (進化)                 w= 6.0
      4. ABILITY (特性)                 w= 5.0 ※ルナサイクルは条件付き
      5. ATTACK  (攻撃)                 w= 4.5
      6. RETREAT (にげる)               w= 2.4
      7. END     (ターン終了)            w= 0.1
    """
    global _non_boss_supporter_played

    state = obs.current
    if state is not None:
        _sync_turn_state(state)

    options = obs.select.option
    card_cache = _get_card_data_cache()

    priority_order = [
        OptionType.ATTACH,   # w=20.0（最大）エネルギー準備を最優先
        OptionType.PLAY,     # w= 6.3
        OptionType.EVOLVE,   # w= 6.0
        OptionType.ABILITY,  # w= 5.0
        OptionType.ATTACK,   # w= 4.5
        OptionType.RETREAT,  # w= 2.4
        OptionType.END,      # w= 0.1
    ]

    for opt_type in priority_order:
        matches = [i for i, opt in enumerate(options) if opt.type == opt_type]
        if not matches:
            continue

        if opt_type == OptionType.ATTACK:
            return [_best_attack_index(matches, options)]

        if opt_type == OptionType.ATTACH:
            idx = _best_attach_index(matches, options, obs)
            if idx is not None:
                return [idx]
            continue  # 有効なアタッチなし → 次の優先度へ

        if opt_type == OptionType.PLAY:
            idx = _best_play_index(matches, options, obs)
            if idx is not None:
                # 非ボスサポーターを使う場合はターン追跡フラグを立てる
                if state is not None:
                    hand = state.players[state.yourIndex].hand
                    hand_pos = options[idx].index
                    if hand and hand_pos is not None and 0 <= hand_pos < len(hand):
                        cd = card_cache.get(hand[hand_pos].id)
                        if (cd and cd.cardType == CardType.SUPPORTER
                                and cd.cardId != _SUPPORTER_BOSS):
                            _non_boss_supporter_played = True
                return [idx]
            continue  # 条件付きカードが未達成など → 次の優先度へ

        if opt_type == OptionType.ABILITY:
            idx = _select_ability(matches, options, obs)
            if idx is not None:
                return [idx]
            continue  # 条件未達成（ルナサイクル等）→ 次の優先度へ

        if opt_type == OptionType.RETREAT:
            if _should_retreat(obs):
                return [matches[0]]
            continue  # 条件未達成 → ENDへ

        return [matches[0]]

    return [len(options) - 1]


# --- メインエージェント ---

def agent(obs_dict: dict) -> list[int]:
    obs: Observation = to_observation_class(obs_dict)

    if obs.select is None:
        return read_deck_csv()

    options   = obs.select.option
    max_count = obs.select.maxCount
    sel_type  = obs.select.type

    if sel_type == SelectType.MAIN:
        return _select_main_action(obs)

    # CARD選択: コンテキストに応じて専用ハンドラへ振り分け
    if sel_type == SelectType.CARD:
        if obs.select.context == SelectContext.ATTACH_FROM:
            return _select_attach_target(obs)
        if obs.select.context in (SelectContext.SWITCH, SelectContext.TO_ACTIVE):
            return _select_switch_target(obs)
        return _route_card_selection(obs)

    # YES/NO: コンテキストに応じて判断（_select_yes_no 参照）
    if sel_type == SelectType.YES_NO:
        return _select_yes_no(obs)

    # COUNT: 最大値を選ぶ（ドロー枚数等）
    if sel_type == SelectType.COUNT:
        best = max(range(len(options)), key=lambda i: (options[i].number or 0))
        return [best]

    # その他（カード選択・エネルギー選択等）: 最初のmax_count個を選ぶ
    if max_count == 0:
        return []
    count = min(max_count, len(options))
    return list(range(count))
