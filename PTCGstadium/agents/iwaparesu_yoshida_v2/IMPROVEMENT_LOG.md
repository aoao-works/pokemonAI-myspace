# Iwaparesu (v2) improvement log

Autonomous loop entries go here, newest first. See the loop routine prompt / project memory (`iwaparesu-kaggle-loop-routine`) for the full process this follows each run.

---

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
