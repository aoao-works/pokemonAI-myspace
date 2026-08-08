import os
import re

from cg.api import (
    Observation, SelectType, SelectContext, OptionType, AreaType, CardType,
    EnergyType, to_observation_class, all_attack, all_card_data,
)

# =====================================================================
# ポケモンTCG AIエージェント — 汎用アーキテクチャ版（デッキ: メガルカリオex
# 「ファイティングゴング」速攻）
# ---------------------------------------------------------------------
# 設計: 「デッキ非依存の中核アルゴリズム」＋「デッキ固有の設定ブロック」。
#   中核は iwaparesu_yoshida_v2/main.py と共通（評価関数V・行動優先度・
#   アタッチ/サーチ/配置/捨て先の枠組み・定番トレーナー処理）。
#   イワパレス固有だった「ex無効の壁特性」判定・回復トリオ（いいきずぐすり/
#   ジャンボアイス/ベルのまごころ）は本デッキでは不使用のため無効化のみ
#   （壁ではなくメガルカリオexで殴り倒すアグロデッキ）。
#   下の「DECK CONFIG」だけがデッキ固有。ここを編集すれば別デッキへ流用可能。
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

# --- ポケモンID（メガルカリオexデッキ）---
# リオル→メガルカリオexの1進化ライン。マキシマムベルト等は不採用、代わりに
# マクノシタ→ハリテヤマ（進化時に相手ベンチをバトル場へ引きずり出す特性＝
# 無料のガスト効果）で並行進化ラインを持つ2枚看板構成。
CID_RIOLU         = 974   # リオル（たね, HP70, パンチ 無無 30。フリップ無しの安定打点）
CID_MEGA_LUCARIO  = 678   # メガルカリオex（1進化, HP340, オーラのつぶて 無1で130＋
                          # トラッシュの基本闘エネ最大3枚をベンチへ好きに再アタッチ／
                          # メガブレイブ 無無2で270・ただし次の自分の番は使用不可）
                          # ★本デッキの主力。被弱点はエスパー（アラカザム等に注意）。
                          # ex ではなく megaEx なのできぜつ時に相手へ3枚のサイドを渡す点に留意。
CID_MAKUHITA      = 673   # マクノシタ（たね, HP80）
CID_HARIYAMA      = 674   # ハリテヤマ（1進化, HP150, 特性ヘビーしょうかん＝マクノシタから
                          # 進化させた時1回、相手ベンチ1体をバトル場へ強制的に引きずり出せる）

# --- 相手のポケモンexからワザダメージを受けない特性を持つ味方ポケモン ---
# 本デッキは壁ではなく殴り勝つアグロなので該当ポケモン無し（イワパレス由来の
# 仕組みだけコードとして残置。空集合なら _usable_damage 内の分岐は常にfalseで無害）。
_EX_IMMUNE_POKEMON: frozenset[int] = frozenset()

# --- 回復カード（このデッキは不採用のため全て0＝無効なセンチネル）---
CID_POTION      = 0
CID_JUMBO_ICE   = 0
CID_BELL        = 0

# --- 退避用どうぐ（このデッキは不採用）---
CID_EMERGENCY_BOARD = 0

# --- 定番トレーナー ---
CID_BOSS            = 1182  # ボスの指令（KO/スナイプ対象がいる時最優先で使用）
CID_LILLIE          = 1227  # リーリエの決心（手札を戻して6/8枚引く）
CID_MATSUBA         = 0     # このデッキには無い
CID_POKE_PAD        = 1152  # ポケパッド（ルールボックス無しポケモンをサーチ＝リオル/マクノシタ/ハリテヤマ）
CID_ULTRA_BALL      = 1121  # ハイパーボール（手札2枚トラッシュで任意のポケモンをサーチ＝メガルカリオexも対象）
CID_NIGHT_STRETCHER = 1097  # 夜のタンカ（トラッシュのポケモン/基本エネルギーを1枚手札へ）
CID_SWITCH          = 1123  # ポケモンいれかえ
CID_XEROSIC         = 0     # このデッキには無い

# --- アグロ加速用トレーナー ---
CID_FIGHTING_GONG       = 1142  # ファイティングゴング（基本闘エネorたね闘ポケモンをサーチ）
CID_PREMIUM_POWER_PRO   = 1141  # プレミアムパワープロ（このターン中、闘ポケモンのワザ+30ダメージ）
CID_WALLY               = 1229  # ワルビの信念（メガ進化exポケモン1体の全回復＋回復した場合は
                                 # そのポケモンに付いていたエネルギーを全て手札に戻す＝
                                 # メガルカリオexの延命とエネルギー再利用を同時に行う要）
CID_POFFIN              = 1086  # なかよしポフィン（HP70以下のたねポケモンを2匹までベンチへ＝リオル専用）
CID_JUDGE               = 1213  # ジャッジ（手札を山札に戻し互いに4枚引く。手札事故の立て直し／妨害）

# --- 山札切れ回避のしきい値 ---
_DECKOUT_GUARD_THRESHOLD = 15

# --- 目標盤面（ID: 在場したい数） ---
_FIELD_TARGETS: dict[int, int] = {
    CID_RIOLU: 2,
    CID_MEGA_LUCARIO: 2,
    CID_HARIYAMA: 1,
}

# --- 場に置く上限（ID: 最大在場数）---
_FIELD_CAP: dict[int, int] = {
    CID_RIOLU: 4, CID_MEGA_LUCARIO: 4, CID_MAKUHITA: 3, CID_HARIYAMA: 3,
}

# --- ベンチ配置の優先順（(カードID, すでに場にいる枚数)。小さいほど先に出す）---
# メガルカリオexは「たね」ではないのでベンチへ直接は出せない（リオルに進化で乗せる）。
# ここに載るのはベンチへ直接置けるたねポケモン（リオル/マクノシタ）のみ。
_BENCH_PLACEMENT_ORDER: list[tuple[int, int]] = [
    (CID_RIOLU, 0),
    (CID_RIOLU, 1),
    (CID_RIOLU, 2),
    (CID_RIOLU, 3),
    (CID_MAKUHITA, 0),
    (CID_MAKUHITA, 1),
    (CID_MAKUHITA, 2),
]

# --- サーチ／持ってくる順（(カードID, すでに所有している枚数=場+手札)。小さいほど優先）---
# 基本闘エネルギー(id=6)も対象に含め、リオルを2体確保した後は手札のエネ切れを防ぐ。
_ENERGY_CARD_ID = 6  # Basic {F} Energy
_BRING_ORDER: list[tuple[int, int]] = [
    (CID_RIOLU, 0),
    (CID_RIOLU, 1),
    (_ENERGY_CARD_ID, 0),
    (CID_MEGA_LUCARIO, 0),
    (CID_RIOLU, 2),
    (_ENERGY_CARD_ID, 1),
    (CID_MEGA_LUCARIO, 1),
    (CID_RIOLU, 3),
    (CID_MAKUHITA, 0),
    (CID_MAKUHITA, 1),
    (CID_HARIYAMA, 0),
    (_ENERGY_CARD_ID, 2),
    (CID_MEGA_LUCARIO, 2),
    (CID_MAKUHITA, 2),
    (CID_HARIYAMA, 1),
    (CID_MEGA_LUCARIO, 3),
    (CID_HARIYAMA, 2),
]

# --- 夜のタンカ等の回収優先（小さいほど優先）---
_SEARCH_PRIORITY: dict[int, int] = {
    CID_RIOLU: 0, CID_MEGA_LUCARIO: 1, CID_MAKUHITA: 2, CID_HARIYAMA: 3,
}

# --- エネルギーアタッチ優先度（小さいほど優先）。主攻撃役に集める ---
_ENERGY_ATTACH_PRIORITY: dict[int, int] = {
    CID_MEGA_LUCARIO: 0,  # オーラのつぶて/メガブレイブ
    CID_HARIYAMA: 1,
    CID_RIOLU: 2,
    CID_MAKUHITA: 3,
}

# --- ポケモンのどうぐの貼り先優先（このデッキは どうぐ 不採用。空なら
# _ENERGY_ATTACH_PRIORITY を自動的に流用するので問題ない）---
_TOOL_TARGET_PRIORITY: dict[int, int] = {}
_TOOL_TARGET_PRIORITY_OVERRIDE: dict[int, dict[int, int]] = {}

# --- エネルギー上限の明示（省略時は全技中の最大コストを自動採用）---
_ENERGY_CAP_OVERRIDE: dict[int, int] = {}

# --- バトル場に出したくない／積極的に交代したいポケモン ---
_RETREAT_EXCEPTIONS: frozenset[int] = frozenset()

# --- スタート時バトル場の優先（小さいほど優先）---
# ゲーム開始時に場に置けるのはたねポケモンのみ（リオル/マクノシタ）。
# リオルは1エネで即攻撃できるため最優先。
_SETUP_ACTIVE_PRIORITY: dict[int, int] = {
    CID_RIOLU: 0,
    CID_MAKUHITA: 1,
}

# --- 自動発動しない特性（自分きぜつ等）。このデッキは該当なし ---
_ABILITY_AVOID: frozenset[int] = frozenset()

# --- 弱点×2を計算しないポケモン（特殊技）。このデッキは該当なし ---
_NO_WEAKNESS_POKEMON: frozenset[int] = frozenset()

# --- 条件付きどうぐ／アイテム（KO圏で貼る等）---
# プレミアムパワープロは「このターン中、闘ポケモンのワザ+30ダメージ」という
# 1ターン限定バフなので、攻撃できないセットアップターンに腐らせないよう
# バトル場にエネルギーが付いている（＝このターン攻撃できる）時のみ使う。
_CONDITIONAL_CARDS: frozenset[int] = frozenset({CID_PREMIUM_POWER_PRO})

# --- 絶対に捨てないカード（捨て先選択で保護）---
_DISCARD_PROTECT: frozenset[int] = frozenset()

# --- サポーターID と 使用優先（小さいほど先。ボス/ワルビ/リーリエ/ジャッジは中核で個別判断）---
_SUPPORTER_IDS: frozenset[int] = frozenset({
    CID_BOSS, CID_LILLIE, CID_WALLY, CID_JUDGE,
})
_SUPPORTER_PRIORITY: dict[int, int] = {}

# --- ポケモンをサーチするグッズ（盤面が埋まっていれば温存）---
_POKEMON_SEARCH_ITEMS: frozenset[int] = frozenset({
    CID_POKE_PAD,
    CID_ULTRA_BALL,
    CID_POFFIN,
})


def _wally_priority(obs: "Observation") -> int | None:
    """ワルビの信念の優先度。場のメガルカリオexが1体でも被弾していれば使う
    （全回復＋回復した場合は付いていたエネルギーを全て手札に戻せるので、
    倒れかけの主力を救出しつつエネルギーを再利用できる）。対象が無ければ None。"""
    state = obs.current
    if state is None:
        return None
    your_state = state.players[state.yourIndex]
    for p in _field_mons(your_state):
        if p.id == CID_MEGA_LUCARIO and p.hp < p.maxHp:
            return 18
    return None


def _should_play_judge(obs: "Observation") -> bool:
    """ジャッジ（手札を山札に戻して互いに4枚引く）を使う価値があるか。
    自分の手札が事故気味（2枚以下）で立て直したい時、または相手が手札を
    5枚以上溜め込んでいて妨害価値が高い時のみ使う。山札切れ間近なら温存。"""
    state = obs.current
    if state is None:
        return True
    your_idx = state.yourIndex
    your_state = state.players[your_idx]
    opp_state = state.players[1 - your_idx]
    if your_state.deckCount <= _DECKOUT_GUARD_THRESHOLD:
        return False
    hand_size = len(your_state.hand or [])
    return hand_size <= 2 or opp_state.handCount >= 5


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


def _ignores_defender_effects(atk) -> bool:
    """このワザが「このワザのダメージは、相手のバトルポケモンにかかっている効果を
    計算しない」系（英語テキストでは "any effects on your opponent's Active Pokémon"）か。
    本デッキでは _EX_IMMUNE_POKEMON が空集合のため実質未使用だが、_usable_damage の
    汎用ロジックとして中核に残置（他デッキへ流用する際に再度必要になるため）。"""
    return atk is not None and "any effects on your opponent" in (atk.text or "")


_DMG_COUNTER_UNTIL_RE = re.compile(r"until its remaining hp is (\d+)", re.IGNORECASE)
_DMG_COUNTER_FIXED_RE = re.compile(r"(?:place|put)\s+(\d+)\s+damage counters?\b", re.IGNORECASE)
_DMG_COUNTER_PER_HAND_RE = re.compile(r"for each card in your hand", re.IGNORECASE)


def _effect_damage_estimate(atk, attacker_hand_count: int, defender_hp: int) -> int:
    """カードDBの damage=0 でも実際はダメージカウンターを乗せて実質ダメージを与える
    ワザ（例: アラカザムの「パワフルハンド」＝手札1枚につきダメカン2個）の概算ダメージ。
    このデッキ自身は使わないが、相手の脅威評価（survive_next/opp_bench_threat/
    ボス狙い撃ち判断）に汎用的に使う。複雑な効果は無理に推定せず0のまま扱う。"""
    if atk is None or not atk.text or "damage counter" not in atk.text.lower():
        return 0
    m_until = _DMG_COUNTER_UNTIL_RE.search(atk.text)
    if m_until:
        return max(0, defender_hp - int(m_until.group(1)))
    m_fixed = _DMG_COUNTER_FIXED_RE.search(atk.text)
    if m_fixed:
        n = int(m_fixed.group(1))
        if _DMG_COUNTER_PER_HAND_RE.search(atk.text):
            n *= max(attacker_hand_count, 0)
        return n * 10
    return 0


def _usable_damage(poke, card_cache: dict, attack_cache: dict, defender=None,
                    attacker_hand_count: int = 0) -> int:
    """今の付与エネルギーで実際に撃てる技の最大ダメージ（弱点×2込み、免除ポケ除く）。"""
    if poke is None:
        return 0
    cd = card_cache.get(poke.id)
    if cd is None:
        return 0
    ex_immune = (defender is not None and defender.id in _EX_IMMUNE_POKEMON
                 and _is_ex_pokemon(poke, card_cache))
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
        if ex_immune and not _ignores_defender_effects(atk):
            continue
        dmg = atk.damage
        if dmg > 0 and weak:
            dmg *= 2
        if dmg == 0:
            dmg = _effect_damage_estimate(
                atk, attacker_hand_count, defender.hp if defender is not None else 0)
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

    my_dmg  = _usable_damage(active, card_cache, attack_cache, defender=opp_active,
                              attacker_hand_count=your_state.handCount)
    opp_dmg = _usable_damage(opp_active, card_cache, attack_cache, defender=active,
                              attacker_hand_count=opp_state.handCount)
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
        d = _usable_damage(p, card_cache, attack_cache, defender=active,
                            attacker_hand_count=opp_state.handCount)
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


def _boss_priority(obs: Observation) -> int | None:
    """ボスの指令の優先度（小さいほど優先、None=今ターンは使わない）。
    ベンチに実際にKO/スナイプできる的がある「確定KOの好機」は最優先（5）で
    サーチ系より先に使う（1ターン待つと相手に退避・回復されて機会を失うため）。
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
    ボス/ワルビ/リーリエ/ジャッジは中核で個別判断、その他は _SUPPORTER_PRIORITY。"""
    if card_id == CID_BOSS:
        prio = _boss_priority(obs)
        return prio if prio is not None else 999
    if card_id == CID_WALLY:
        prio = _wally_priority(obs)
        return prio if prio is not None else 999
    if card_id == CID_LILLIE:
        return 45 if _should_play_lillie(obs) else 999
    if card_id == CID_JUDGE:
        return 40 if _should_play_judge(obs) else 999
    return _SUPPORTER_PRIORITY.get(card_id, 30)


def _should_play_named_card(card_id: int, obs: Observation) -> bool:
    """条件付きどうぐ/アイテムの使用可否。
    プレミアムパワープロは「このターン中バフ」なので、バトル場に攻撃可能な
    エネルギーが付いている（＝このターン実際に攻撃できる）時のみ使う。"""
    if card_id == CID_PREMIUM_POWER_PRO:
        state = obs.current
        if state is None:
            return True
        your_state = state.players[state.yourIndex]
        active = your_state.active[0] if your_state.active else None
        return active is not None and len(active.energies) > 0
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


def _should_play_item(card_id: int, obs: Observation) -> bool:
    """汎用グッズの使用可否。サーチ系は盤面が埋まっていれば温存、交代は個別判断。"""
    if card_id == CID_SWITCH:
        return _should_play_switch_item(obs)
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
    """HEAL（ワルビの信念等の回復対象選択）。バトル場（攻撃に晒され続ける）を最優先し、
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
                target_prio_map = _TOOL_TARGET_PRIORITY_OVERRIDE.get(
                    cd.cardId, _TOOL_TARGET_PRIORITY)
                prio = target_prio_map.get(
                    target.id, _ENERGY_ATTACH_PRIORITY.get(target.id, 99))
                tool_candidates.append((prio, idx))
            elif target is None:
                fallback.append(idx)
        elif is_energy or card_id is None:
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


def _should_play_stadium(card_id: int, obs: Observation) -> bool:
    """スタジアムの使用可否。自分の同名スタジアムが既に場にある間は打ち直さない。"""
    state = obs.current
    if state is None:
        return True
    current = state.stadium
    return not (current and current[0].id == card_id)


def _best_play_index(matches: list[int], options, obs: Observation) -> int | None:
    """プレイ優先度: サポーター（優先度順）> スタジアム > ベンチ配置 > 汎用アイテム > 条件付き > その他。"""
    card_cache = _get_card_data_cache()
    your_state = obs.current.players[obs.current.yourIndex] if obs.current else None
    hand = your_state.hand if your_state else None
    field_counts = _count_field_pokemon(your_state, card_cache) if your_state else {}

    supporter_scored: list[tuple[int, int]] = []
    pokemon_scored:   list[tuple[int, int]] = []
    stadium_idx:      list[int] = []
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
            elif cd.cardType == CardType.STADIUM:
                if _should_play_stadium(cd.cardId, obs):
                    stadium_idx.append(idx)
            elif cd.cardType == CardType.TOOL:
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
    if stadium_idx:
        return stadium_idx[0]
    if pokemon_scored:
        pokemon_scored.sort()
        return pokemon_scored[0][1]
    candidates = item_idx or conditional_ok or other_idx
    return candidates[0] if candidates else None


def _select_ability(matches: list[int], options, obs: Observation) -> int | None:
    """ABILITY選択。_ABILITY_AVOID のポケモン（自分きぜつ等）は自動発動しない。
    本デッキではハリテヤマの特性（進化時に相手ベンチをバトル場へ引きずり出す＝
    無料のガスト効果）が常に有益なので、条件なしで発動可能なら発動する。"""
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
    """EVOLVE 選択。進化は基本的に有利なので先頭を選ぶ（リオル→メガルカリオex、
    マクノシタ→ハリテヤマともに即進化して問題ない構成）。"""
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
