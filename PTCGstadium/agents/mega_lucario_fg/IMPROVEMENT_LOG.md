# Mega Lucario ex / Fighting Gong — Improvement Log

## Open Items (backlog)

### Unresolved
- **Ex-immune wall matchup**: Mega Lucario ex counts as `ex`, so any opponent with an
  "ignore ex attack damage" passive (Iwaparesu-style — this project's own retired deck
  is the only confirmed example so far) walls Aura Jab/Mega Brave completely (0 damage).
  Hariyama's Wild Press / Makuhita's / Riolu's attacks are not `ex` and still work but
  are weak. Not yet seen in real Kaggle replay data (0/14 games in the pre-pivot sample
  had an opponent with this ability), so unclear how often it matters in practice —
  check replay data for this pattern before investing in a fix.
- **Psychic weakness**: Mega Lucario ex is Psychic-weak (2x damage). The retired
  Iwaparesu deck's worst matchup was Alakazam (12.5% win rate, see
  `iwaparesu_yoshida_v2/IMPROVEMENT_LOG.md`); watch replay data for whether Alakazam-line
  opponents are now doubly dangerous (weakness ×2 stacking with Powerful Hand's
  hand-size-scaling damage).
- **Aura Jab's discard-pile energy re-attach clause** ("attach up to 3 Basic {F} Energy
  from discard to Benched Pokémon in any way you like") has no bespoke handler — it
  falls through to generic CARD-selection fallbacks (`_select_from_discard` for picking
  which energy, naive first-N for picking the bench destination). Works without crashing
  but likely picks a suboptimal destination Pokémon. Low priority unless replay data
  shows it mattering.
- **Solrock/Lunatone package was deliberately cut** from the initial decklist (2026-08-08)
  despite appearing in real opponent decklists for this archetype, because Cosmic Beam
  ("does nothing if no Lunatone on Bench") and Lunar Cycle ("only if Solrock in play")
  have a mutual-dependency the naive heuristic agent could easily misplay (e.g. attacking
  with Cosmic Beam for 0 real damage before Lunatone is out). If early replay data shows
  the deck needs more draw power or a secondary attacker, reconsider re-adding it with a
  bespoke gate (check `Lunatone` on bench before valuing/using Cosmic Beam in
  `_usable_damage`/`_best_attack_index`).

### Resolved
- (none yet — this is the deck's first entry)

---

## 2026-08-08 — Strategy pivot from Iwaparesu wall to Mega Lucario ex aggro

User-requested full strategy pivot away from the Iwaparesu wall deck (which had plateaued
around 400-630 Kaggle score vs a ~842 bronze cutoff despite many iterations — see
`iwaparesu_yoshida_v2/IMPROVEMENT_LOG.md` and project memory `iwaparesu-replay-analysis-*`
for that deck's full history). Pulled 14 fresh real-Kaggle replays (submission 55323098,
2026-08-08) and found the actual opponent meta is diverse, real competitive-format
archetypes: Dragapult ex speed, Mega Lucario ex "Fighting Gong" (3/14 games), Alakazam
(2/14), Mega Abomasnow ex water, Mega Gengar ex/Mandibuzz, Empoleon ex, Meganium, Kyogre,
Miraidon/Iron Thorns, Teal Mask Ogerpon ex. User chose Mega Lucario ex Fighting Gong as
the new base archetype: it was the most-observed archetype in the sample (won 2/3, lost
1/3 against it) and has a structurally simple, low-implementation-risk kit (single-stage
evolution, no complex combo pieces) compared to e.g. Alakazam (hand-size timing) or
Dragapult (multi-piece speed engine).

**Built**: `PTCGstadium/agents/mega_lucario_fg/main.py` — forked from
`iwaparesu_yoshida_v2/main.py`'s deck-agnostic core (evaluation function, action-priority
waterfall, attach/search/placement/discard scoring frameworks — all reused as-is per a
detailed engine-API research pass) with the DECK CONFIG block rewritten for this
archetype and the Iwaparesu-specific wall mechanic (`_EX_IMMUNE_POKEMON`) and healing
trio (Potion/Jumbo Ice/Bell) stripped/zeroed. New deck-specific pieces added: Riolu ->
Mega Lucario ex evolution priorities, `_wally_priority` (Wally's Compassion: heal +
recycle energy off a damaged Mega Lucario ex), `_should_play_judge` (hand-refresh/
disruption gate), Premium Power Pro gated via `_CONDITIONAL_CARDS` to only fire on a turn
we can actually attack.

**Decklist** (60 cards): Riolu(974)x4, Mega Lucario ex(678)x4, Makuhita(673)x3,
Hariyama(674)x3, Fighting Gong(1142)x4, Premium Power Pro(1141)x3, Poké Pad(1152)x4,
Ultra Ball(1121)x4, Judge(1213)x2, Lillie's Determination(1227)x4, Boss's Orders(1182)x3,
Wally's Compassion(1229)x2, Switch(1123)x2, Buddy-Buddy Poffin(1086)x3, Night
Stretcher(1097)x1, Basic {F} Energy(6)x14.

**Smoke test** (crash-check only, per project policy — see backlog note on why local
win rate isn't the quality signal): ~90 games total, `errors: 0` throughout.
- vs Random: 90% (basic competence sanity check)
- vs `archive/baseline2`: 30%, `baseline3`: 60%, `baseline4`: 60%, `sakaki`: 50%
- vs `archive/baseline` (the canonical wall-heavy sparring bot): 10%
- vs `iwaparesu_yoshida_v2` (our own retired wall deck): 20%

The low scores against `baseline`/`iwaparesu_yoshida_v2` specifically are the expected
ex-immune-wall hard-counter (see Open Items above), not a general weakness — confirmed by
inspecting a loss replay against a non-wall opponent (a bug-type Crustle/Dwebble deck)
which showed correct evolution (Riolu -> Mega Lucario ex on schedule) and correct
attack/retreat behavior, just a genuine close loss, no logic bug. The more representative
`baseline2-4`/`sakaki` numbers (30-60%) look like a reasonable starting point for a fresh
decklist that hasn't been tuned at all yet.

**Submitted**: ref `55341833` (2026-08-08 ~05:16 UTC), synced to `submission/`. Also
updated `automation/loop_prompt.txt` to point the unattended 6-hourly loop at this folder
instead of `iwaparesu_yoshida_v2` (it was previously fully autonomous and would have
silently reverted this pivot on its next scheduled run otherwise) and updated `CLAUDE.md`'s
"現在の提出エージェント" section. Real Kaggle score for this first submission not yet
available at write time — **next run should check ref 55341833's score/replays first**,
before making any further changes.
