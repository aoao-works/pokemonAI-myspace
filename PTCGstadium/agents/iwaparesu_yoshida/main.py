import os

from cg.api import (
    Observation, SelectType, SelectContext, OptionType, AreaType, CardType,
    EnergyType, to_observation_class, all_attack, all_card_data,
)

# =====================================================================
# ポケモンTCG AIエージェント — 汎用アーキテクチャ版（デッキ: イワパレス）
# ---------------------------------------------------------------------
# 設計: 「デッキ非依存の中核アルゴリズム」＋「デッキ固有の設定ブロック」。
#   - 中核（評価関数V・行動優先度・上限アタッチ・V比較にげる・サーチ/配置
#     /捨て先の枠組み・定番トレーナー処理）は sample_submission（ルカリオ）から
#     ルカリオ専用ロジック（ルナサイクル/8段階交代/メガブレイブ/ソルロック/
#     イワパレス対面）を取り除いた共通部分。3デッキで同一。
#   - 下の「DECK CONFIG」だけがデッキ固有。ここを編集すれば別デッキへ流用可能。
# 重要: all_card_data()/all_attack() は英語名を返すため、照合は全て「カードID」。
# =====================================================================


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


# =====================================================================
# ============================ DECK CONFIG ============================
# ここだけがデッキ固有。別デッキへ流用する場合はこのブロックを差し替える。
# =====================================================================

# --- ポケモンID（イワパレスデッキ）---
# このデッキはイシズマイ→イワパレスの単一進化ラインのみ（ポケモンは2種）。
CID_ISHIZUMAI = 344   # イシズマイ（たね, HP70, かくせい=自己進化 → イワパレス）
CID_IWAPARESU = 345   # イワパレス（1進化, HP150, グレートシザー 草無無 120）★主力
                      # 特性しんぴのいしやど（ex のワザダメージを受けない）は受動＝発動不要

# --- 相手のポケモンexからワザダメージを受けない特性を持つ味方ポケモン ---
# イワパレスの「しんぴのいしやど」。これに立たれた ex は空振りするので、
# _usable_damage で「守備側がこの集合 かつ 攻撃側が ex → ダメージ0」と扱う。
# これを反映しないと survive_next / opp_bench_threat / にげる・ボス判断が
# 「exに殴られて死ぬ」と誤認し、壁デッキ最大の武器が意思決定に見えない。
_EX_IMMUNE_POKEMON: frozenset[int] = frozenset({CID_IWAPARESU})

# --- 回復カード（無駄撃ち・自傷回避のため個別判断する）---
CID_POTION      = 1112  # いいきずぐすり（60回復＋エネ1個トラッシュ＝諸刃）
CID_JUMBO_ICE   = 1147  # ジャンボアイス（エネ3個以上のバトルを80回復）
CID_BELL        = 1190  # ベルのまごころ（残HP30以下の味方を全回復, サポート）

# --- 定番トレーナー（複数デッキ共通。無いデッキは 0 で無効化）---
CID_BOSS            = 1182  # ボスの指令
CID_LILLIE          = 1227  # リーリエの決心
CID_MATSUBA         = 1187  # マツバの確信（手札1枚トラッシュ→相手ベンチ数ぶんドロー）
CID_POKE_PAD        = 1152  # ポケパッド
CID_ULTRA_BALL      = 0     # このデッキには無い
CID_NIGHT_STRETCHER = 0     # このデッキには無い
CID_SWITCH          = 1123  # ポケモンいれかえ

# --- 山札切れ回避のしきい値 ---
# 壁デッキは長期戦になりやすく、大量ドロー系サポート（リーリエ/マツバ）を
# 使い続けると勝敗が付く前に自分の山札が切れて負けることが多い
# （2026-07-04計測: 敗因の約4割が自分の山札切れ）。残り山札がこの枚数以下に
# なったら、緊急性の低い大量ドローは温存してターンを稼ぐ。
_DECKOUT_GUARD_THRESHOLD = 15

# --- 目標盤面（ID: 在場したい数）。理想盤面の構築度（V.field_setup）にも使う ---
# イワパレスを複数立てて壁にするため、起点のイシズマイを多めに確保する。
_FIELD_TARGETS: dict[int, int] = {
    CID_ISHIZUMAI: 3,
}

# --- 場に置く上限（ID: 最大在場数）---
_FIELD_CAP: dict[int, int] = {
    CID_ISHIZUMAI: 5, CID_IWAPARESU: 5,
}

# --- ベンチ配置の優先順（(カードID, すでに場にいる枚数)。小さいほど先に出す）---
_BENCH_PLACEMENT_ORDER: list[tuple[int, int]] = [
    (CID_ISHIZUMAI, 0),
    (CID_ISHIZUMAI, 1),
    (CID_ISHIZUMAI, 2),
    (CID_ISHIZUMAI, 3),
    (CID_ISHIZUMAI, 4),
]

# --- サーチ／持ってくる順（(カードID, すでに所有している枚数=場+手札)。小さいほど優先）---
_BRING_ORDER: list[tuple[int, int]] = [
    (CID_ISHIZUMAI, 0),
    (CID_ISHIZUMAI, 1),
    (CID_ISHIZUMAI, 2),
    (CID_ISHIZUMAI, 3),
    (CID_ISHIZUMAI, 4),
]

# --- 夜のタンカ等の回収優先（小さいほど優先）---
_SEARCH_PRIORITY: dict[int, int] = {
    CID_ISHIZUMAI: 0, CID_IWAPARESU: 1,
}

# --- エネルギーアタッチ優先度（小さいほど優先）。主攻撃役に集める ---
_ENERGY_ATTACH_PRIORITY: dict[int, int] = {
    CID_IWAPARESU: 0,   # グレートシザー（草無無）
    CID_ISHIZUMAI: 1,
}

# --- ポケモンのどうぐの貼り先優先（空なら _ENERGY_ATTACH_PRIORITY を流用）---
# ヒーローマント(+100HP)/せいなるおまもり(-30) はイワパレスに優先して貼る。
_TOOL_TARGET_PRIORITY: dict[int, int] = {
    CID_IWAPARESU: 0,
    CID_ISHIZUMAI: 1,
}

# --- エネルギー上限の明示（省略時は全技中の最大コストを自動採用）---
_ENERGY_CAP_OVERRIDE: dict[int, int] = {}

# --- バトル場に出したくない／積極的に交代したいポケモン ---
# 単一ラインなので特別な例外は無し（V でにげる/交代を判断）。
_RETREAT_EXCEPTIONS: frozenset[int] = frozenset()

# --- スタート時バトル場の優先（小さいほど優先。空なら非例外の最大HP）---
_SETUP_ACTIVE_PRIORITY: dict[int, int] = {
    CID_ISHIZUMAI: 0,
    CID_IWAPARESU: 1,
}

# --- 自動発動しない特性（自分きぜつ等）。イワパレスの特性は受動なので該当なし ---
_ABILITY_AVOID: frozenset[int] = frozenset()

# --- 弱点×2を計算しないポケモン（特殊技）---
_NO_WEAKNESS_POKEMON: frozenset[int] = frozenset()

# --- 条件付きどうぐ（KO圏で貼る等）。このデッキは該当なし（ツールは常時有用）---
_CONDITIONAL_CARDS: frozenset[int] = frozenset()

# --- 絶対に捨てないカード（捨て先選択で保護）---
_DISCARD_PROTECT: frozenset[int] = frozenset()

# --- サポーターID と 使用優先（小さいほど先。ボス/リーリエ/ベルは中核で個別判断）---
# ボスは「今ターン実際にKO/スナイプできる的がある」時は最優先（5）でサーチ系より
# 先に使う（取り逃すと相手に退避・回復されるため）。攻撃準備が無い/的が無い時のみ
# stall用に低優先（55）で使う。サーチ系（トウコ/ラムダ/マツバ）は常時有用だが、
# ボスの確定KOを逃してまで使う理由は無いため中間の優先度に据える。
_SUPPORTER_IDS: frozenset[int] = frozenset({CID_BOSS, CID_LILLIE, CID_MATSUBA, 1190, 1219, 1225})
_SUPPORTER_PRIORITY: dict[int, int] = {
    1190: 15,   # ベルのまごころ（瀕死回避、緊急性が高い）
    1225: 20,   # トウコ（進化ポケモン＋エネをサーチ）
    1219: 21,   # ロケット団のラムダ（トレーナーズをサーチ）
    1187: 22,   # マツバの確信（ドロー）
}

# --- ポケモンをサーチするグッズ（盤面が埋まっていれば温存）---
# ポケパッド/なかよしポフィン。ポケギア3.0(1122)はサポーターサーチなので含めない（常時有用）。
_POKEMON_SEARCH_ITEMS: frozenset[int] = frozenset({
    CID_POKE_PAD, 1086,
})

# =====================================================================
# ========================= 評価関数の重み ============================
# =====================================================================
_V_WEIGHTS: dict[str, float] = {
    "survive_next":     3.0,   # 相手の次の攻撃を耐えるか（二値）
    "can_ko":           4.0,   # 今ターン相手バトルを倒せるか（二値）
    "prize_lead":       5.0,   # サイド差（相手残り − 自分残り、＋が有利）
    "energy_ready":     1.5,   # 主攻撃役のエネルギー準備度（0〜1）
    "hand_energy":      0.3,   # 手札エネルギー（正規化 0〜1）
    "bench_backup":     0.5,   # 控えベンチの最大HP（正規化 0〜1）
    "opp_bench_threat": -1.0,  # 相手ベンチの潜在打点（正規化、脅威=マイナス）
    "field_setup":      1.0,   # 目標盤面の構築度（0〜1）
    "retreat_cost":     0.4,   # にげるエネルギーコストのペナルティ係数
}


# =====================================================================
# ====================== デッキ非依存の中核 ===========================
# =====================================================================

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
    """そのポケモンの全技を通じて最大のエネルギーコスト数。ID別上限が優先。"""
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
    """ポケモンのカード名（表示/デバッグ用。照合には使わない）"""
    cd = card_cache.get(poke.id)
    return cd.name if cd else ""


def _is_ex_pokemon(poke, card_cache: dict) -> bool:
    """exポケモンか（言語非依存に CardData.ex / megaEx で判定）"""
    cd = card_cache.get(poke.id)
    return cd is not None and (bool(cd.ex) or bool(cd.megaEx))


def _is_stage2(poke, card_cache: dict) -> bool:
    """2進化ポケモンか（CardData.stage2）"""
    cd = card_cache.get(poke.id)
    return cd is not None and bool(cd.stage2)


def _field_mons(player_state) -> list:
    """場（バトル場＋ベンチ）の実体ポケモン。伏せ active=[None] は除外。"""
    return [p for p in list(player_state.active) + list(player_state.bench) if p is not None]


def _count_field_pokemon(your_state, card_cache: dict) -> dict[int, int]:
    """自分のバトル場+ベンチのポケモンをカードIDでカウント"""
    counts: dict[int, int] = {}
    for poke in _field_mons(your_state):
        counts[poke.id] = counts.get(poke.id, 0) + 1
    return counts


def _hand_counts(your_state) -> dict[int, int]:
    """手札のカード（ID別）枚数"""
    counts: dict[int, int] = {}
    for c in (your_state.hand or []):
        counts[c.id] = counts.get(c.id, 0) + 1
    return counts


def _placement_rank(cid: int, field_count: int) -> int | None:
    """すでに field_count 体いる状態で出すときの優先順位（小さいほど先）。上限超過は None。"""
    cap = _FIELD_CAP.get(cid)
    if cap is not None and field_count >= cap:
        return None
    try:
        return _BENCH_PLACEMENT_ORDER.index((cid, field_count))
    except ValueError:
        return 100 + field_count   # 明示順序外だが上限内 → 低優先で出す


def _bring_rank(cid: int, owned: int) -> int | None:
    """すでに owned 枚 所有している状態でその cid を持ってくる優先順位。順序外は None。"""
    try:
        return _BRING_ORDER.index((cid, owned))
    except ValueError:
        return None


def _usable_damage(poke, card_cache: dict, attack_cache: dict, defender=None) -> int:
    """今の付与エネルギーで実際に撃てる技の最大ダメージ（弱点×2込み、免除ポケ除く）。"""
    if poke is None:
        return 0
    cd = card_cache.get(poke.id)
    if cd is None:
        return 0
    # 守備側がex無効特性（しんぴのいしやど等）を持ち、攻撃側がexなら
    # ワザのダメージは通らない ＝ 打点0扱い。壁デッキの中核ロジック。
    if (defender is not None and defender.id in _EX_IMMUNE_POKEMON
            and _is_ex_pokemon(poke, card_cache)):
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


def _evaluate(state, your_idx: int, active_override=None) -> float:
    """盤面評価関数 V。active_override で「その体がバトル場にいる」仮定の評価ができる。"""
    if state is None:
        return 0.0
    your_state = state.players[your_idx]
    opp_state  = state.players[1 - your_idx]
    card_cache   = _get_card_data_cache()
    attack_cache = _get_attack_cache()

    active = active_override if active_override is not None else (
        your_state.active[0] if your_state.active else None)
    opp_active = opp_state.active[0] if opp_state.active else None

    my_dmg  = _usable_damage(active, card_cache, attack_cache, defender=opp_active)
    opp_dmg = _usable_damage(opp_active, card_cache, attack_cache, defender=active)
    my_hp   = active.hp if active is not None else 0
    opp_hp  = opp_active.hp if opp_active is not None else 0

    survive_next = 1.0 if (active is not None and opp_dmg < my_hp) else 0.0
    can_ko       = 1.0 if (opp_active is not None and my_dmg >= opp_hp) else 0.0
    prize_lead   = float(len(opp_state.prize) - len(your_state.prize))

    need = _max_energy_needed(active, card_cache, attack_cache) if active is not None else 0
    energy_ready = (min(len(active.energies), need) / need) if (active is not None and need > 0) else 1.0

    hand = your_state.hand or []
    hand_energy = sum(
        1 for c in hand
        if card_cache.get(c.id) is not None
        and card_cache[c.id].cardType in (CardType.BASIC_ENERGY, CardType.SPECIAL_ENERGY)
    )
    hand_energy_n = min(hand_energy, 4) / 4.0

    bench_hps = [p.hp for p in your_state.bench if p.id not in _RETREAT_EXCEPTIONS]
    bench_backup = (min(max(bench_hps), 300) / 300.0) if bench_hps else 0.0

    opp_bench_threat = 0
    for p in opp_state.bench:
        d = _usable_damage(p, card_cache, attack_cache, defender=active)
        if d > opp_bench_threat:
            opp_bench_threat = d
    opp_bench_threat_n = min(opp_bench_threat, 300) / 300.0

    field_counts = _count_field_pokemon(your_state, card_cache)
    target_total = sum(_FIELD_TARGETS.values())
    field_setup = (
        sum(min(field_counts.get(cid, 0), m) for cid, m in _FIELD_TARGETS.items())
        / target_total
    ) if target_total else 0.0

    w = _V_WEIGHTS
    return (
        w["survive_next"]     * survive_next
        + w["can_ko"]         * can_ko
        + w["prize_lead"]     * prize_lead
        + w["energy_ready"]   * energy_ready
        + w["hand_energy"]    * hand_energy_n
        + w["bench_backup"]   * bench_backup
        + w["opp_bench_threat"] * opp_bench_threat_n
        + w["field_setup"]    * field_setup
    )


# --- ターン内状態追跡（デッキ非依存）---
_last_seen_turn: int = -1
_non_boss_supporter_played: bool = False
_last_attack_turn: int = -1


def _sync_turn_state(state) -> None:
    """ターンが変わったら追跡フラグをリセット。巻き戻り（新ゲーム）で履歴クリア。"""
    global _last_seen_turn, _non_boss_supporter_played, _last_attack_turn
    if state is not None and state.turn != _last_seen_turn:
        if state.turn < _last_seen_turn:
            _last_attack_turn = -1
        _last_seen_turn = state.turn
        _non_boss_supporter_played = False


def _is_stalled(state) -> bool:
    """数ターン攻撃できていない（stall戦術を取るべき）か。"""
    if state is None:
        return False
    if _last_attack_turn < 0:
        return state.turn >= 5
    return state.turn - _last_attack_turn >= 4


def _need_basic_target(obs: Observation) -> bool:
    """目標ポケモンが場で上限未満かつ手札に無い → サーチの価値あり"""
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


def _should_play_lillie(obs: Observation) -> bool:
    """リーリエの決心（手札を戻して6/8枚引く）を使う価値があるか。
    山札が残り少ない時は、それ以上の大量ドローが山札切れ負けを早めるだけなので、
    手札が壊滅的に少ない（他に打つ手が無い）場合を除き温存する。"""
    state = obs.current
    if state is None:
        return True
    your_state = state.players[state.yourIndex]
    hand = your_state.hand or []
    if your_state.deckCount <= _DECKOUT_GUARD_THRESHOLD and len(hand) > 1:
        return False
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


def _should_play_matsuba(obs: Observation) -> bool:
    """マツバの確信（手札1枚トラッシュ→相手ベンチ数ぶんドロー）を使う価値があるか。
    山札が残り少ない時は、大量ドローが山札切れ負けを早めるだけなので温存する。
    相手のベンチが空ならドロー0枚で無価値なので使わない。"""
    state = obs.current
    if state is None:
        return True
    your_idx  = state.yourIndex
    your_state = state.players[your_idx]
    opp_state  = state.players[1 - your_idx]
    if your_state.deckCount <= _DECKOUT_GUARD_THRESHOLD:
        return False
    return len(opp_state.bench) > 0


def _boss_priority(obs: Observation) -> int | None:
    """ボスの指令の優先度（小さいほど優先、None=今ターンは使わない）。
    ベンチに実際にKO/スナイプできる的がある「確定KOの好機」は最優先（5）で
    トウコ等のサーチより先に使う（1ターン待つと相手に退避・回復されて機会を失うため）。
    攻撃準備が無い/的が無い場合は stall 時のみ低優先（55）で足止めに使う。"""
    state = obs.current
    if state is None:
        return 5
    your_idx   = state.yourIndex
    your_state = state.players[your_idx]
    opp_state  = state.players[1 - your_idx]
    card_cache   = _get_card_data_cache()
    attack_cache = _get_attack_cache()

    your_active = your_state.active[0] if your_state.active else None
    opp_active  = opp_state.active[0] if opp_state.active else None
    if your_active is None or len(your_active.energies) == 0:
        return 55 if _is_stalled(state) else None

    best_dmg = _best_attack_damage(your_active, card_cache, attack_cache)
    bench_ko = [p for p in opp_state.bench if p.hp <= best_dmg]
    if opp_active is not None and opp_active.hp <= best_dmg:
        return 5 if any(_is_ex_pokemon(p, card_cache) for p in bench_ko) else None
    if bench_ko:
        return 5
    return 55 if _is_stalled(state) else None


def _supporter_sort_key(card_id: int, obs: Observation) -> int:
    """サポーターの使用優先度（小さいほど優先、999=今ターンは使わない）。
    ボス/リーリエ/ベル/マツバは中核で個別判断、その他は DECK CONFIG の _SUPPORTER_PRIORITY。"""
    if card_id == CID_BOSS:
        prio = _boss_priority(obs)
        return prio if prio is not None else 999
    if card_id == CID_LILLIE:
        return 45 if _should_play_lillie(obs) else 999
    if card_id == CID_BELL:
        return _SUPPORTER_PRIORITY.get(CID_BELL, 15) if _should_play_bell(obs) else 999
    if card_id == CID_MATSUBA:
        return _SUPPORTER_PRIORITY.get(CID_MATSUBA, 22) if _should_play_matsuba(obs) else 999
    return _SUPPORTER_PRIORITY.get(card_id, 30)


def _should_play_named_card(card_id: int, obs: Observation) -> bool:
    """条件付きどうぐ/スタジアムの使用可否。デッキ固有の条件が無ければ常に使用。
    （ルカリオのマキシマムベルト/パワープロテイン/グラビティ相当をデッキ別に追加する拡張点）"""
    return True


def _should_play_switch_item(obs: Observation) -> bool:
    """ポケモンいれかえ（エネ不要の交代）の使用判断（V比較ベース）。"""
    state = obs.current
    if state is None:
        return False
    your_idx = state.yourIndex
    your_state = state.players[your_idx]
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


def _should_play_potion(obs: Observation) -> bool:
    """いいきずぐすり（60回復＋エネ1個トラッシュ＝諸刃）。
    エネを1個削っても攻撃コストを満たせ、かつ回復がほぼ無駄にならない程度に
    傷ついた味方がいる時のみ使う。攻撃準備済みの主砲のエネを削らないための温存判断。"""
    state = obs.current
    if state is None:
        return False
    your_state   = state.players[state.yourIndex]
    card_cache   = _get_card_data_cache()
    attack_cache = _get_attack_cache()
    for p in _field_mons(your_state):
        if (p.maxHp - p.hp) < 50:          # 60回復がほぼ無駄にならない程度に削れている
            continue
        need = _max_energy_needed(p, card_cache, attack_cache)
        if len(p.energies) == 0 or len(p.energies) - 1 >= need:  # エネ1個削っても攻撃可能
            return True
    return False


def _should_play_jumbo_ice(obs: Observation) -> bool:
    """ジャンボアイス（エネ3個以上のバトルポケを80回復・デメリット無し）。
    バトル場が相応に傷ついている時のみ（満タン付近での無駄撃ち回避）。"""
    state = obs.current
    if state is None:
        return False
    your_state = state.players[state.yourIndex]
    active = your_state.active[0] if your_state.active else None
    if active is None or len(active.energies) < 3:
        return False
    return (active.maxHp - active.hp) >= 40


def _should_play_bell(obs: Observation) -> bool:
    """ベルのまごころ（残HP30以下の味方を全回復）。対象がいる時のみ＝価値が大きい局面限定。"""
    state = obs.current
    if state is None:
        return False
    your_state = state.players[state.yourIndex]
    return any(0 < p.hp <= 30 for p in _field_mons(your_state))


def _should_play_item(card_id: int, obs: Observation) -> bool:
    """汎用グッズの使用可否。サーチ系は盤面が埋まっていれば温存、交代・回復は個別判断。"""
    if card_id == CID_SWITCH:
        return _should_play_switch_item(obs)
    if card_id == CID_POTION:
        return _should_play_potion(obs)
    if card_id == CID_JUMBO_ICE:
        return _should_play_jumbo_ice(obs)
    if card_id in _POKEMON_SEARCH_ITEMS:
        return _need_basic_target(obs)
    return True


def _best_bench_switch_candidate(state, your_idx: int):
    """交代先に最適な非例外ベンチポケモンと、そのベンチindexを返す（なければ (None, -1)）。
    各候補を「バトル場に出した」と仮定して V を計算し、V 最大の体を選ぶ（同点HP）。"""
    your_state = state.players[your_idx]
    best, best_i, best_key = None, -1, None
    for i, p in enumerate(your_state.bench):
        if p.id in _RETREAT_EXCEPTIONS:
            continue
        v = _evaluate(state, your_idx, active_override=p)
        key = (v, p.hp)
        if best_key is None or key > best_key:
            best_key, best, best_i = key, p, i
    return best, best_i


def _should_retreat(obs: Observation) -> bool:
    """にげる判断（V比較）。例外ポケモンがバトル場なら攻撃役へ即交代。"""
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
        return False
    if active.id in _RETREAT_EXCEPTIONS:
        return True
    stay_v   = _evaluate(state, your_idx, active_override=active)
    acd      = card_cache.get(active.id)
    retreat_cost = acd.retreatCost if acd is not None else 0
    switch_v = (_evaluate(state, your_idx, active_override=cand)
                - _V_WEIGHTS["retreat_cost"] * retreat_cost)
    return switch_v > stay_v


def _option_card_id(opt, your_state):
    """選択肢が指すカードIDを取得（手札/デッキ/トラッシュ/直接ID）。"""
    cid = getattr(opt, 'cardId', None) or getattr(opt, 'id', None)
    if cid:
        return cid
    idx = getattr(opt, 'index', None)
    area = getattr(opt, 'area', None)
    pile = None
    if area == AreaType.HAND:
        pile = your_state.hand
    elif area == AreaType.DECK:
        pile = getattr(your_state, 'deck', None)
    elif area == AreaType.DISCARD:
        pile = your_state.discard
    if pile is not None and idx is not None and 0 <= idx < len(pile):
        return pile[idx].id
    return None


# --- CARD 選択ハンドラ ---

def _select_attach_target(obs: Observation) -> list[int]:
    """ATTACH_FROM（特性によるエネルギーアタッチ先選択）。不足ポケモン優先・過剰回避。"""
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
            if 0 <= opt.index < len(ps.bench):
                poke = ps.bench[opt.index]
        if poke is None:
            full.append(i)
            continue
        needed  = _max_energy_needed(poke, card_cache, attack_cache)
        current = len(poke.energies)
        if needed > 0 and current < needed:
            (need_active if opt.area == AreaType.ACTIVE else need_bench).append(i)
        else:
            full.append(i)

    candidates = (need_active + need_bench)[:max_count]
    if len(candidates) < min_count:
        candidates += full[:min_count - len(candidates)]
    return candidates


def _select_boss_target(obs: Observation) -> list[int]:
    """ボスの指令のターゲット選択。KO可能ex > KO可能 > ex(エネ多) > その他。stall時は足止め。"""
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

    pokes = [get_poke(options[i]) for i in range(len(options))]
    any_ko = any(p is not None and p.hp <= best_dmg for p in pokes)
    if _is_stalled(state) and not any_ko:
        def stall_key(i):
            poke = pokes[i]
            if poke is None:
                return (99, 99)
            cd = card_cache.get(poke.id)
            retreat = cd.retreatCost if cd is not None else 0
            return (-retreat, len(poke.energies))
        return sorted(range(len(options)), key=stall_key)[:max_count]

    def sort_key(i):
        poke = pokes[i]
        if poke is None:
            return (99, 0, 1, 1)
        cd = card_cache.get(poke.id)
        is_ex  = _is_ex_pokemon(poke, card_cache)
        can_ko = poke.hp <= best_dmg
        energy = len(poke.energies)
        is_psychic  = cd is not None and cd.energyType == EnergyType.PSYCHIC
        has_ability = cd is not None and len(cd.skills) > 0
        if can_ko and is_ex:
            tier = -3
        elif can_ko:
            tier = -2
        elif is_ex:
            tier = -1
        else:
            tier = 0
        return (tier, -energy, 0 if is_psychic else 1, 0 if has_ability else 1)

    return sorted(range(len(options)), key=sort_key)[:max_count]


def _select_search_target(obs: Observation) -> list[int]:
    """デッキからのサーチ先選択。_BRING_ORDER の「N枚目」順（所有=場+手札）。"""
    state = obs.current
    options = obs.select.option
    max_count = obs.select.maxCount
    if state is None or not options:
        return list(range(min(max_count, len(options))))

    your_idx   = state.yourIndex
    your_state = state.players[your_idx]
    card_cache = _get_card_data_cache()
    field_counts = _count_field_pokemon(your_state, card_cache)
    hand_counts  = _hand_counts(your_state)

    def get_card_data(opt):
        for attr in ('id', 'cardId'):
            cid = getattr(opt, attr, None)
            if cid is not None:
                return card_cache.get(cid)
        idx = getattr(opt, 'index', None)
        for state_attr in ('deck', 'discard'):
            pile = getattr(your_state, state_attr, None)
            if pile is not None and idx is not None and 0 <= idx < len(pile):
                cobj = pile[idx]
                cid = getattr(cobj, 'id', None) or getattr(cobj, 'cardId', None)
                return card_cache.get(cid) if cid else None
        return None

    scored: list[tuple[int, int]] = []
    for i, opt in enumerate(options):
        cd    = get_card_data(opt)
        cid   = cd.cardId if cd else -1
        owned = field_counts.get(cid, 0) + hand_counts.get(cid, 0)
        rank  = _bring_rank(cid, owned)
        scored.append((rank if rank is not None else 99, i))
    scored.sort()
    return [i for _, i in scored[:max_count]]


def _select_discard_target(obs: Observation) -> list[int]:
    """DISCARD（ハイパーボール等で手札を捨てる）。保持価値の低い順に捨てる。"""
    state = obs.current
    options = obs.select.option
    max_count = obs.select.maxCount
    if state is None or not options:
        return list(range(min(max_count, len(options))))

    your_idx = state.yourIndex
    your_state = state.players[your_idx]
    card_cache = _get_card_data_cache()
    hand = your_state.hand or []
    discard_pile = your_state.discard

    hand_ids: set[int] = {c.id for c in hand}
    has_lillie = CID_LILLIE in hand_ids
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
        opt = options[i]
        idx = getattr(opt, 'index', None)
        if idx is None or not (0 <= idx < len(hand)):
            return (50, i)
        cid = hand[idx].id
        cd = card_cache.get(cid)
        if cd is None:
            return (40, i)
        ctype = cd.cardType
        if cid in _DISCARD_PROTECT:
            return (99, i)
        if cid == CID_LILLIE and len(hand) >= 4:
            return (90, i)
        if cid == CID_NIGHT_STRETCHER and night_stretcher_valuable:
            return (80, i)
        if ctype in (CardType.BASIC_ENERGY, CardType.SPECIAL_ENERGY):
            return (20, i)
        if ctype == CardType.POKEMON:
            if field_counts.get(cid, 0) >= _FIELD_TARGETS.get(cid, 1):
                return (10, i)
            return (55, i)
        if ctype == CardType.ITEM:
            return (25, i)
        if ctype in (CardType.TOOL, CardType.STADIUM):
            return (30, i)
        if ctype == CardType.SUPPORTER:
            return (60, i)
        return (35, i)

    return sorted(range(len(options)), key=discard_score)[:max_count]


def _select_from_discard(obs: Observation) -> list[int]:
    """トラッシュから回収（夜のタンカ等）。不足する目標ポケモン > 必要エネ > その他。"""
    state = obs.current
    options = obs.select.option
    max_count = obs.select.maxCount
    if state is None or not options:
        return list(range(min(max_count, len(options))))

    your_idx = state.yourIndex
    your_state = state.players[your_idx]
    card_cache = _get_card_data_cache()

    has_energy_in_hand = False
    for c in (your_state.hand or []):
        cd = card_cache.get(c.id)
        if cd and cd.cardType in (CardType.BASIC_ENERGY, CardType.SPECIAL_ENERGY):
            has_energy_in_hand = True
            break
    field_counts = _count_field_pokemon(your_state, card_cache)
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
        if cid in _FIELD_TARGETS and field_counts.get(cid, 0) < _FIELD_TARGETS[cid]:
            return (_SEARCH_PRIORITY.get(cid, 20), i)
        if ctype in (CardType.BASIC_ENERGY, CardType.SPECIAL_ENERGY) and need_energy:
            return (6, i)
        return (50, i)

    return sorted(range(len(options)), key=score)[:max_count]


def _select_bench_placement(obs: Observation) -> list[int]:
    """ベンチに出すポケモンを配置優先順で選ぶ（SETUP_BENCH / TO_BENCH / TO_FIELD）。"""
    state = obs.current
    options = obs.select.option
    max_count = obs.select.maxCount
    if state is None or not options:
        return list(range(min(max_count, len(options))))

    your_state = state.players[state.yourIndex]
    card_cache = _get_card_data_cache()
    field = _count_field_pokemon(your_state, card_cache)

    scored: list[tuple[int, int]] = []
    for i, opt in enumerate(options):
        cid = _option_card_id(opt, your_state)
        rank = _placement_rank(cid, field.get(cid, 0)) if cid is not None else None
        scored.append((rank if rank is not None else 999, i))
    scored.sort()
    return [i for _, i in scored[:max_count]]


def _select_setup_active(obs: Observation) -> list[int]:
    """SETUP_ACTIVE: 開始時バトル場。_SETUP_ACTIVE_PRIORITY 優先、無ければ非例外の高V/HP。"""
    state = obs.current
    options = obs.select.option
    if state is None or not options:
        return [0]
    your_idx = state.yourIndex
    your_state = state.players[your_idx]

    if _SETUP_ACTIVE_PRIORITY:
        def prio(i):
            cid = _option_card_id(options[i], your_state)
            return _SETUP_ACTIVE_PRIORITY.get(cid, 100)
        best = min(range(len(options)), key=prio)
        return [best]

    def rank(i):
        cid = _option_card_id(options[i], your_state)
        is_exc = 1 if cid in _RETREAT_EXCEPTIONS else 0
        v = _evaluate(state, your_idx)  # setupではほぼ定数だが将来拡張用
        return (is_exc, -v)
    best = min(range(len(options)), key=rank)
    return [best]


def _select_switch_target(obs: Observation) -> list[int]:
    """交代先のベンチ選択（にげる後・いれかえ後・強制バトル場）。V最大の体（同点HP）。"""
    state   = obs.current
    options = obs.select.option
    if state is None or not options:
        return [0]
    your_idx   = state.yourIndex
    your_state = state.players[your_idx]

    best_i   = 0
    best_key = None
    for i, opt in enumerate(options):
        area  = getattr(opt, 'area', None)
        index = getattr(opt, 'index', None)
        if area == AreaType.BENCH and index is not None and 0 <= index < len(your_state.bench):
            p = your_state.bench[index]
            if p.id in _RETREAT_EXCEPTIONS:
                continue
            key = (_evaluate(state, your_idx, active_override=p), p.hp)
            if best_key is None or key > best_key:
                best_key, best_i = key, i
    return [best_i]


def _select_heal_target(obs: Observation) -> list[int]:
    """HEAL（ベルのまごころ等の回復対象選択）。バトル場（攻撃に晒され続ける）を最優先し、
    同条件ならHP割合が低い体を優先する。"""
    state = obs.current
    options = obs.select.option
    max_count = obs.select.maxCount
    if state is None or not options:
        return list(range(min(max_count, len(options))))

    your_idx = state.yourIndex
    your_state = state.players[your_idx]

    def score(i: int) -> tuple:
        opt = options[i]
        area = getattr(opt, 'area', None)
        index = getattr(opt, 'index', None)
        poke = None
        if area == AreaType.ACTIVE and your_state.active:
            poke = your_state.active[0]
        elif area == AreaType.BENCH and index is not None and 0 <= index < len(your_state.bench):
            poke = your_state.bench[index]
        if poke is None or poke.maxHp <= 0:
            return (1, 1.0, i)
        is_bench = 0 if area == AreaType.ACTIVE else 1
        return (is_bench, poke.hp / poke.maxHp, i)

    return sorted(range(len(options)), key=score)[:max_count]


def _route_card_selection(obs: Observation) -> list[int]:
    """CARD 選択をコンテキスト/特徴から適切なハンドラに振り分ける。"""
    state = obs.current
    options = obs.select.option
    max_count = obs.select.maxCount
    if state is None or not options:
        return list(range(min(max_count, len(options))))

    if obs.select.context == SelectContext.DISCARD:
        return _select_discard_target(obs)

    your_idx = state.yourIndex
    opp_idx  = 1 - your_idx
    first    = options[0]
    opt_pi   = getattr(first, 'playerIndex', None)
    opt_area = getattr(first, 'area', None)

    if opt_pi == opp_idx and opt_area in (AreaType.BENCH, AreaType.ACTIVE):
        return _select_boss_target(obs)
    if opt_area == AreaType.DECK:
        return _select_search_target(obs)
    if opt_area == AreaType.DISCARD:
        return _select_from_discard(obs)
    return list(range(min(max_count, len(options))))


# --- MAIN アクションの各ハンドラ ---

def _best_attack_index(matches: list[int], options, obs: Observation) -> int:
    """ATTACK選択: KO可能なら最小打点（過剰/反動回避）、不可なら最大打点。弱点×2考慮。"""
    cache = _get_attack_cache()
    state = obs.current

    weak_x2 = False
    opp_hp = 10 ** 9
    if state is not None:
        card_cache = _get_card_data_cache()
        your_state = state.players[state.yourIndex]
        opp_state  = state.players[1 - state.yourIndex]
        attacker   = your_state.active[0] if your_state.active else None
        opp_active = opp_state.active[0] if opp_state.active else None
        if opp_active is not None:
            opp_hp = opp_active.hp
        if attacker is not None and opp_active is not None:
            acd = card_cache.get(attacker.id)
            ocd = card_cache.get(opp_active.id)
            if (acd is not None and ocd is not None and ocd.weakness is not None
                    and ocd.weakness == acd.energyType
                    and attacker.id not in _NO_WEAKNESS_POKEMON):
                weak_x2 = True

    scored: list[tuple[int, int]] = []
    for idx in matches:
        attack_id = options[idx].attackId
        dmg = cache[attack_id].damage if (attack_id is not None and attack_id in cache) else 0
        eff = dmg * 2 if (weak_x2 and dmg > 0) else dmg
        scored.append((eff, idx))

    ko = [(eff, idx) for eff, idx in scored if eff >= opp_hp]
    chosen = min(ko, key=lambda x: x[0])[1] if ko else max(scored, key=lambda x: x[0])[1]

    global _last_attack_turn
    if state is not None:
        _last_attack_turn = state.turn
    return chosen


def _best_attach_index(matches: list[int], options, obs: Observation) -> int | None:
    """アタッチ先決定。エネルギー: 上限内で spec優先度→spread→V。どうぐ: 主攻撃役へ。"""
    state = obs.current
    if state is None:
        for idx in matches:
            if options[idx].inPlayArea == AreaType.ACTIVE:
                return idx
        return matches[0] if matches else None

    your_idx     = state.yourIndex
    your_state   = state.players[your_idx]
    card_cache   = _get_card_data_cache()
    attack_cache = _get_attack_cache()

    def get_target(opt):
        if opt.inPlayArea == AreaType.ACTIVE:
            return your_state.active[0] if your_state.active else None
        if opt.inPlayArea == AreaType.BENCH and opt.inPlayIndex is not None:
            if 0 <= opt.inPlayIndex < len(your_state.bench):
                return your_state.bench[opt.inPlayIndex]
        return None

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

        cd = card_cache.get(card_id) if card_id is not None else None
        is_energy = cd is not None and cd.cardType in (
            CardType.BASIC_ENERGY, CardType.SPECIAL_ENERGY)
        is_tool = cd is not None and cd.cardType == CardType.TOOL

        if is_tool:
            if _should_play_named_card(cd.cardId, obs) and target is not None:
                prio = _TOOL_TARGET_PRIORITY.get(
                    target.id, _ENERGY_ATTACH_PRIORITY.get(target.id, 99))
                tool_candidates.append((prio, idx))
            elif target is None:
                fallback.append(idx)
        elif is_energy or card_id is None:
            # エネルギー、またはカード識別不能（保守的にエネルギー扱い）
            if target is not None:
                needed  = _max_energy_needed(target, card_cache, attack_cache)
                current = len(target.energies)
                if needed > 0 and current < needed:
                    prio = _ENERGY_ATTACH_PRIORITY.get(target.id, 99)
                    v = _evaluate(state, your_idx, active_override=target)
                    energy_candidates.append(((prio, current, -v), idx))
            else:
                fallback.append(idx)
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
    """プレイ優先度: サポーター（優先度順）> ベンチ配置 > 汎用アイテム > 条件付き > その他。"""
    card_cache = _get_card_data_cache()
    your_state = obs.current.players[obs.current.yourIndex] if obs.current else None
    hand = your_state.hand if your_state else None
    field_counts = _count_field_pokemon(your_state, card_cache) if your_state else {}

    supporter_scored: list[tuple[int, int]] = []
    pokemon_scored:   list[tuple[int, int]] = []
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
            elif cd.cardType == CardType.POKEMON:
                rank = _placement_rank(cd.cardId, field_counts.get(cd.cardId, 0))
                if rank is not None:
                    pokemon_scored.append((rank, idx))
            elif cd.cardType == CardType.SUPPORTER:
                prio = _supporter_sort_key(cd.cardId, obs)
                if prio < 999:
                    supporter_scored.append((prio, idx))
            elif cd.cardType == CardType.ITEM:
                if cd.cardId in _CONDITIONAL_CARDS:
                    if _should_play_named_card(cd.cardId, obs):
                        conditional_ok.append(idx)
                elif _should_play_item(cd.cardId, obs):
                    item_idx.append(idx)
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
    if pokemon_scored:
        pokemon_scored.sort()
        return pokemon_scored[0][1]
    candidates = item_idx or conditional_ok or other_idx
    return candidates[0] if candidates else None


def _select_ability(matches: list[int], options, obs: Observation) -> int | None:
    """ABILITY選択。_ABILITY_AVOID のポケモン（自分きぜつ等）は自動発動しない。"""
    state = obs.current
    if state is None:
        return matches[0] if matches else None
    your_state = state.players[state.yourIndex]
    for idx in matches:
        opt = options[idx]
        poke = None
        if opt.area == AreaType.ACTIVE and your_state.active:
            poke = your_state.active[0]
        elif opt.area == AreaType.BENCH and opt.index is not None:
            if 0 <= opt.index < len(your_state.bench):
                poke = your_state.bench[opt.index]
        if poke is not None and poke.id in _ABILITY_AVOID:
            continue
        return idx
    return None


def _select_yes_no(obs: Observation) -> list[int]:
    """YES_NO 選択: 基本は積極的に YES。"""
    options = obs.select.option

    def _yes():
        idx = [i for i, o in enumerate(options) if o.type == OptionType.YES]
        return idx[:1] if idx else [0]

    return _yes()


def _select_evolve(matches: list[int], options, obs: Observation) -> int | None:
    """EVOLVE 選択。進化は基本的に有利なので先頭を選ぶ。"""
    return matches[0] if matches else None


def _select_main_action(obs: Observation) -> list[int]:
    """MAIN 選択: ATTACH > PLAY > EVOLVE > ABILITY > ATTACK > RETREAT > END。"""
    global _non_boss_supporter_played
    state = obs.current
    if state is not None:
        _sync_turn_state(state)

    options = obs.select.option
    card_cache = _get_card_data_cache()

    priority_order = [
        OptionType.ATTACH, OptionType.PLAY, OptionType.EVOLVE,
        OptionType.ABILITY, OptionType.ATTACK, OptionType.RETREAT, OptionType.END,
    ]

    for opt_type in priority_order:
        matches = [i for i, opt in enumerate(options) if opt.type == opt_type]
        if not matches:
            continue

        if opt_type == OptionType.ATTACK:
            return [_best_attack_index(matches, options, obs)]

        if opt_type == OptionType.ATTACH:
            idx = _best_attach_index(matches, options, obs)
            if idx is not None:
                return [idx]
            continue

        if opt_type == OptionType.PLAY:
            idx = _best_play_index(matches, options, obs)
            if idx is not None:
                if state is not None:
                    hand = state.players[state.yourIndex].hand
                    hand_pos = options[idx].index
                    if hand and hand_pos is not None and 0 <= hand_pos < len(hand):
                        cd = card_cache.get(hand[hand_pos].id)
                        if (cd and cd.cardType == CardType.SUPPORTER
                                and cd.cardId != CID_BOSS):
                            _non_boss_supporter_played = True
                return [idx]
            continue

        if opt_type == OptionType.ABILITY:
            idx = _select_ability(matches, options, obs)
            if idx is not None:
                return [idx]
            continue

        if opt_type == OptionType.EVOLVE:
            idx = _select_evolve(matches, options, obs)
            if idx is not None:
                return [idx]
            continue

        if opt_type == OptionType.RETREAT:
            if _should_retreat(obs):
                return [matches[0]]
            continue

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

    if sel_type == SelectType.CARD:
        if obs.select.context == SelectContext.ATTACH_FROM:
            return _select_attach_target(obs)
        if obs.select.context == SelectContext.SETUP_ACTIVE_POKEMON:
            return _select_setup_active(obs)
        if obs.select.context in (
            SelectContext.SETUP_BENCH_POKEMON,
            SelectContext.TO_BENCH,
            SelectContext.TO_FIELD,
        ):
            return _select_bench_placement(obs)
        if obs.select.context in (SelectContext.SWITCH, SelectContext.TO_ACTIVE):
            return _select_switch_target(obs)
        if obs.select.context == SelectContext.HEAL:
            return _select_heal_target(obs)
        return _route_card_selection(obs)

    if sel_type == SelectType.YES_NO:
        return _select_yes_no(obs)

    if sel_type == SelectType.COUNT:
        best = max(range(len(options)), key=lambda i: (options[i].number or 0))
        return [best]

    if max_count == 0:
        return []
    count = min(max_count, len(options))
    return list(range(count))
