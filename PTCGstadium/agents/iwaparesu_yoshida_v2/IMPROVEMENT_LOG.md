# Iwaparesu (v2) improvement log

Autonomous loop entries go here, newest first. See the loop routine prompt / project memory (`iwaparesu-kaggle-loop-routine`) for the full process this follows each run.

---

## Open Items (backlog)

**Read this section first, every run. Update it last, every run** — before appending
your dated entry below. This exists because the chronological log entries grow long
and a "worth revisiting later" note buried in an old entry is easy to miss; this
section is the single place that always reflects current unresolved business.

Rules:
- When you find something worth fixing but don't tackle it this run, add it here
  (one bullet, with enough context to act on later, and which run/date found it).
- When you resolve something (or determine it's not actually worth fixing), move
  its bullet to **Resolved** with the run/date and commit/submission ref that
  addressed it. Don't just delete it — the history has value.
- If you're about to submit a fix for something in this list, note in your dated
  entry which backlog item(s) it addresses.

### Unresolved

- **Buddy-Buddy Poffin (1086) validation pending**: ref `55137619` (2026-07-31 run #3)
  added 2x Buddy-Buddy Poffin (cut 1x Jumbo Ice + 1x Bell's Sincerity) to fix the
  "never got Dwebble into play" loss pattern (see run #3 entry below). Check next run
  whether the "0 Dwebble/Crustle ever in play" loss rate actually drops from this
  run's 6/17 (35%), and whether cutting Jumbo Ice/Bell's Sincerity caused any new
  "died to damage we could've healed through" losses (watch for it, small sample risk).
- **Self-referential "damage counters already on this/opponent's Pokémon" attacks**
  (Flail, Wrathful Hearth, Powerful Rage, Damage Beat, Scarring Shout, etc.) are still
  unestimated in `_usable_damage()` (found 2026-07-31 run #2). Would need to read
  `maxHp - hp` (in 10-HP units) off the specific opposing Pokémon to estimate safely.
  Not yet confirmed to be costing real games — needs replay evidence before acting.
- **Discard-pile-count-based damage attacks** (e.g. Re-Brew) — noted in run #2 as
  another `atk.damage == 0` pattern not yet estimated, lower priority than the
  self-referential family above (rarer in observed replays so far).
- **Toko (1225, x3) may be partly redundant**: found in run #3 — Dwebble's own
  "Ascension" attack already searches the deck for Crustle automatically when used
  (no separate tutor needed), so Toko's "search 1 evolution Pokémon + 1 energy"
  mostly only has unique value for the energy half once Dwebble is out, and is dead
  weight (searches Crustle you can't yet play) before Dwebble is out. Did not touch
  this run to keep the change surgical (one lever at a time) — worth reconsidering
  once the Poffin fix's real impact is known, since freeing more slots for Poffin or
  other basic-stage support might compound.

### Resolved

- **Alakazam-line loss rate after the damage-counter-estimate fix** (opened run #2,
  2026-07-31): checked in run #3 against ref `55129961`'s real replays (34 games).
  Alakazam line (741/742/743) appeared in 4 games this round: 1 win / 3 losses (25%
  win rate) — up from 0 wins / 5 losses (0%) in the pre-fix sample. Sample is still
  small (4 games) but the direction is the right one and the fix is not making things
  worse; traced one loss (ep 89101506) and confirmed the exact -160 HP hit still
  matches Powerful Hand's formula (8 hand cards × 2 counters × 10 HP), so the
  estimate function itself is computing correctly — the remaining losses look like
  "correctly identified a lethal threat but had no good escape that turn" rather than
  a threat-detection miss. Considering resolved as "fix validated, working as
  intended"; not going to chase this further without a bigger sample.
- *(the original run #1/#2 items — Zarude/Night-Stretcher resource-exhaustion fix,
  the ex-immunity-vs-"ignores defender effects" bypass, and the damage-counter-attack
  blind spot — were resolved before this section existed and are only referenced
  informally in the entries below.)*

---

## 2026-07-31 (loop run #3, ~21:55 JST)

**Orientation**: Read the backlog and run #2 entry below. That run shipped ref
`55129961` (the `_effect_damage_estimate()` fix for Powerful Hand/damage-counter
attacks) and left it PENDING pending a real-score/replay check.

**Current standing**:
- `55129961` came back at **549.7** (up from run #2's 518.1, still below run #1's
  592.4/571.2 range — reconfirms the loop's own point that single scores are noisy;
  see below for the replay-level read instead). Leaderboard (fresh CSV, 6014 teams):
  bronze cutoff (rank 601) = **841.1**, essentially flat vs run #2's 840.9. We're
  rank 3844, displayed score 571.2 (Kaggle shows best-ever, not latest). Submission
  count today before this run: 2 (00:59 and 06:58 UTC) — safe to submit a 3rd.

**Replay analysis of `55129961`**: downloaded all 34 public episodes
(`kaggle competitions episodes 55129961` + `replay` per episode) and parsed final
+ full-game board state for both sides (active/bench/hand/prize, plus HP deltas on
our active Pokémon and the opponent's roster across the whole game, not just the
last snapshot). Wrote a reusable parser at analysis time (not checked in — one-off,
see method notes below for anyone who wants to reproduce).
- Record: **17-17 (50.0%)**, consistent with 549.7.
- **Alakazam-line check (validates run #2's fix)**: moved to Resolved above — went
  from 0/5 (0%) win rate pre-fix to 1/4 (25%) post-fix. Real improvement, not
  complete, sample still small.
- **New/bigger finding this run**: of the 17 losses, **6 (35%) never got
  Dwebble(344) into play at all** (not on bench, not active, at any point in the
  whole game — confirmed by scanning every step, not just the final snapshot).
  This is now the single largest identifiable loss pattern this round, bigger than
  the Alakazam-specific issue (3/17) or the classic "Crustle died then we ran dry"
  resource-exhaustion pattern. Checked where the 4 Dwebble copies were sitting at
  game end in these 6 losses: **0 in hand, 0 in discard, all 4 still stuck in the
  deck** in every case. Notably, in 3 of these 6 losses, **Crustle (345) itself
  was sitting dead in our hand** at game end — useless, since Crustle is a Stage-1
  that can only be played by evolving an already-in-play Dwebble, and Dwebble never
  got there.

**Root cause identified**: the deck currently has **no way to specifically search
for a Basic Pokémon** (Dwebble). Toko (1225) searches "an evolution Pokémon + an
energy" (i.e. it can only fetch Crustle, which explains why Crustle was showing up
in dead hands — Toko was finding it while Dwebble sat undrawn). Pokégear 3.0 (1122)
only searches Supporters. So Dwebble access is purely a function of raw draw luck
across an 60-card deck with only 4 copies, with no tutor at all — unusually thin
for how central Dwebble is (it's the *only* way Crustle/Iwaparesu, our whole wall
plan, gets into play).

**Fix applied**: grepped the card DB for "Search your deck for ... Basic Pokémon"
Items and found **Buddy-Buddy Poffin (id 1086)**: "Search your deck for up to 2
Basic Pokémon with 70 HP or less and put them onto your Bench. Then, shuffle your
deck." Dwebble is exactly 70 HP, and it's the *only* Pokémon in our decklist at or
under that threshold (Zarude is 120 HP) — so this card can only ever fetch Dwebble,
no ambiguity, and it places directly onto the Bench (not hand), which is exactly
the deck's own designed opening sequence per the existing `_SETUP_ACTIVE_PRIORITY`
comment (Zarude tanks active while Dwebble sits on bench getting energy, then swaps
in to use Ascension). This is also **the "pre-wired but unused" pattern the loop
process calls out explicitly**: `main.py` already had a `_POKEMON_SEARCH_ITEMS`
mechanism (`_should_play_item` → `_need_basic_target` → generic bench-count gating)
and a `_select_search_target` ranking function (via `_BRING_ORDER`, which already
prioritizes Dwebble copies 0-4 first) — fully generic and ready to use, just wired
to an unused placeholder `CID_POKE_PAD = 0` that never matches any real card
(Poké Pad, the real card, is id 1152 and isn't in this deck; the `0` was always a
"disabled" sentinel, per the project's convention e.g. `CID_ULTRA_BALL = 0`). Also
found via `git`/code comments that Buddy-Buddy Poffin (1086) was *previously in this
deck* and was explicitly cut to make room when Zarude was adopted (comment at
`main.py` "なかよしポフィン(1086)はザルード採用の枠確保のためデッキから抜いた").
So this is arguably a lapsed regression as much as a new idea.

Changes:
1. `main.py`: added `CID_POFFIN = 1086`, added it to `_POKEMON_SEARCH_ITEMS`
   (alongside the still-inert `CID_POKE_PAD`), updated the surrounding comment.
   No changes to `_should_play_item`, `_need_basic_target`, or `_select_search_target`
   — all three already worked generically once the ID was registered.
2. `deck.csv`: added 2x Buddy-Buddy Poffin (1086). To keep this a pure swap (60
   cards, no net deck-size change), cut the 2 single-copy cards that seemed least
   load-bearing: Jumbo Ice (1147, heal-80-if-3+-energy, narrow trigger) and Bell's
   Sincerity (1190, full-heal-if-≤30HP panic button, already partially redundant
   with Night Stretcher's KO recursion). Deliberately did **not** touch the
   3x-Toko/energy counts/other slots — see new backlog item above about Toko's
   partial redundancy with Dwebble's own Ascension search, left for a future run to
   avoid stacking two untested deck changes at once.

**Testing**:
- `sort -n deck.csv | uniq -c`: 60 lines total, max 4 copies of any ID, 1159 (ACE
  SPEC) still at 1. Confirmed 1086 now present at 2 copies, 1147/1190 both at 0.
- Verified `submission/main.py` loads standalone and `read_deck_csv()` parses 60
  cards including id 1086 present.
- Smoke test: `arena.py --p0 agents/iwaparesu_yoshida_v2 --p1 agents/archive/baseline
  --games 40` → 50.0% win rate, **errors: 0**. Pure crash-check per the loop's own
  rules; baseline is a different deck so this doesn't specifically exercise the new
  Poffin logic, it just confirms nothing broke.
- Synced `main.py`/`deck.csv` into `submission/` (cg/ SDK unchanged).
- Submitted: ref **`55137619`**, 2026-07-31 12:55 UTC, PENDING at time of writing.
  **Check its score/replays next run — specifically the "0 Dwebble ever in play"
  loss-rate, which should drop meaningfully from this run's 6/17 (35%) if the fix
  is working.**

**Method note for future runs**: episode/replay JSON parsing needs the *Windows*
path (e.g. `C:\Users\...\Temp\...`), not the Git-Bash `/tmp/...` path, when passed
inside an inline `python -c "..."` string — `/c/venv/Scripts/python.exe` is a native
Windows binary and MSYS/Git-Bash only rewrites POSIX paths that appear as literal
CLI *arguments*, not paths embedded inside a quoted script body. Use `cygpath -w
/tmp/foo` to get the real path, or pass the path as `sys.argv[1]` (an actual CLI
arg) instead of hardcoding `/tmp/...` inside the script text. Cost some time this
run via silent `glob()` matches returning zero results with no error.

**For the next run**:
1. First check ref `55137619`'s score and replays. Key metric: did the "Dwebble
   never got into play" loss share actually drop from 6/17 (35%)? If yes, the fix
   is validated — consider bumping Poffin to 3-4 copies (standard competitive count)
   if slots can be found. If the pattern didn't move, check whether Poffin is
   actually being played early (verify via replay: does Poffin show up in the
   discard pile by turn 2-3 in games where Dwebble ends up on the bench?) before
   concluding the fix failed — could also be a play-priority issue rather than a
   deck-list issue.
2. Watch for any new "died to unhealed damage" pattern that might be attributable to
   cutting Jumbo Ice/Bell's Sincerity — small risk, flagged in backlog, not expected
   to be large given both were single copies with narrow triggers.
3. The Toko-redundancy observation (new backlog item) is worth a dedicated look once
   Poffin's impact is confirmed — don't stack it in without evidence first.

## 2026-07-31 (loop run #2, ~15:00 JST)

**Orientation**: Read the 2026-07-31 run #1 entry below. That run shipped ref `55123159` (the `_ignores_defender_effects` ex-immunity fix) and left it PENDING with instructions to check its real score/replays first before drawing conclusions.

**Current standing**:
- `55123159` (the ex-immunity fix) came back at **518.1** — down from the previous 571.2. Leaderboard (downloaded fresh CSV, 6014 teams): bronze cutoff (rank 601, top 10%) = score **841.2**. Our displayed leaderboard score is still 571.2 (Kaggle keeps your best submission, not latest) at rank 3844. Submission count today before this run: 1 (safe to submit once more).
- **Important context for whoever reads this next**: this competition's score has *always* been extremely noisy run-to-run even without material code changes — e.g. the historical submissions list shows 746.9 → 494.4 → 476.1 within a few days in July, and 787.0 → 503.0 → 524.4 in another stretch. A single ±50-point (or even ±100) swing is well within normal opponent-pool variance and is not on its own evidence that a change was bad.

**Replay analysis of `55123159`'s real games**: downloaded all 31 public episodes for this submission (`kaggle competitions episodes 55123159` + `replay` for each) and parsed `steps[-1]` board state (active/bench/hand/prize) for both sides, same methodology as the prior run.
- Record: **14-17 (45.2%)**, consistent with the 518.1 score being genuinely below-average this round, not just a scoring artifact.
- Checked specifically whether the *ex-immunity fix from last run* could be the cause: scanned all 31 games' logs for any of the 6 "ignores defender effects" ex attack IDs (70,148,207,316,426,837,901,1226,1305,1488 — Ogerpon ex/Tatsugiri ex/Dudunsparce ex/Keldeo ex/Mega Lopunny ex/Mega Starmie ex-type attacks). Only **1 of 31 games** featured one (Nebula Beam, id 1488) — **and we won that game**. So there's no evidence the fix backfired; it just didn't come up much this round. Concluded: **do not revert the ex-immunity fix**, the score drop has a different, better-evidenced cause (below).
- Re-checked the "no Pokémon in play" resource-exhaustion pattern from prior runs: traced *all* steps (not just the final snapshot) for Crustle(345)/Dwebble(344) presence in each of the 17 losses. Correcting a mid-analysis mistake I nearly made (card id 178 in this deck is **Zarude**, not Iwaparesu — Iwaparesu/Crustle is id 345, evolving from Dwebble id 344): 13/17 losses *did* see Crustle reach play (up to full HP, once as high as 250/270), only 4/17 never drew into the Crustle line at all. So the dominant story remains "Crustle got traded/KO'd during a long grindy game and we ran out of backup bodies afterward," matching prior runs' finding — not a new regression.
- **New finding this run**: tallied which opponent Pokémon appear in our 17 losses vs our 14 wins. The **Abra/Kadabra/Alakazam line (ids 741/742/743) appeared in 5/17 losses and 0/14 wins** — the single most lopsided matchup in this sample. Traced one such loss (ep `89057424` vs "R. Yamada") turn-by-turn: opponent's Alakazam used **"Powerful Hand"** (attackId 1072, DB `damage=0`, real text: *"Place 2 damage counters on your opponent's Active Pokémon for each card in your hand"*) against our Crustle and dealt **-400 HP** in one hit (opponent had ~20 cards in hand at that point — 20 × 2 counters × 10 HP/counter = 400, exact match). Alakazam is **not ex**, so this has nothing to do with last run's ex-immunity fix; it's a completely separate bypass of our threat model.

**Root cause identified**: `_usable_damage()` in `main.py` (the same function touched last run) computes threat purely from `atk.damage`, the card DB's static damage field. For "damage counter"-placement attacks like Powerful Hand, `atk.damage` is **0** in the DB — the real damage is entirely described in the effect text, not the numeric field. So `_evaluate()`'s `survive_next`/retreat-value scoring saw Alakazam as a 0-threat attacker and had no reason to retreat Crustle out, right up until it took a near-guaranteed OHKO. Grepped `all_attack()` for `damage=0` attacks whose text contains "damage counter": found ~30 such attacks across the card pool (self-referential ones like "Flail"/"Wrathful Hearth" that scale off the attacker's *own* existing damage counters, discard-pile-count-based ones, and simpler "place N damage counters" / "for each card in your hand" / "until remaining HP is N" ones).

**Fix applied** (`PTCGstadium/agents/iwaparesu_yoshida_v2/main.py`): added `_effect_damage_estimate(atk, attacker_hand_count, defender_hp)`, used as a fallback inside `_usable_damage()` only when `atk.damage == 0`. It handles exactly three regex-matchable, safely-estimable patterns via English-text matching (consistent with the project's English-only card-text-matching convention):
  1. `"until its remaining HP is N"` → `defender_hp - N` (e.g. Dastardly Jab).
  2. `"place/put N damage counters"` (literal digit) → `N * 10` (e.g. Haunt, Sneaky Placement, Phantasmal Barrage).
  3. Same as (2) but combined with `"for each card in your hand"` → `N * 10 * attacker_hand_count` (Powerful Hand specifically — verified this reproduces the exact observed -400 for hand_count=20).
  Deliberately did **not** attempt to estimate the self-referential formulas (Flail, Wrathful Hearth, Powerful Rage, Damage Beat, etc. — "X damage for each damage counter already on this/opponent's Pokémon") or discard-pile-based ones (Re-Brew) — these need additional state I didn't want to thread through in a single surgical change, and getting them wrong (over- or under-estimating) risks new bugs. They stay at their current (0) estimate, same as before this fix — no regression, just not-yet-improved. `attacker_hand_count` is threaded through from `your_state.handCount`/`opp_state.handCount`, which was already available on `PlayerState` but not previously passed into `_usable_damage()`. Weakness doubling is deliberately **not** applied to the effect-estimate branch (real damage-counter placement bypasses weakness in the actual ruleset, same logic as why it bypasses ex-immunity abilities per last run's fix).

**Testing**:
- `sort -n deck.csv | uniq -c`: unchanged, 60 lines, no deck.csv changes this run (pure decision-logic fix again).
- Unit-sanity-checked `_effect_damage_estimate` directly against known cards: Powerful Hand w/ hand=20 → 400 (matches observed real damage exactly), Haunt → 30, Dastardly Jab (hp170) → 160, Sneaky Placement → 20, Undulating Slice (self-referential, should NOT match) → 0. All as expected.
- Smoke test: `arena.py --p0 agents/iwaparesu_yoshida_v2 --p1 agents/archive/baseline --games 40` → 47.5% win rate, **errors: 0**. (Baseline doesn't run Alakazam either, so like last run this is a pure crash-check, not a quality signal for this specific fix.)
- Synced `main.py`/`deck.csv` into `submission/` (`cg/` already in sync), confirmed `submission/main.py` imports and `agent()`/`read_deck_csv()` work standalone.
- Submitted: ref **`55129961`**, 2026-07-31 06:58 UTC, PENDING at time of writing. **Check its score/replays next run.**

**For the next run**:
1. First check ref `55129961`'s score. If replays show Alakazam/damage-counter-attack losses dropped or disappeared relative to this run's rate (5/17), that's strong validation. Given only 5/31 games this round featured Alakazam at all, don't expect the *aggregate* score to move dramatically from this one fix alone — it's a narrow but real leak plug, not a strategy overhaul.
2. The self-referential "X damage for each damage counter on this/opponent's Pokémon" attack family (Flail, Wrathful Hearth, Powerful Rage, Damage Beat/Scarring Shout — several of these are usable by threatening non-ex attackers building up counters over several turns) is still an unaddressed blind spot in `_usable_damage()` if it turns out to matter — would need to track "how many damage counters does this specific opposing Pokémon already have" (visible via `hp` vs `maxHp` on the observed Pokémon dict, i.e. `maxHp - hp` in 10-HP units) to estimate safely. Didn't tackle this run to keep the change surgical; worth a dedicated pass if replay evidence shows it's costing real games.
3. Reconfirmed (again) that a single Kaggle score is noisy — this competition's submission history shows 200-300 point swings across days with presumably-similar code. Don't chase every dip; only act on patterns that show up consistently in replay evidence across multiple losses, as done here (5/17 vs 0/14 for the Alakazam line was the actual trigger, not the raw 518.1 score by itself).

## 2026-07-31 (loop run)

**Orientation**: This was the first run to find `IMPROVEMENT_LOG.md` missing, so created it now. Checked prior state via project memory notes (kaggle-competition-status-20260730, iwaparesu-replay-analysis-20260731, iwaparesu-v2-improvements-20260730) instead, since no log existed yet.

**Current standing** (via `kaggle competitions submissions` + leaderboard CSV):
- Latest completed submission before this run: ref `55113051` (2026-07-30 15:28), score **592.4** — this was the "Night Stretcher + Zarude x4" resource-exhaustion fix from the previous run, and it clearly helped (prior submission was 539.7, and the long-run average before that was ~450-550).
- Leaderboard: 6002 teams total. Bronze cutoff (top 10%, rank 600) = score **840.9**. We are rank **3572**, score 592.4. Gap to bronze ≈ +248.5 points / ~2972 ranks. Meaningfully closer than the 2026-07-29 reading (rank 4933, score 440.8) but still a real gap.
- Submission count today (07-31) before this run: 0. Safe to submit.

**Replay analysis**: Downloaded and parsed all 37 real opponent games (excluding the validation self-play match) from submission `55113051` via `kaggle competitions episodes 55113051` + `kaggle competitions replay <id>`. Record: **21 wins, 16 losses (56.8%)**, consistent with the 592.4 score.

Checked final board state for all 16 losses (active/bench/prize arrays, not just prize count):
- **13 of 16 losses (81%) were still "no-Pokémon" resource-exhaustion losses** (active=[] and bench=[] for us at game end) — so the previous run's Night Stretcher/Zarude fix reduced this pattern's *severity* (win rate up) but did **not** eliminate it as the dominant loss mode. This remains the single biggest lever.
- Traced individual games turn-by-turn (`active`/`bench` id+hp per step) rather than just the final snapshot, for several of the no-Pokémon losses, looking for *why* we ran out of bodies so fast. Two sub-patterns emerged:
  1. Several very short losses (29-51 steps) never got Iwaparesu into play at all — only Zarude (and once Ishizumai) were ever active, and both died repeatedly to ex/mega-ex attackers that Zarude has no protection against. This looks like normal variance in a wall deck that hasn't drawn/evolved into its payload yet, not obviously fixable without deck-level risk (already tuned via Zarude x4 + Night Stretcher last run).
  2. **The important new finding**: in the vs `Yuki Fukamizu` game (Mega Lopunny ex opponent, ep `89001337`), our **Iwaparesu itself** was live in the active slot (170 HP) and took a single hit for **exactly 160 damage** (170→10) from Mega Lopunny ex's "Spiky Hopper" attack — despite Iwaparesu's whole gimmick being 0 damage taken from opponent `ex` Pokémon (`_EX_IMMUNE_POKEMON` in `main.py`).

**Root cause identified**: Spiky Hopper's real card text (confirmed via the engine's own `all_attack()`, English: *"This attack's damage isn't affected by any effects on your opponent's Active Pokémon."*) is a templated "ignores defending Pokémon's abilities/effects" clause — the same clause our own Iwaparesu's "Superb Scissors" attack carries. This is a real, by-design hard-counter mechanic in the actual card game (rare, but exists specifically to punish wall/damage-reduction decks like ours). Searched the full card DB (`all_attack()`) for this exact English marker (`"any effects on your opponent"`) and found **11 total attacks** with it, of which **6 are ex/mega-ex attackers we can realistically face**: Ogerpon ex (Cornerstone Mask), Tatsugiri ex, Dudunsparce ex, Keldeo ex, Mega Lopunny ex, Mega Starmie ex. So this isn't a one-off — it's a real, recurring counter-archetype in the opponent field.

**The actual bug**: this is not a game-engine bug, it's *our own agent's* threat model. `_usable_damage()` in `main.py` (used everywhere via `_evaluate()` for retreat/switch/bench-priority decisions) unconditionally zeroed out **all** damage from any ex/mega-ex attacker against Iwaparesu, including these "ignores defender effects" attacks that are specifically designed to bypass that exact immunity. So our own decision logic thought Iwaparesu was safe (survive_next=1.0, no reason to retreat) right up until it took a near-lethal 160 damage hit it should have seen coming and switched out of.

**Fix applied** (`PTCGstadium/agents/iwaparesu_yoshida_v2/main.py`, `_usable_damage()` + new helper `_ignores_defender_effects()`): moved the ex-immunity zero-out from a blanket function-level short-circuit to a per-attack check inside the existing attack-scanning loop — an attack is now only zeroed out if it does *not* contain the `"any effects on your opponent"` marker in its (English) attack text. Attacks that do carry the marker now compute real damage normally, so `_evaluate()`'s `survive_next`/switch-value scoring will correctly see the threat and should favor retreating Iwaparesu (or not walking it back in) against these specific counters. No deck.csv changes this run — this is a pure decision-logic fix, not a card swap.

Deliberately did **not** attempt a bigger fix (e.g., a full "does this specific attack ignore our ability" precheck before every MAIN/retreat decision) — this is the minimal, surgical change that plugs the concretely-observed bug without restructuring working code, per the project's own lesson about refactors silently changing behavior.

**Testing**:
- `sort -n deck.csv | uniq -c`: unchanged, still 60 lines, max 4 copies (ACE SPECs at 1).
- Smoke test: `arena.py --p0 agents/iwaparesu_yoshida_v2 --p1 agents/archive/baseline --games 30` → 53.3% win rate, **errors: 0**. (Per the loop's own rules, this is a crash-check only, not a quality gate — `baseline` doesn't run any of the 6 "ignores defender effects" ex attackers identified above, so it can't meaningfully exercise this fix either way.)
- Synced `main.py`/`deck.csv` into `submission/` (`cg/` SDK already in sync, only stale `__pycache__` differed).
- Submitted: ref **`55123159`**, 2026-07-31 00:59 UTC, status PENDING at time of writing. **Check `kaggle competitions submissions pokemon-tcg-ai-battle` next run for the resulting score before drawing conclusions.**

**For the next run**: 
1. First check ref `55123159`'s actual score/replays. If it's a clear improvement, the "ignores defender effects" fix is validated — consider whether there's more to extract here (e.g., should the agent actively avoid staying in Iwaparesu at all against a *known* one of these 6 specific attackers if opponent's active/bench roster is scouted?). If flat/worse, remember per the loop's own methodology that a single Kaggle score reading is noisy — don't reverse this fix off one data point, pull replays and check whether the specific no-Pokémon-loss rate actually dropped.
2. The "never drew into Iwaparesu at all" short-game losses (sub-pattern 1 above) are still unaddressed and may be the next-largest lever — would need mulligan/opening-hand statistics across more replays to confirm before acting (small sample this run).
3. Deck-code note for future runs: `before/data/JP_Card_Data.csv` and `before/data/EN_Card_Data.csv` are a useful offline reference DB for card names/effect text when investigating replays (maps card ID → name/type/weakness/attack text in both languages) — much faster than repeatedly querying the live engine. The engine's own `all_card_data()`/`all_attack()` (via `PTCGstadium/cg/api.py`) return **English** text/names (see existing code comment at `main.py:17`), so any future text-based card/attack matching in agent code must match against English strings, not the Japanese CSV wording.
