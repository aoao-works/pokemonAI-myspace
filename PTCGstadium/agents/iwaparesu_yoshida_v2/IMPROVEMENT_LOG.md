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

- **Alakazam-line matchup — still bad, still small-sample, root cause now
  clearer (run #6, 2026-08-01)**: ref `55151278`'s replays showed 4 Alakazam-line
  games, 1 win (25%), basically flat vs run #5's 2/7 (28.6%) — sample too small to
  call decisively but not improving. Crucially, traced *why* the 2 losses lost even
  with 3 Xerosic copies now available: ep `89242979` (84 steps) never dropped the
  opponent's hand to ≤3 at all the whole game — i.e. **we never drew any of the 3
  Xerosic copies**, so the copy-count bump doesn't help if it's simply not drawn.
  ep `89245086` (67 steps) got exactly 1 reset off (7→3 at step 48) but the game
  ended before a 2nd was needed/possible. By contrast the 1 win (`89251840`, 119
  steps) *did* show 2 genuine resets (16→3 at step 71, 7→3 at step 105) — so the
  3-copy bump **does work mechanically when drawn early enough**, it's a draw-timing
  problem, not a firing-logic problem. Next lever if this keeps being the worst
  matchup: consider whether an existing search effect (Toko searches "evolution
  Pokémon" only, Pokégear 3.0 searches Supporters generically) could be biased
  toward fetching Xerosic specifically when facing a hoarding opponent — not
  attempted yet, no code changes made this run in this area (see "Fix applied"
  below, this run's one change was the Poffin bump instead). Do NOT bump Xerosic to
  4 copies without new evidence — 3 copies already demonstrated correct behavior
  when drawn; the bottleneck looks like draw variance, not ammo count.
- **Self-referential "damage counters already on this/opponent's Pokémon" attacks**
  (Flail, Wrathful Hearth, Powerful Rage, Damage Beat, Scarring Shout, etc.) are still
  unestimated in `_usable_damage()` (found 2026-07-31 run #2). Would need to read
  `maxHp - hp` (in 10-HP units) off the specific opposing Pokémon to estimate safely.
  Not yet confirmed to be costing real games — needs replay evidence before acting.
- **Discard-pile-count-based damage attacks** (e.g. Re-Brew) — noted in run #2 as
  another `atk.damage == 0` pattern not yet estimated, lower priority than the
  self-referential family above (rarer in observed replays so far).
- **"No active Pokémon" (engine reason=3) losses remain the single largest loss
  bucket even after the Poffin 3-copy fix — but traced to already-known,
  structurally-hard-to-fix causes, not a new bug (run #7, 2026-08-01)**: in ref
  `55157226`'s 16 losses, engine-reported end reason was 3 ("no active Pokémon")
  in **8/16 (50%)**, vs reason=1 (opponent took all 6 prizes normally, 6/16) and
  reason=2 (we decked out, 2/16 — see below). Of those 8, only 3 are the narrow
  "never had a 2nd Pokémon in play at all" pattern the Poffin fix targeted (down
  hard from run #6's 6/19 — the fix is working, see Resolved below); the other
  5/8 built a real board (max concurrent Pokémon in play 2-6) but still got wiped
  out by the end. Traced 4 of those 5 individually: 2 were Fire-type one-shots
  (`Ethan's Typhlosion` decks, eps `89302769`/`89304327` — already-known,
  accepted weakness, immunity ability doesn't cover weakness damage); 1 was
  `Iono's Bellibolt ex`'s pre-evolution **`Iono's Voltorb`** (non-ex, so our
  ex-immunity correctly does NOT apply) using an apparent self-destruct-style
  attack for **-380 damage** (with -20 recoil to itself) that one-shots Crustle
  regardless of HP total (ep `89325603`) — not fixable by copy-count tuning; 1
  was `Marnie's Grimmsnarl ex` OHKOing our **Zarude** (a non-wall attacker with no
  ex-immunity ability at all — only the Crustle/Iwaparesu line has the ability)
  for -180 (ep `89289658`) — expected behavior, not a bug. The 5th (ep
  `89302139`, Applin/Dipplin/Seaking toolbox) died to a high-damage non-ex
  attacker (`Seaking`, id 93, -100 dmg) in the same "ordinary attrition" pattern
  CLAUDE.md already documents as the deck's known core weakness. **Conclusion:
  no new fixable lever found this run** — the remaining reason=3 losses trace to
  things this deck was already known to be weak to (Fire weakness, non-wall
  Pokémon lacking the immunity ability, big non-ex hits) rather than an
  addressable bug or an undertuned card count. Further gains here would likely
  need a structural change (e.g. more redundancy getting Crustle/Iwaparesu itself
  back into play after a KO, since it's the only thing the ability actually
  protects) rather than another deck.csv count tweak — not attempted this run,
  no strong enough evidence for a specific structural change yet.
- **Deck-out dynamics — informational, not actionable (run #7, 2026-08-01)**: of
  ref `55157226`'s 19 wins, **14 (73.7%) came from the opponent decking out**
  (engine reason=2), confirming the wall/stall strategy's designed win condition
  is working as intended in practice, not just in theory. We ourselves decked out
  in only 2/16 losses (12.5%), and both of those were long grindy games where we
  were actually *ahead* on prizes (5-1 and a 6-6 mirror-ish game) when our own
  deck ran dry — i.e. decking out is already working in our favor far more than
  against us, so it's not a lever worth pulling in either direction right now.

### Resolved

- **Buddy-Buddy Poffin 2→3 bump (run #6) — validated, fix confirmed working
  (run #7, 2026-08-01)**: checked ref `55157226`'s replays (35 games) against
  run #6's own "check next run" question — did the "never had a 2nd bench
  Pokémon" loss share drop from 31.6%? **Yes, sharply**: using the same strict
  definition (max concurrent Pokémon in play across the whole game < 2), it's
  now **3/16 losses (18.8%)**, down from run #6's re-check of 6/19 (31.6%) and
  run #5's 4/14 (29%) — a clean, large improvement in the right direction with
  no offsetting new pattern found from the Toko 2→1 trim (no "Toko stuck useless
  in hand" cases observed this batch). Score itself came back lower (555.5 vs
  576.7) but per this project's noise-tolerance rule that's not the signal — the
  targeted loss-pattern rate is, and it moved decisively. Considering this fix
  fully validated; no further action needed here. (The broader "no active
  Pokémon" loss bucket is still the largest one overall, 50% of losses, but the
  other 5/8 in it are different, already-understood causes — see new Unresolved
  item above, not a Poffin-related residual.)
- **"Single Pokémon the whole game" sudden-death losses — acted on (run #6,
  2026-08-01)**: this pattern (opened run #5) recurred at almost the same rate in
  ref `55151278`'s replays — 6/19 losses (31.6%) vs run #5's 4/14 (29%), confirming
  it's real and persistent, not a one-batch fluke. Traced all 6 losses' opening
  hands and found the "bad mulligan variance" theory from run #5 was too narrow:
  5/6 (83%) never drew *either* copy of Buddy-Buddy Poffin at all (not just a thin
  opening hand — one case, ep `89256504`, was traced turn-by-turn through 62 steps
  and Poffin (1086) never once appeared in hand the entire game). Toko (1225) was
  sitting in hand for many turns in that same game but was mechanically useless —
  it can only search "an evolution Pokémon" (refetch Crustle) or an energy, not a
  Basic, so with no Dwebble ever on the bench it had nothing to convert. This is
  exactly the scenario run #3's original forward note anticipated. Fix: bumped
  Buddy-Buddy Poffin (1086) 2→3, funded by trimming Toko (1225) 1→ from its current
  2 down to 1 — Toko's remaining "search 1 energy" value is real but smaller than
  giving the deck's only Basic-Pokémon search effect a meaningfully better draw
  rate. See dated entry below for full testing/submission details (ref `55157226`).
  **Check next run**: does the "never had a 2nd bench Pokémon" loss rate actually
  drop from this run's 6/19 (31.6%)? Also watch for any new "Toko in hand but
  couldn't refetch Crustle" pattern from the 2→1 trim (small risk, Toko was already
  trimmed twice before with no regression found either time).
- **Toko/Morty's Conviction trim (run #4) — no regression found**: checked run #5
  (2026-08-01) against `55148965`'s replays. Only 2/14 losses (14%) never saw the
  Dwebble/Crustle line in play at all — same order of magnitude as run #4's own 1/23
  (4%) post-Poffin-fix baseline, not a meaningful jump. No evidence the Toko 2-copy /
  Morty's-Conviction-1-copy trim from run #4 hurt draw consistency. (Morty's
  Conviction has since been cut to 0 entirely this run — see dated entry — to fund
  the Xerosic bump above; this finding is part of why that felt safe to do.)
- **Buddy-Buddy Poffin (1086) validated**: checked run #4 (2026-08-01) against ref
  `55137619`'s real replays (37 games). The "Dwebble/Crustle line never got into
  play" loss share dropped to **1/23 (4%)**, down hard from run #3's pre-fix 6/17
  (35%) — a clear, large improvement, confirming the fix works as intended. (The
  score itself came back lower — 507.2 vs the prior 549.7/571.9 — but per this
  project's own noise-tolerance rule, a single aggregate score is not the signal;
  the specific loss-pattern rate is, and it moved decisively in the right direction.)
  No new "died to damage we could've healed through" pattern attributable to cutting
  Jumbo Ice/Bell's Sincerity was found in this round's losses.
- **Toko (1225, x3) redundancy**: addressed run #4 (2026-08-01, ref `55148965`) —
  trimmed 3→2 copies (not all the way to 1) now that Poffin's fix (above) confirms
  Dwebble reliably reaches the bench without needing Toko as a backup route; kept 2
  rather than 1 because Toko's "search 1 energy" half still has standalone value once
  Dwebble/Crustle is already out. Freed 1 of the 2 slots this trim created; the other
  came from cutting 1x Morty's Conviction (1187, 2→1) — see dated entry for full
  rationale. Both went toward the 2x Xerosic's Machinations add above.
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

## 2026-08-01 (loop run #7, ~22:35-23:15 JST)

**⚠️ git push failed again this run — same issue as run #6, see note near the
end.** Local `main` had this run's commit but could not be pushed to `origin`
at the time this entry was written. If you are reading this from a *pushed*
copy of the repo, someone/something pushed it after the fact — otherwise,
**check `git status`/`git log` vs `origin/main` before assuming this log entry
or the backlog changes above are visible remotely.**

**Orientation**: Read the backlog first. Top item was run #6's own "check next
run" question — did ref `55157226`'s (Poffin 2→3, Toko 2→1) score/replays show
the "never had a 2nd bench Pokémon" loss rate actually drop from 31.6%?

**Current standing**:
- `55157226` (run #6's Poffin fix) is COMPLETE at **555.5**. `55151278` (run #5's
  Xerosic fix) is still our best-ever at **576.7**. Leaderboard (fresh CSV, 6094
  teams): bronze cutoff (top 10%, rank 609) = **835.3**, essentially flat vs run
  #6's 836.5. We're rank **3826** (best-ever score 576.7). Submissions today
  (08-01) before this run: 2 (`55151278` 01:50 UTC, `55157226` 07:51 UTC).

**Replay analysis of `55157226`** (all 35 public episodes, full active/bench/
hand/prize trace per step for both perspectives, same methodology as prior
runs, extended this round to also parse the engine's own `Result` log event —
`{reason, result}` — which directly states *why* each game ended: 1 = normal
prize win, 2 = a player started their turn with 0 deck cards (deck-out), 3 = no
Pokémon in Active Spot, 4 = a card effect. This is a more precise ground truth
than inferring cause from board-state snapshots alone and is worth reusing in
future runs).
- Record: **19-16 (54.3%)**.
- **Backlog question — did the Poffin fix work?** Yes. Losses with max
  concurrent Pokémon in play < 2 (the strict "never had a 2nd Pokémon" test):
  **3/16 (18.8%)**, down from run #6's 6/19 (31.6%). Moved to Resolved in the
  backlog above — considering this fix fully validated, no further action.
- **New finding — the broader "no active Pokémon" (engine reason=3) bucket is
  still 50% of losses (8/16), but the other 5/8 (beyond the 3 the Poffin fix
  targets) are different, already-understood causes, not a new bug**: traced 4
  of the 5 individually — 2 Fire-type one-shots (`Ethan's Typhlosion`, already
  documented weakness), 1 `Iono's Voltorb` (non-ex) self-destruct-style attack
  for -380 dmg that one-shots Crustle at any HP (immunity correctly doesn't
  apply since it's non-ex — nothing to fix), 1 `Marnie's Grimmsnarl ex` OHKOing
  our **Zarude** for -180 (expected — only the Crustle/Iwaparesu line has the
  ex-immunity ability, Zarude never had protection to begin with). The 5th (vs
  an Applin/Dipplin/Seaking toolbox) died to a high-damage non-ex attacker
  (`Seaking`) in the same "ordinary non-ex attrition" pattern CLAUDE.md already
  documents as the deck's known core weakness. Full detail in the new Unresolved
  backlog item above. **No code/deck change made this run** — didn't find
  evidence for a specific, safe, well-reasoned fix; per this loop's own rules I'd
  rather skip a change than ship a speculative one.
- **Side finding — deck-out dynamics, informational only**: 14/19 wins (73.7%)
  this round came from the *opponent* decking out, confirming the wall/stall
  win condition works as designed in practice. We ourselves decked out in only
  2/16 losses (12.5%), and traced both (`89299449`, `89303241`) — both were
  long grindy games where we were actually ahead or even on prizes (5-1, 6-6)
  when our own deck ran dry. Not a lever worth pulling either direction; logged
  for future reference only. Full detail in backlog above.
- Alakazam-line matchup: only 1 game featured it this round (down from 4 last
  run), 0 wins — too small a sample to update the existing backlog note
  meaningfully; leaving as-is (still "Do NOT bump Xerosic without new
  evidence").

**No fix applied, no submission this run**: no new well-evidenced, safe change
emerged from this round's analysis (see above) — the loop's rules explicitly
say not to submit a speculative change or burn a submission slot without real
evidence, so today's submission count stays at 2. `main.py`/`deck.csv` are
unchanged from `55157226` (already the current `submission/` state).

**Method note for future runs**: parsing the engine's own `Result` log entry
(`{reason, result, type: 'Result'}`, found by scanning every step's `logs` for
`type == 'Result'`) gives an authoritative end-of-game cause instead of
inferring it from board snapshots — much more reliable for bucketing losses
(prize win vs deck-out vs no-active-Pokémon vs card-effect). Worth using this
as the primary loss classifier going forward rather than re-deriving it from
`active`/`bench` state each time.

**Also note (environment, not a code issue)**: hit an MSYS/Git-Bash path
translation gotcha this run — `/tmp/...`-style paths only auto-translate to the
real Windows temp folder when passed as a Bash **command-line argument** to a
native Windows binary (e.g. `python.exe /tmp/script.py /tmp/some_dir`); a
`/tmp/...` path **hardcoded inside** a Python string (or written via the Write
tool) resolves to `C:\tmp\...` instead (root of the current drive), a different,
silently-existing location with old leftover files from earlier runs. Caused a
few minutes of confusion this run (looked like a stale/conflicting concurrent
process at first). Always pass scratch-file paths as argv, not as literals
embedded in a script, when using `/tmp` from this environment.

**git push failure (recurring — 2nd time, run #6 hit this too)**: `git push
origin main` fails every time in this run's session with:
```
fatal: Unable to persist credentials with the 'wincredman' credential store.
bash: line 1: /dev/tty: No such device or address
error: failed to execute prompt script (exit code 1)
fatal: could not read Username for 'https://github.com': No such file or directory
```
Confirmed at the *start* of this run that local `main` and `origin/main` were
in sync (both at `74dd230`), meaning run #6's push failure *did* eventually get
resolved — almost certainly by the user manually running `git push` from an
interactive session per run #6's request, since there's no other credential
source available (checked: no `gh` CLI installed, no `~/.git-credentials` file,
no relevant env vars, `git credential fill` fails the same way). This looks
like a structural limitation of this scheduled/non-interactive session (Windows
Credential Manager's `wincredman` store needs an interactive desktop/prompt
that isn't available here), not something fixable by changing repo-local git
config (and the safety rules for this loop explicitly forbid touching git
config anyway). **Left this run's commit (`d1c7362`, the backlog/log update
only — no code changes) sitting local-only, unpushed.** If this keeps
recurring every run, it's worth the user setting up a non-interactive-friendly
credential source for the scheduled task specifically (e.g. a `store`-based
credential helper with a PAT, scoped to just this task's context) rather than
relying on manual pushes each time — but that's a one-time human setup task,
not something this loop should attempt unsupervised.

**For the next run**:
1. First check whether a fresh submission's replays are available to analyze
   (none was made this run, so `55157226` is still the latest — check
   `kaggle competitions submissions` for anything newer before assuming stale).
2. The "no active Pokémon" bucket (backlog, new item above) is the biggest
   remaining loss driver (50%) but every traced case this run pointed to
   already-known structural weaknesses (Fire weakness, ex-immunity only
   covering Crustle/Iwaparesu, big non-ex hits) rather than a tunable bug. If a
   genuinely new angle is needed, consider whether more redundancy specifically
   getting a 2nd/3rd Crustle back into play after a KO (the only thing the
   ability protects) is worth exploring — not attempted yet, no evidence
   gathered on how often we have a 2nd Crustle/Iwaparesu available after the
   first one dies.
3. Alakazam-line matchup and the self-referential/discard-count damage-attack
   families remain open, still low-priority/low-sample — see backlog.

---

## 2026-08-01 (loop run #6, ~16:00-17:00 JST)

**Orientation**: Read the backlog first. Top item was checking ref `55151278`'s
(run #5's Xerosic 2→3 bump) score/replays — exactly what this run did.

**Current standing**:
- `55151278` came back at **558.0** (COMPLETE). Leaderboard (fresh CSV, 6078
  teams): bronze cutoff (top 10%, rank 607) = **836.5**, essentially flat vs run
  #5's 837.5. Our displayed rank (best-ever score, 563.8 from ref `55148965`) =
  **3980**. Submissions today (08-01) before this run: 1 (ref `55151278`,
  01:50 UTC) — safe to submit a 2nd.

**Replay analysis of `55151278`** (all 37 public episodes, full active/bench/
hand/prize/handCount trace across every step for both perspectives — reused the
prior runs' methodology, extended to also track opponent handCount-reset *events*
as a distinct-event series rather than a single flag, to properly answer backlog
item (b) about a "2nd reset").
- Record: **18-19 (48.6%)**, consistent with 558.0.
- **Backlog item — Alakazam-line win rate**: only 4 games featured the line this
  round (down from 7 last run), 1 win (25.0%) — flat vs run #5's 2/7 (28.6%),
  within noise for this sample size. Traced *why* the 2 losses lost even with 3
  Xerosic copies: one game (`89242979`, 84 steps) never got the opponent's hand
  below 6 the entire game — i.e. **we never drew any of the 3 Xerosic copies** —
  while the other (`89245086`, 67 steps) got exactly 1 real reset off (7→3 at step
  48) but the game ended before a 2nd reset was needed. By contrast, this round's
  1 Alakazam win (`89251840`, 119 steps) showed 2 clean, distinct resets (16→3 at
  step 71, then 7→3 again at step 105) — direct confirmation that the 3-copy bump
  *does* work correctly when drawn in time. Conclusion: the fix is mechanically
  validated (answers backlog question (b) — yes, a genuine 2nd reset does happen in
  long games now), but the Alakazam matchup overall isn't improving because in a
  60-card deck 3 copies of one card still isn't reliably drawn before a short-ish
  game ends. Did not bump Xerosic further this run — no evidence more copies would
  help beyond what 3 already demonstrates; recorded as still-unresolved but
  better-understood in the backlog above.
- **New/bigger finding this run — re-checked the "single Pokémon the whole game"
  pattern flagged in run #5's backlog**: recurred at **6/19 losses (31.6%)**,
  essentially the same rate as run #5's 4/14 (29%) — confirms this is a real,
  persistent pattern, not batch noise, and at ~30% of losses it's now a bigger
  overall loss driver than the narrow 4-game Alakazam matchup. Checked the opening
  hand (first populated hand snapshot, ~step 3) of all 6 losses for Basic Pokémon
  and Buddy-Buddy Poffin (1086) presence: only 1/6 had exactly 1 Basic and no
  Poffin (the "bad mulligan variance" story run #5 guessed at). The other 5/6 told
  a different, more specific story: **5/6 never had Poffin in their opening hand**,
  and one of those (ep `89256504`) was traced turn-by-turn through all 62 steps of
  the game and *never drew a single copy of Poffin the entire game* — despite
  drawing Dwebble, evolving to Crustle, and holding Toko (1225) in hand for ~20
  consecutive turns. Toko was mechanically useless there: it can only search "an
  evolution Pokémon" (i.e. refetch a 2nd Crustle, pointless with no 2nd Dwebble on
  the bench to evolve) or 1 energy — it cannot fetch a new Basic. A second traced
  game (`89256884`) did draw a Poffin and it left hand mid-game (via a Lillie's
  Determination-triggered search/shuffle sequence), but the bench still never
  filled — plausibly because the remaining Dwebble copies were already
  prized/unavailable by then; didn't chase this second sub-case further since the
  first (never-drew-Poffin-at-all) is the larger, cleaner signal.

**Root cause**: same core issue run #3 first identified (Dwebble access
bottleneck) but at the next level — Poffin is the fix, but 2 copies in 60 cards is
still not a high enough hit rate to reliably show up before a lone active dies in
a fast game. This is exactly the scenario flagged as the natural next lever in run
#5's backlog note ("if this pattern recurs at a similar rate, bump Poffin to
3-4 copies").

**Fix applied** (`PTCGstadium/agents/iwaparesu_yoshida_v2/deck.csv` + one-line
comment in `main.py`): bumped **Buddy-Buddy Poffin (1086) from 2→3 copies**,
funded by trimming **Toko (1225) from 2→1**. Toko was already flagged twice as
partially redundant (run #4's 3→2 trim, validated no-regression in run #5); this
run's traced loss (`89256504`) gave a concrete example of Toko sitting dead in
hand for ~20 turns specifically because it can't do what Poffin does (fetch a new
Basic), which made this a well-evidenced, not speculative, further trim. Pure
1-for-1 swap, no other deck changes, no code-logic changes (the search-item
plumbing was already fully generic from run #3's Poffin adoption — only the
`deck.csv` counts changed).

**Testing**:
- `sort -n deck.csv | uniq -c`: 60 lines, confirmed 1086 at 3 copies, 1225 at 1,
  ACE SPEC 1159 still at 1, no other counts changed.
- `python -c "import ast; ast.parse(...)"` on `main.py`: syntax OK.
- Smoke test: `arena.py --p0 agents/iwaparesu_yoshida_v2 --p1 agents/archive/baseline
  --games 40` → **50.0% win rate, errors: 0**. Per this loop's own rules, a
  crash-check only.
- Verified `submission/main.py` imports standalone (`main.agent` callable,
  `read_deck_csv()` returns 60 cards) after syncing `main.py`/`deck.csv` into
  `submission/` (`cg/` already in sync, confirmed via `diff -rq` ignoring
  `__pycache__`).
- Submitted: ref **`55157226`**, 2026-08-01 ~07:51 UTC, PENDING at time of writing.
  **Check its score/replays next run.**

**Method notes for future runs**:
- Watch out for CRLF line endings when writing episode-ID lists to a file with
  Python's default text mode on Windows and then comparing with `comm`/`sort` from
  Git Bash — every line differs silently (no error) because of the trailing `\r`.
  Strip with `tr -d '\r'` before comparing. Cost some time this run.
- Replay JSON logs the same step's `current` snapshot from *both* agents'
  perspectives when both happen to be queried that step, and adjacent step indices
  can show what look like oscillating values (e.g. handCount flipping between two
  numbers across consecutive step entries) — this is just two different
  before/after snapshots of the same underlying turn, not real oscillation. Don't
  treat every apparent up-down flip in a per-step series as a real game event;
  cross-check against the actual `logs`/`action` fields (or just look at the
  overall trend) before concluding something happened twice.

**For the next run**:
1. First check ref `55157226`'s score and replays. Key metric: did the "never had
   a 2nd bench Pokémon" loss share actually drop from this run's 6/19 (31.6%)? If
   yes, consider the Poffin fix validated (parallel to how the original Poffin
   adoption in run #3 was validated by run #4). If it didn't move, check whether
   Poffin is actually reaching hand earlier now (should be mathematically more
   likely with 3 copies) before concluding the fix failed.
2. Watch for any new "Toko in hand but nothing to refetch" or "ran out of energy
   search" pattern attributable to the Toko 2→1 trim — low risk (this is Toko's
   3rd trim across 3 runs with no regression found in the first two), but this is
   the first time it's down to a single copy.
3. The Alakazam-line matchup (backlog, now better-understood but still unresolved)
   and the self-referential damage-counter-attack family (backlog, still lowest
   priority) remain open — see backlog section for full detail on both.

---

## 2026-08-01 (loop run #5, ~10:15-11:00 JST)

**Orientation**: Read the backlog first. Top item was validating run #4's Xerosic's
Machinations fix against ref `55148965`'s real replays — exactly the task this run
did.

**Current standing**:
- `55148965` (run #4's Xerosic fix) came back at **616.1** at time of first check
  (best score since 592.4 on 2026-07-30), though it had already revised down to
  602.5 by the time this run finished (Kaggle keeps revising scores as more games
  play out — consistent with prior runs' observation, not a new phenomenon).
  Leaderboard (fresh CSV, 6059 teams): bronze cutoff (top 10%, rank 605) = **837.5**,
  essentially flat vs run #4's 837.4. We're rank **3313** (best-ever score 616.1),
  up from run #4's rank 3864 — real, if modest, progress. Submissions today
  (08-01) before this run: 0 — safe to submit.

**Replay analysis of `55148965`** (all 26 public episodes, full active/bench/hand/
prize/handCount trace across every step for both perspectives, same methodology as
prior runs — reused/extended the analysis script rather than rewriting from scratch).
- Record: **12-14 (46.2%)**, roughly consistent with 616.1/602.5 (mid-pack for this
  competition's very noisy scoring).
- **Backlog item (a) — Alakazam-line win rate**: 7 games featured the Abra/Kadabra/
  Alakazam line this round, **2 wins (28.6%)** — up from run #4's 1/7 (14%), so
  moving in the right direction but still our worst matchup by a wide margin.
- **Backlog item (b) — is Xerosic actually firing?** Yes: played in **19/26 games**
  overall, and in **5 of the 6** Alakazam-line games where it had a chance to matter
  (only exception was a very short 45-step loss, ep `89231817`, where we likely never
  drew it — see the new "single Pokémon" finding below, same episode). So the
  `_XEROSIC_HAND_THRESHOLD = 7` firing condition itself is **not** the bottleneck —
  it correctly identifies hoarding and fires. The real problem, found by tracing
  opponent handCount across full games: in ep `89233850` (a 91-step Alakazam loss),
  opponent hand dropped to exactly 3 once at step 14 (our one Xerosic use that game)
  then climbed *unchecked* 6→16→18 over the remaining ~80 steps with **no second
  reset** — we only had 2 copies and evidently only drew/played one of them. So
  Xerosic works as designed but we run out of ammo in long grindy games, which are
  exactly the games where hand-hoarding has time to become lethal. **Fix**: bumped
  Xerosic's Machinations from 2→3 copies (see below).
- **Backlog item (c) — did the run #4 Toko/Morty's-Conviction trim cost us
  anything?** No evidence of regression: only 2/14 losses (14%) this round never saw
  the Dwebble/Crustle line in play at all, the same order of magnitude as run #4's
  post-Poffin-fix 1/23 (4%). Moved to Resolved in the backlog.
- **New finding this run — "single Pokémon the whole game" sudden-death losses**:
  tallied max bench size reached *at any point in the entire game* (not just at the
  end) for all 14 losses. **4/14 (29%)** — eps `89229735` (28 steps), `89231817`
  (45 steps), `89232839` (23 steps), `89238059` (45 steps) — never had a 2nd Pokémon
  on the bench at any point, ever, and the game ended the instant the lone active
  died, with **zero prizes taken by either side** up to that point in 3 of the 4
  (confirmed via the `prize` array length, which — reconfirming a prior run's method
  note — only exposes remaining-count, not contents, for either side). Traced two
  turn-by-turn (`89229735`, `89232839`) using the engine's own visible-hand field
  (our own hand contents *are* exposed in our perspective's `current.players[our_idx]
  .hand`, unlike the opponent's, which is count-only) — both had genuinely bad
  opening hands: exactly 1 Basic Pokémon (Zarude in one, Dwebble in the other) and no
  Poffin/Toko drawn before that lone body died. This looks like real deck-consistency
  variance (only 8 Basics total — 4x Dwebble + 4x Zarude — in 60 cards) rather than a
  play-logic bug; **did not act on it this run** to avoid stacking two untested deck
  changes at once (see backlog — flagged as the natural next lever, likely another
  Poffin bump, if the Xerosic change doesn't move the needle enough next run).

**Fix applied** (`PTCGstadium/agents/iwaparesu_yoshida_v2/deck.csv` +
one-line comment in `main.py`): bumped **Xerosic's Machinations (1197) from 2→3
copies**, funded by cutting the last copy of **Morty's Conviction (1187, 1→0)** —
a pure 1-for-1 swap, no other deck changes. Morty's Conviction was already trimmed
once (2→1) in run #4 for the same reason (judged least load-bearing of the
Boss/Lillie/Petrel-Factory-adjacent supporter set) and cutting its last copy follows
the same reasoning, now backed by this run's confirmation (item c above) that the
run #4 trim didn't cost us anything. No code-logic changes were needed — `CID_MATSUBA`
stays defined in `main.py` (same "inert sentinel" pattern as `CID_POKE_PAD = 0`
elsewhere) since deck composition is fully data-driven from `deck.csv`; added a short
comment at its definition so a future run doesn't mistake it for still being live.
Deliberately did **not** touch `_XEROSIC_HAND_THRESHOLD` (confirmed not the
bottleneck this run, see item b) or the newly-found "single Pokémon" pattern (see
above — parking for next run to avoid bundling two speculative changes).

**Testing**:
- `sort -n deck.csv | uniq -c`: 60 lines, confirmed 1197 at 3 copies, 1187 at 0
  (absent from output entirely), ACE SPEC 1159 still at 1, no other counts changed.
- `python -c "import ast; ast.parse(...)"` on `main.py`: syntax OK.
- Smoke test: `arena.py --p0 agents/iwaparesu_yoshida_v2 --p1 agents/archive/baseline
  --games 40` → **62.5% win rate, errors: 0**. Per this loop's own rules this is a
  crash-check only (baseline doesn't run Alakazam), but note in passing: this is
  notably higher than recent smoke-test baselines (47.5-55.0% in runs #2-#4) —
  plausibly just game-to-game arena variance rather than a signal about this change,
  since baseline can't exercise Xerosic either way.
- Verified `submission/main.py` imports standalone (`import main; main.agent`
  callable, `main.read_deck_csv()` returns 60 cards) after syncing `main.py`/
  `deck.csv` into `submission/` (`cg/` already in sync, `diff -rq` showed no
  differences outside `__pycache__`).
- Submitted: ref **`55151278`**, 2026-08-01 ~01:50 UTC, PENDING at time of writing.
  **Check its score/replays next run — see the two updated Open Items above for
  exactly what to look for (Xerosic 2nd-reset behavior, and whether the "single
  Pokémon" pattern recurs at a similar ~29% rate).**

**Method notes for future runs**:
- Our own hand *contents* (not opponent's) are visible in replay JSON at
  `current.players[our_idx].hand` (list of `{id, ...}` dicts) — useful for
  diagnosing "what did we actually have available" in a specific loss, distinct from
  the opponent's `handCount`-only visibility. Didn't see this used explicitly in
  prior entries' method notes, worth keeping in mind.
- To check "did X ever happen at any point in the game" (e.g. "was there ever a 2nd
  bench Pokémon") reliably, scan **both** `step[our_idx]` and `step[opp_idx]`
  entries' `observation.current` per step, not just one perspective — some steps
  only carry a populated `current` snapshot under one agent's entry (the other's may
  be `None`, presumably logged only when that agent was actually queried for a
  decision that step).

**For the next run**:
1. First check ref `55151278`'s score and replays. Key checks: (a) Alakazam-line win
   rate — did it improve from this run's 2/7 (28.6%)? (b) does the opponent's hand
   actually get reset a 2nd time in long games now (trace handCount trajectory in a
   long Alakazam-line game like this run did for `89233850`), or are we still only
   drawing 1 of the 3 copies in practice? If still insufficient, next lever is
   probably 3→4 copies rather than touching the threshold (see backlog reasoning).
2. The new "single Pokémon the whole game" pattern (4/14 losses, 29%) is unacted-on
   and flagged in the backlog — if it recurs at a similar rate, or if the Xerosic
   bump doesn't move the Alakazam matchup enough, consider bumping Buddy-Buddy Poffin
   (currently 2 copies) next, per run #3's original forward-looking note.
3. The self-referential damage-counter-attack family and discard-pile-count attacks
   (both still in the backlog, untouched for 3 runs now) remain unaddressed and still
   have no confirmed real-game cost — still lowest priority.

---

## 2026-08-01 (loop run #4, ~00:15-00:52 JST)

**Orientation**: Read the backlog first. Top item was "Buddy-Buddy Poffin validation
pending" from run #3 (ref `55137619`).

**Current standing**:
- `55137619` (the Poffin fix) came back at **507.2** — lower than run #3's read of
  it (549.7, later updated to 571.9 in the submissions list — Kaggle appears to
  revise scores after more games are played against a submission). Also lower than
  the immediately-prior `55129961` (571.9) and `55123159` (530.8). Leaderboard
  (fresh CSV, 6052 teams): bronze cutoff (top 10%, rank 605) = **837.4**, essentially
  flat vs run #3's 841.1. We're rank 3864, displayed score 571.9 (best-ever, not
  latest). Submissions today (08-01) before this run: 0 — safe to submit.

**Replay analysis of `55137619`** (all 37 public episodes, same
active/bench/hand/prize full-game-trace methodology as prior runs — note: the
`prize` array elements are always `null` even for our own side, presumably face-down
by design; only `len(prize)` — remaining prize count — is usable, not the contents).
- Record: **14-23 (37.8%)**, consistent with 507.2.
- **Poffin fix validated hard**: only **1/23 losses (4%)** now show the Dwebble/
  Crustle line never reaching play at all, down from run #3's pre-fix 6/17 (35%).
  Moved to Resolved in the backlog above. This is a clean, unambiguous win even
  though the aggregate score this round was mediocre — the score drop has a
  different, better-evidenced cause below, not this fix backfiring.
- **New/biggest finding this run**: tallied opponent rosters across the 23 losses.
  The **Abra/Kadabra/Alakazam line (741/742/743) appeared in 6/23 losses and only
  1/7 total appearances were wins (14% win rate)** — by far the single worst
  matchup, worse even than run #3's already-flagged 25% post-fix reading (small
  samples both times, but the direction is bad, not improving).
  Traced two of these losses turn-by-turn (not just final snapshot):
  - ep `89147429` (loss vs "立て板に水"): our board was fully healthy (2x Zarude,
    120/120 HP each) but the opponent had **25 cards in hand** and a nearly-empty
    deck (1 card left) by turn 25 — a deliberate hand-hoarding strategy. Their
    Alakazam's "Powerful Hand" (attackId 1072, `n cards in hand × 2 counters ×
    10 HP`) hit our Crustle for **-480** (24 cards) at step 156, then hit our
    fresh Zarude for **-500** (25 cards) just 12 steps later at step 168 — an
    outright OHKO on *any* Pokémon we could put in the active slot, with no
    retreat/positioning counterplay possible since the next-in-line Pokémon dies
    to the exact same attack next turn.
  - Checked the opponent's hand-count trajectory across the whole game: normal
    range (turns 0-13) was 3-6 cards, then it jumped to 14 at turn 14 and kept
    climbing (18, 23, 24, 25) — a clear, sharp inflection point distinguishing
    "hoarding mode" from ordinary play, not a gradual drift.
  - ep `89147934` (loss vs Shiyuanhe123) showed the same Alakazam-line signature
    in the opponent roster (also present: id 66/Kadabra, 305, 741/742/743).

**Root cause**: this is *not* a threat-detection gap — run #2's
`_effect_damage_estimate()` fix (which taught `_usable_damage()` to read Powerful
Hand's real damage from hand-count) is doing its job; the problem is that once an
opponent's hand is large enough, Powerful Hand becomes an unconditional OHKO on
*whichever* Pokémon we have active, and retreating/switching just presents a new,
equally-doomed target next turn. There is no positional or HP-based counterplay to
a large-enough Powerful Hand — the only real counter is preventing the opponent's
hand from ever getting that large in the first place.

**Fix applied** (`PTCGstadium/agents/iwaparesu_yoshida_v2/main.py` +
`deck.csv`): added 2x **Xerosic's Machinations** (card id 1197, Supporter: "Your
opponent discards cards from their hand until they have 3 cards in their hand").
This directly caps the maximum possible Powerful Hand damage at 3×2×10=60 (trivial)
regardless of how long the opponent has been hoarding. Wired identically to the
existing Bell/Toko conditional-supporter pattern:
- `CID_XEROSIC = 1197`, added to `_SUPPORTER_IDS`.
- New `_should_play_xerosic(obs)`: returns `True` only when the opponent's
  `handCount >= _XEROSIC_HAND_THRESHOLD` (set to **7**, comfortably above the 3-6
  card range observed in ordinary play this round, but well before the
  14→18→23→24→25 hoarding trajectory becomes lethal — the goal is to interrupt the
  snowball early, not just react once it's already dangerous).
- `_supporter_sort_key()`: new branch returning priority 19 (between Crispin=17 and
  Toko=20) when `_should_play_xerosic()` is true, else 999 (skip this turn) — same
  "priority if condition met else 999" idiom used by Bell/Matsuba/Lillie, so it
  slots into the existing generic supporter-selection pipeline
  (`_best_play_index()` → `CardType.SUPPORTER` → `_supporter_sort_key`) with no
  other code paths to touch.
- **Deck slot funding**: to keep this a pure 60-card swap, trimmed 2 slots from
  cards judged least load-bearing given what run #3/#4 have now confirmed:
  - Toko (1225) 3→2: backlog already flagged this as "worth reconsidering once
    Poffin's real impact is known" — it's now known (Poffin fixed the Dwebble-access
    problem hard, see Resolved above), so Toko's redundant "search Crustle" half is
    less necessary. Kept 2 (not 1) because its "search 1 energy" half still has
    standalone value once Dwebble/Crustle is already in play.
  - Morty's Conviction (1187) 2→1: a secondary card-advantage Supporter, judged
    less central than the Boss/Lillie/Petrel-Factory engine pieces (which have
    explicit code-level protection/priority already) — a modest trim, not a
    structural change.

Deliberately did **not** touch the Boss's Orders / Lillie / Team Rocket's
Factory-Petrel draw engine, `_EX_IMMUNE_POKEMON`, or any retreat/switch logic —
this is purely a new supporter card plus a funding trim, following the project's
own caution against bundling unrelated changes.

**Testing**:
- `sort -n deck.csv | uniq -c`: 60 lines, max 4 of any id (1159 ACE SPEC still at
  1), confirmed 1197 at 2 copies, 1187 at 1, 1225 at 2.
- `python -c "import ast; ast.parse(...)"` on `main.py`: syntax OK.
- Smoke test: `arena.py --p0 agents/iwaparesu_yoshida_v2 --p1 agents/archive/baseline
  --games 40` → 55.0% win rate, **errors: 0**. Baseline doesn't run Alakazam, so
  (per this loop's own rules) this only confirms no crash, not whether Xerosic
  actually helps — the card imported/parsed fine (engine recognizes id 1197 as a
  legal card, no exceptions during 40 games).
- Verified `submission/main.py` imports standalone (`import main; main.agent`
  callable, `main.read_deck_csv()` returns 60 cards) after syncing `main.py`/
  `deck.csv` into `submission/` (`cg/` already in sync aside from `__pycache__`).
- Submitted: ref **`55148965`**, 2026-08-01 (~2026-07-31 23:52 UTC per Kaggle's
  submission-list timestamp), PENDING at time of writing. **Check its score/replays
  next run — see the new Open Items entry above for exactly what to look for.**

**Method note**: the `prize` field in the observation JSON is an array of `null`
entries for *both* sides even in your own perspective's final snapshot — only its
*length* (remaining prizes to take) is usable, not per-card contents. Don't try to
read prize contents expecting card IDs; there aren't any exposed there.

**For the next run**:
1. First check ref `55148965`'s score and, more importantly, pull its replays and
   check the Alakazam-line matchup specifically: did the win rate improve from this
   run's 1/7 (14%)? Check whether Xerosic's Machinations (attackId/cardId 1072/1197
   in the logs) actually got played in those games — if the opponent's hand never
   reached the >=7 threshold before a lethal Powerful Hand, consider lowering
   `_XEROSIC_HAND_THRESHOLD`.
2. Watch for any regression traceable to the Toko/Morty's Conviction trims (e.g. a
   new "couldn't find Crustle" or "ran out of draw options" pattern) — small risk,
   flagged in the backlog, not expected to be large since both were partial (not
   full) cuts.
3. The self-referential damage-counter-attack family and discard-pile-count attacks
   (both still in the backlog) remain unaddressed — still no confirmed real-game
   cost, still lower priority than the items above.

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
