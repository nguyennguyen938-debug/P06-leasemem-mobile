#!/usr/bin/env python3
"""Physical-phone results (plan C3) -> manuscript/generated/physical_macros.tex and tab_phys_*.tex.

Reads only top-level artifact/results/physical-*/*.jsonl (append-only raw data from the experiment role); schema and
file names: PHYS-PROTOCOL.md sections 6, 7 and 10. Every macro or table without data renders \\PhysTBD{<what>}, a red
TBD; scripts/check_final.py fails while the PDF shows one. Trials are classified with the emulator rules of
scripts/analyze.py (valid, classify, gap_effects, coverage, e9_row), so phone and emulator numbers are comparable.
Files whose name contains "pilot" (S2 pipeline check) are summarized on stdout and never enter macros or tables.
Optional per-record fields of the AWS runs: `device_instance` (counted by \\PhysInstances) and `run_arn` (counted on
stdout); records without them still load. B6 (host-*) has one macro, B7 (continuous-*) none; B11 and B12 are dropped.
Freezer trials (B1 bg_freezer, B2 freeze, B5) count only with the freezer on: `use_freezer`, else the saved settings.
Files named b13-* (B13, Galaxy S25, campaign.py --tag) never enter the Pixel 8 macros; they feed the \\PhysSamsung*
macros and Table tab_phys_samsung with the same B1, B4 and freezer rules. Captions name no experiment codes.
Run `python physical/analyze_phys.py --self-check`.
"""
import json, re, statistics as st, sys, tempfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'artifact/scripts'))
sys.path[:0] = [str(ROOT / 'artifact/revision'), str(ROOT / 'artifact/physical')]
import analyze as ea                      # noqa: E402  emulator analysis rules
from render import GAPNAME, SRCNAME       # noqa: E402
from oracle import boot                   # noqa: E402  the emulator host table's paired bootstrap (mean, 95%)
from b7_continuous import classify as b7_classify   # noqa: E402  B7 oracle

NAMES = {'bg_unfrozen': 'Background, unfrozen', 'bg_freezer': 'Background, frozen', 'fg': 'Foreground service',
         'assistant': 'Bound assistant'}
SOURCES = {'contacts': 'Contacts', 'media': 'MediaStore', 'calllog': 'Call log'}
GAPS = ['none', 'freeze', 'dozeidle', 'bucket', 'unregister', 'kill', 'forcestop', 'perm', 'reboot']   # B2, campaign.py
LOST, INEPOCH = ['unregister', 'kill', 'forcestop', 'perm', 'reboot'], ['none', 'freeze', 'dozeidle', 'bucket']
FILES = {'deploy': 'deploy*.jsonl', 'gaps': 'gaps-*.jsonl', 'coverage': 'coverage-*.jsonl', 'stock': 'stock-*.jsonl',
         'boundary': 'boundary*.jsonl', 'pitfalls': 'pitfalls-*.jsonl', 'frozen': 'frozen-*.jsonl',
         'b0': 'b0-probe-*.jsonl', 'host': 'host-*.jsonl', 'diag': 'diag-*.jsonl', 'reset': 'contacts-reset-*.jsonl',
         'continuous': 'continuous-*.jsonl', 'all': '*.jsonl'}
# RUNLOG 03:24 on 19/11 (run c3579ab2): campaign.py's restore turned the freezer off after the first step, so these files
# record use_freezer true for steps that ran with it off. The raw files stay as written; the analysis applies this.
FREEZER_FIX = {'c3579ab2': {'gaps-dozeidle-1834.jsonl', 'gaps-unregister-1834.jsonl', 'gaps-forcestop-1834.jsonl',
                            'gaps-perm-1834.jsonl', 'gaps-freeze-1834.jsonl'}}
# Sources never touched on this phone print NR instead of TBD: those the latest B0 record lists in excluded_sources.
# SMS and the call log each have an \if switch for the prose; B9 has its own (\ifPhysBoundary), whatever the call log.
NR = 'not run on phone'
# B11 (24-hour state log) and B12 (battery) are dropped: rented Device Farm phones are always charging and a run lasts
# at most 150 min. Their macros stay defined and print NR; their tables carry one row that says why.
DROPPED = ['PhysStateHours', 'PhysStateAlivePct', 'PhysStateFrozenPct', 'PhysStateDozePct', 'PhysStateKillsPerHour',
           'PhysBatteryFgsMahPerHour', 'PhysBatteryBgMahPerHour', 'PhysBatteryFgsBlocks', 'PhysBatteryBgBlocks']
WHY = 'dropped: rented Device Farm phones are always charging and a run lasts at most 150\\,min'
B13 = 'b13-'        # Galaxy S25 files; S25 keys of the data dict: 's25_' + one of S25_FILES
S25_FILES = {k: FILES[k] for k in ('deploy', 'stock', 'diag', 'b0')}
# Stopped partial run 06804731 (RUNLOG 11:32 and 13:29 on 19/11): 6 rounds whose seeds repeat the full run's; its
# records still show the unit's freezer state, but no trial counts.
PARTIAL = {'b13-galaxys25-stock-R3CY1019X6Y-0426.jsonl'}
NO_DELAY = 1 << 15  # ContentResolver.NOTIFY_NO_DELAY (hidden): ContentService then skips BACKGROUND_OBSERVER_DELAY
WRITES = {'none': 'no', 'one': 'one', 'continuous': 'continuous'}
MODE = {'bg_unfrozen': 'background', 'bg_freezer': 'background, frozen', 'fg': 'FGS', 'assistant': 'bound assistant'}
SHORT = {'bg_unfrozen': 'bg', 'bg_freezer': 'frozen', 'fg': 'FGS', 'assistant': 'assistant'}
GSHORT = {'none': 'no gap', 'freeze': 'freezer', 'dozeidle': 'Doze', 'bucket': 'bucket', 'unregister': 'unregister',
          'kill': 'kill', 'forcestop': 'force-stop', 'perm': 'revoke', 'reboot': 'reboot'}


def not_run(b0):
    """Sources not run: excluded_sources of the latest B0 record (files sort by date and time); none before B0."""
    recs = [r for r in b0 if 'excluded_sources' in r]
    return set(recs[-1]['excluded_sources'] if recs else ())


def load(res, pattern):
    """All records of one experiment, with the file name; nothing is rewritten. b13-* files load only for a b13-*
    pattern, so no Galaxy S25 record reaches a Pixel 8 macro."""
    return [dict(json.loads(l), _file=p.name) for p in sorted(res.glob('physical-*/' + pattern)) if p.name.startswith(B13) == pattern.startswith(B13)
            for l in p.read_text(encoding='utf-8').splitlines() if l.strip()]


def pilot(r):
    return 'pilot' in r['_file']


def dur(ms):
    return f'{ms / 1000:.1f}\\,s' if ms >= 1000 else f'{ms:.0f}\\,ms'


def sec(x):
    return f'{x:.1f}' if x >= 1 else f'{x:.3f}'


def kn(k, n):
    return f'{k}/{n}'


def wil(k, n):
    _, lo, hi = ea.wilson(k, n)
    return f'{k}/{n} [{100 * lo:.0f}, {100 * hi:.0f}]\\%' if n else 'n/a'


def pct(k, n):
    return f'{100 * k / n:.0f}' if n else 'n/a'


# ------------------------------------------------------------------ freezer state (some Device Farm units ship it off)
FZ_WHY = {False: 'freezer off', None: 'freezer state unknown'}
EXPERIMENTS = ('deploy', 'gaps', 'coverage', 'stock', 'boundary', 'pitfalls', 'frozen', 'host', 'reset', 'continuous')   # reported trials
FREEZE_GAPS = {'freeze', 'longfreeze'}      # B2 gaps that rely on the freezer; B5 and B1 bg_freezer always do


def setting(r, key):
    """'true'/'false' from the record's field `key`, else from use_freezer= in its saved `dumpsys activity settings`
    (`config`, B1 records written before the field existed); None if neither says."""
    v = r.get(key)
    if v in (None, '', '?'):
        m = re.search(r'use_freezer=(\w+)', str(r.get('config') or ''))
        v = m and m.group(1)
    return None if v in (None, '', '?') else str(v).lower()


def freezer_on(r):
    """Freezer state during the trial: True, False or None (unknown). use_freezer is the value after campaign.py
    turned the freezer on where a unit had it off."""
    v = setting(r, 'use_freezer')
    return None if v is None else v == 'true'


def freezer_units(M):
    """device_instance -> freezer on (True) or off (False) before any run changed it, over non-pilot records. Off:
    use_freezer_before (or the saved settings) false on any record. On: that value true, or the client was seen frozen
    (B0 freezer probe, freezer diagnosis). Units with neither stay out."""
    units = {}
    for k, v in M.items():
        for r in v if k != 'all' else ():
            s = setting(r, 'use_freezer_before')
            if s is None and (r.get('froze') is True or r.get('probe') == 'freezer_debounce_2s' and r.get('ok') and (r.get('detail') or {}).get('frozen') == '1'):
                s = 'true'
            u = r.get('device_instance')
            if s is not None and u is not None:
                units[u] = units.get(u, True) and s == 'true'   # any off record wins
    return units


def runlog_freezer(path):
    """RUNLOG "freezer on <instance>: use_freezer X -> Y" lines as records with the run's ARN: each line sits in the
    indented block under its run's "AWS fetch <run arn>:" line (artifact/aws/devicefarm.py)."""
    out, arn = [], None
    for line in (path.read_text(encoding='utf-8').splitlines() if path.exists() else ()):
        top = re.match(r'- \S+ AWS fetch (arn:\S+?:run:\S+?):', line)
        if top or not line.startswith(' '):
            arn = top and top.group(1)
        m = re.search(r'freezer on (\S+): use_freezer (\w+) -> (\w+)', line)
        if m and line.startswith(' '):
            out.append({'run_arn': arn, 'device_instance': m.group(1), 'use_freezer_before': m.group(2), 'use_freezer': m.group(3),
                        '_file': path.name})
    return out


def with_runlog(rows, log):
    """The trial's freezer state from its run's RUNLOG line when neither use_freezer nor the saved settings say. (The
    unit's state before the run needs no join: the RUNLOG records themselves count in freezer_units, and an off
    record wins over the settings saved after the freezer was turned on.)"""
    by = {x['run_arn']: x['use_freezer'] for x in log if x['run_arn']}
    return [dict(r, use_freezer=by[r['run_arn']]) if setting(r, 'use_freezer') is None and r.get('run_arn') in by else r for r in rows]


def corrected(r):
    """A record with the FREEZER_FIX correction applied (freezer off during the step)."""
    return dict(r, use_freezer='false') if any(run in str(r.get('run_arn')) and r.get('_file') in f for run, f in FREEZER_FIX.items()) else r


def needs_freezer(rows, excl):
    """Rows whose trial depends on the freezer: keep those that ran with it on, count the others by reason."""
    keep = []
    for r in rows:
        fz = freezer_on(r)
        if fz:
            keep.append(r)
        else:
            excl[FZ_WHY[fz]] += 1
    return keep


def why(excl, what):
    """Caption sentence for excluded trials, or ''."""
    return ' Excluded %s: %s.' % (what, ', '.join('%d (%s)' % (c, w) for w, c in sorted(excl.items()))) if excl else ''


# ------------------------------------------------------------------ per experiment: dict of results, or {} without data
def deploy(rows):
    """B1: callback delay per (source, deployment); a callback counts only for the trial's own `source`
    (records without it are emulator-schema Contacts trials). nodelay: trials whose first such callback carries
    NOTIFY_NO_DELAY in its onChange flags."""
    out = {}
    for src in SOURCES:
        for mode in NAMES:
            rs = [r for r in rows if r.get('source', 'contacts') == src and r.get('mode') == mode]
            if not rs:
                continue
            target, excl = '1' if mode == 'bg_freezer' else '0', Counter()
            valid, delays, before, nodelay = [], [], 0, 0
            for r in needs_freezer(rs, excl) if mode == 'bg_freezer' else rs:
                if 'error' in r or r.get('invalid') or r['before'].get('frozen') != target or any(x.get('frozen') != target for x in r['states']):
                    continue
                valid.append(r); t = r['mutation']['t_pre']
                ev = [e for e in r['memory_before_thaw'].get('events', []) if e['src'] == src and e['t'] >= t]
                before += bool(ev)
                if ev:
                    first = min(ev, key=lambda e: e['t'])
                    delays.append(first['t'] - t); nodelay += bool(first.get('flags', 0) & NO_DELAY)
            out[src, mode] = {'attempted': len(rs), 'valid': len(valid), 'before_thaw': before, 'delays_ms': delays, 'excluded': excl,
                              'nodelay': nodelay, 'rows': valid}
    return out


def nodelay(B, src):
    """(first callbacks with NOTIFY_NO_DELAY, first callbacks) over every deployment of one source."""
    z = [v for (s, _), v in B.items() if s == src]
    return sum(v['nodelay'] for v in z), sum(len(v['delays_ms']) for v in z)


def proc_states(rows):
    """Process states and oom_adj values of trials, before the mutation and in every later sample."""
    ps, adj = set(), set()
    for r in rows:
        for s in [r['before'], *r['states']]:
            m = re.search(r'curProcState=(\d+)', str(s.get('activity') or ''))
            ps.add(m and m.group(1)); adj.add(s.get('adj'))
    return ps - {None}, adj - {None}


def froze(rows):
    """(frozen, attempts, window s, debounce s) over freezer attempts with the client cached and the freezer not known to
    be off: the B0 freezer_debounce_2s probe and freezer-diagnosis variants b to d. Variant a keeps the client's FGS, so
    the client is never cached there (RUNLOG 00:47 on 19/11; experiment report G9). Window: the shortest time any attempt
    was watched (its last sample: probe after_s, diagnosis samples[].t_s), so "not frozen within it" holds for every
    attempt; None without times. Debounce: the freezer debounce set for the attempts, if they all agree."""
    a = [r for r in rows if freezer_on(r) is not False and (r.get('probe') == 'freezer_debounce_2s' or r.get('exp') == 'freeze_diag' and r.get('variant') != 'a')]
    w = [(r.get('detail') or {}).get('after_s') if 'probe' in r else max((s.get('t_s') for s in r.get('samples') or []), default=None) for r in a]
    db = {float((r.get('detail') or {}).get('debounce_get') or r.get('debounce_ms') or 0) / 1000 for r in a}
    return (sum(r.get('froze') is True or (r.get('detail') or {}).get('frozen') == '1' for r in a), len(a),
            min(w) if a and None not in w else None, db.pop() if len(db) == 1 and 0 not in db else None)


def gaps(rows):
    """B2: gap taxonomy and missed changed uses (event-only, restart-aware, StampCheck), emulator validity rules."""
    X = defaultdict(Counter)
    rows = [hist(t) for t in current(rows, X)]
    att, V = Counter(r['gap'] for r in rows), defaultdict(list)
    for t in rows:
        if t['gap'] in FREEZE_GAPS and not needs_freezer([t], X[t['gap']]):
            continue
        if ea.valid(t)[0]:
            V[t['gap']].append(t)
    out = {}
    for g in [g for g in GAPS if att[g]] + sorted(set(att) - set(GAPS)):
        T = V[g]; z = {'att': att[g], 'n': len(T), 'miss': {}, 'excluded': X[g]}
        if T:
            z['survived'], z['nsrc'], z['ev_e'], z['ev_l'], _, z['exit'], _, z['fcl'] = ea.gap_effects(T)
            z['exit_desc'] = Counter(new_exit(t)['desc'] for t in T if new_exit(t))   # same rule as gap_effects
        S = [t for t in T if stamp_ok(t)]
        for phase in ('early', 'late'):
            for p, TT in (('ev', T), ('evr', T), ('lm', S)):
                ch = [x for t in TT for x in ea.classify(t, phase).values() if x['changed']]
                z['miss'][phase, p] = (sum(not x['refresh'][p] for x in ch), len(ch)) if TT else None   # None: no StampCheck verdicts
        z['cost'] = [ea.decision_cost(t, 'late', ea.classify(t, 'late')) for t in S if 'lm_cost' in t['late']]
        out[g] = z
    return out


def new_exit(t):
    """The ApplicationExitInfo record written after observation (scripts/analyze.py gap_effects), or None."""
    ex = (t['late'].get('last_start') or {}).get('exit') or {}
    return ex if ex.get('ts', 0) > t['t_obs'] else None


def has_hist(t):
    return any('lm_hist' in f for ph in ('early', 'late') for f in t.get(ph, {}).get('facts', {}).values())


def current(rows, X):
    """B2: one consistent set per gap. A run whose records carry StampCheck verdicts (lm_hist, client C6) supersedes,
    gap by gap, the records of runs without them; the superseded records are counted in X."""
    c6 = {r.get('run_arn') for r in rows if has_hist(r)}
    redone = {r['gap'] for r in rows if r.get('run_arn') in c6}
    keep = []
    for r in rows:
        if r['gap'] in redone and r.get('run_arn') not in c6:
            X[r['gap']]['superseded by rerun with StampCheck verdicts'] += 1
        else:
            keep.append(r)
    return keep


def hist(t):
    """The trial as the emulator v3 analysis reads it: from client C6 on, StampCheck is lm_hist / lmts_hist with
    lm_hist_cost (source keyed, `ns`), the same lmValidateHistorical(all, true) as emulator `lm`; `lm` is then strict
    EvCheck. Records without lm_hist are returned unchanged."""
    if not has_hist(t):
        return t
    view = lambda D: dict(D, lm_cost=D.get('lm_hist_cost', {}), facts={k: dict(f, lm=f.get('lm_hist'), lmts=f.get('lmts_hist', f.get('lm_hist')))
                                                                       for k, f in D['facts'].items()})
    return dict(t, **{ph: view(t[ph]) for ph in ('early', 'late') if ph in t})


def stamp_ok(t):
    """The trial's `lm` verdicts are StampCheck's: lm_cost keyed by source with `ns`, as in the emulator runs. The revised
    client reports strict EvCheck under `lm` instead (lm_cost keyed by fact, each with a verdict); never StampCheck."""
    return not any(isinstance(v, dict) and 'verdict' in v for v in t['late'].get('lm_cost', {}).values())


def coverage(rows):
    rows = [r for r in rows if 'error' not in r]
    return {'n': len(rows), 'cells': ea.coverage(rows, 'phys')[0]} if rows else {}


def race(rows):
    """B4: optimistic anchors that certify a value changed by the racing writer (oracle.py rule)."""
    by = defaultdict(lambda: {'n': 0, 'stale': 0, 'unknown': 0, 'errors': 0})
    for r in rows:
        z = by[r.get('case')]
        if 'error' in r:
            z['errors'] += 1; continue
        z['n'] += 1
        z['stale'] += any(v != r['after']['values'][f] and r['historical']['verdicts'][f] == 'FRESH' for f, v in r['before']['values'].items())
        z['unknown'] += all(x['verdict'] == 'UNKNOWN' for x in r['repaired'].values())
    return dict(by)


def boundary(rows):
    """B9, scripts/analyze.py e3 rules, independent of excluded_sources. Stale, in every store: the value the client used
    differs from Dana's number read right after the effect (the client's flag, as in the emulator E3 v2 table). Store
    `contacts` (AWS: a Data row of a separate raw contact) also gives a second reading: the number in effect_row against
    Dana's number at effect_row.wall_ms, known without a change, when the change ended before wall_ms, or when it began
    after wall_ms (dana_number_before; without it, only after the truth read); a change spanning wall_ms is undetermined.
    Excluded: a change that never ran, the EvCheck validator, no effect row read back, an effect row whose number is not
    the value used, or a no-change trial whose Dana VERSION is missing or moved."""
    rows = [r for r in rows if r.get('res')]
    cls, cte, bins, excl, stores, wall = Counter(), [], {'near': [0, 0], 'late': [0, 0]}, Counter(), set(), Counter()
    for r in rows:
        res, store, mut = r['res'], r.get('effect_store', 'calllog'), r.get('mut') if r['change'] else None
        stale = bool(res.get('stale'))
        if r['change'] and 'mut_start' not in (mut or {}):
            excl['change not made'] += 1; continue
        if r.get('validator', res.get('validator', 'hist')) != 'hist':      # missing: emulator schema, StampCheck
            excl['EvCheck validator'] += 1; continue
        if store == 'contacts':
            row = r.get('effect_row') or {}
            if 'number' not in row:
                excl['no effect row'] += 1; continue
            if row['number'] != str(res.get('used', '')).split(',')[0]:
                excl['effect row is not the value used'] += 1; continue
            if not r['change'] and not (r.get('dana_version_unchanged') is True and r.get('dana_version_before')):
                excl["VERSION moved in a control"] += 1; continue
            w, old = row['wall_ms'], r.get('dana_number_before')
            truth = (res['truth_after_effect'] if not mut or mut['mut_end'] < w else
                     old if old and mut['mut_start'] > w else
                     res['truth_after_effect'] if mut['mut_start'] > res['effect_end'] + res.get('truth_read_ns', 0) / 1e6 else None)
            wall['undetermined' if truth is None else 'stale' if row['number'] != truth.split(',')[0] else 'fresh'] += 1
        stores.add(store)
        if r['mode'] == 'bnd':
            cte.append(res['effect_end'] - res['check2_start'])
        if not mut:
            where = 'none'
        else:
            ms, me = mut['mut_start'], mut['mut_end']
            if r['mode'] == 'bnd':
                where = 'before_check' if me < res['check2_start'] else 'after_effect' if ms > res['effect_end'] else 'overlaps'
                rel = ms - res['check2_start']
                b = 'near' if -10 <= rel < 10 else 'late' if 10 <= rel < 60 else None
                if b:
                    bins[b][0] += stale; bins[b][1] += 1
            else:
                where = 'before_action' if me < res['effect_start'] else 'after_effect' if ms > res['effect_end'] else 'overlaps'
        cls[r['mode'], where, stale] += 1
    k = lambda m, w: (cls[m, w, True], cls[m, w, True] + cls[m, w, False])
    n = len(rows) - sum(excl.values())
    return {'n': n, 'cte': cte, 'k': k, 'bins': bins, 'excluded': excl, 'wall': wall, 'stores': stores} if n else {}


def pitfalls(rows):
    reuse = [r for r in rows if r.get('exp') == 'sms_reuse' and r['res'].get('ok')]
    mt = [r for r in rows if r.get('exp') == 'mtime' and all(x.get('ok') for x in r['res'])]
    # clock set-back (driver/e6_pitfalls.py): valid only if the clock really went back (about 1 h; 50 min suffices);
    # affected = the client's Contacts stamp (lm) kept FRESH although the cached number was stale (scripts/analyze.py e6)
    ck = [r for r in rows if r.get('exp') == 'clock' and 'error' not in r and r.get('clock_moved_back_ms', 0) >= 3000000 and ver(r)]
    tr = [r for r in ck if r.get('variant') == 'transient' and r.get('lm_ts_hist')]   # timestamp StampCheck, as emulator ClockTs
    ps = [r for r in ck if r.get('variant') == 'persistent']
    same = lambda did: did.split('->')[0] == did.split('->')[1]
    if not (reuse or mt or ck):
        return {}
    return {'sms': (sum(same(r['res']['did']) for r in reuse), len(reuse)), 'mtime': (sum(same(r['res'][1]['did']) for r in mt), len(mt)),
            'clock': (sum(ver(r) == 'FRESH' and bool(r['stale_if_used']) for r in ck), len(ck)),
            'clock_ts': (sum(r.get('lm_ts_hist') == 'FRESH' and bool(r['stale_if_used']) for r in tr), len(tr)),
            'clock_guard': (sum(bool(r.get('clock_jump')) for r in ps), len(ps))}


def ver(r):
    """StampCheck's VERSION verdict of a clock trial: lm_hist (client C6 on), else `lm` of the emulator schema; None for
    a strict-only record (lm is EvCheck there, reason strict_*)."""
    return r['lm_hist'] if r.get('lm_hist') else None if 'strict' in str(r.get('reason')) else r.get('lm')


def frozen(rows):
    """B5: long frozen holds, one e9_row per hold; holds on a unit without the freezer are excluded first."""
    excl = Counter()
    out = [ea.e9_row(r, 'phone') for r in needs_freezer(rows, excl)]
    V = [o for o in out if o['valid']]
    if not V:
        return {'excluded': excl} if excl else {}
    S = [o for o in V if o['stayed_frozen']]
    return {'run': len(rows), 'excluded': excl, 'valid': len(V), 'stayed': len(S), 'died': sum(o['died'] for o in V), 'changes': sum(o['n_mut'] for o in V),
            'hold_min': min(o['frozen_with_pending_s'] for o in V) / 60, 'src': sum(o['sources_mutated'] for o in S),
            'lost': sum(o['sources_no_callback'] for o in S), 'unseen': sum(o['sources_last_change_unseen'] for o in S),
            'callbacks': sum(o['callbacks_vlate'] for o in V), 'evr': [sum(o['evr_miss_' + p] for o in V) for p in ('early', 'late', 'vlate')]}


def reset(rows):
    """Contacts reset (revision/supplement.py, case contacts_reset): pm clear of the Contacts provider, fixtures written
    again. same: the client's Contacts stamp (watermark) after equals the one before, so the stamp cannot see the reset;
    unknown: strict EvCheck returned UNKNOWN."""
    ok = [r for r in rows if 'error' not in r and str(r.get('reset_result', '')).strip() == 'Success']
    return {'n': len(ok), 'same': sum(r['before']['watermark'] == r['after']['watermark'] for r in ok),
            'unknown': sum(r['verdict'].get('verdict') == 'UNKNOWN' for r in ok)} if ok else {}


def matched_host(rows):
    """B6 matched host, per write case: median host ms per arm, refresh minus StampCheck paired (mean, revision/oracle.py
    boot), facts read, and quiet trials whose StampCheck values differ from the post-trial truth."""
    out = {}
    for case in ('none', 'one', 'continuous'):
        T = [r for r in rows if r.get('case') == case and 'error' not in r and not r.get('writer_errors')
             and all('_host_ns' in r['arms'].get(a, {}) for a in ('refresh', 'stamp'))]
        if T:
            ms = lambda a: st.median(r['arms'][a]['_host_ns'] / 1e6 for r in T if a in r['arms'])
            gain = [(r['arms']['refresh']['_host_ns'] - r['arms']['stamp']['_host_ns']) / 1e6 for r in T]
            out[case] = {'n': len(T), 'refresh': ms('refresh'), 'stamp': ms('stamp'), 'relay': ms('relay') if all('relay' in r['arms'] for r in T) else None,
                         'gain': (st.mean(gain), *boot(gain)), 'reads': (st.mean(r['arms']['refresh']['fact_reads'] for r in T),
                                                                         st.mean(r['arms']['stamp']['fact_reads'] for r in T)),
                         'mismatch': sum(r['arms']['stamp'].get('values', r['truth_after']['values']) != r['truth_after']['values'] for r in T),
                         'dev_refresh': st.median((r['arms']['refresh']['end_ns'] - r['arms']['refresh']['start_ns']) / 1e6 for r in T)
                                        if all('end_ns' in r['arms']['refresh'] for r in T) else None}   # on-device time of the refresh batch
    return out


def host_order(rows):
    """(units, write cases alternate trial by trial): whether order or unit could separate the write cases of B6."""
    T = sorted((r for r in rows if 'error' not in r and 'start' in r), key=lambda r: r['start'])
    return len({r.get('device_instance') for r in T}), bool(T) and all(a['case'] != b['case'] for a, b in zip(T, T[1:]))


def continuous(rows):
    """B7: per arm, oracle classes of physical/b7_continuous.py (fresh, stale at certification, stale at action only,
    ambiguous when an instant falls inside a commit window)."""
    out = defaultdict(Counter)
    for r in rows:
        if 'error' not in r:
            for arm, c in b7_classify(r).items():
                out[arm][c['class']] += 1
    return dict(out)


def builds(rows):
    """One build: its fingerprint; several (units on different builds): their build IDs."""
    f = sorted({r['fingerprint'] for r in rows if r.get('fingerprint')})
    return None if not f else '\\path{%s}' % f[0] if len(f) == 1 else ', '.join('\\path{%s}' % x.split('/')[3] for x in f)


def device(rows, key):
    vals = sorted({str(r[key]) for r in rows if r.get(key) is not None})
    return ', '.join(vals) if vals else None


def by_unit(rows):
    g = defaultdict(list)
    for r in rows:
        g[r.get('device_instance') or '?'].append(r)
    return sorted(g.items())


def build_id(f):
    """Build ID of a fingerprint brand/product/device:release/ID/incremental:type/tags."""
    m = re.search(r':[\d.]+/([^/:]+)', f)
    return m.group(1) if m else f


def build_ids(rows):
    return ', '.join(sorted({build_id(r['fingerprint']) for r in rows if r.get('fingerprint')})) or '?'


DEFERRED = ['none', 'dozeidle', 'bucket']      # gaps whose callbacks are only deferred (no freezer, observer kept)


def per_unit(M):
    """Pixel 8 trials per unit (device_instance) and build for callbacks, gaps, race, host helper and boundary, each with
    its own rules (gaps after the rerun replacement of the whole campaign). Returns table rows (test, unit, build,
    trials, result) and per-unit values: deferred first-callback median, whether event-only missed every lost-coverage
    change, check-to-effect median."""
    rows, U = [], {'fcl': {}, 'lost': {}, 'cte': {}, 'gap_builds': set()}
    for u, rs in by_unit(M['deploy']):
        B = deploy(rs)
        res = '; '.join('%s: %s' % (SOURCES[s], ', '.join('%s %s' % (SHORT[m], dur(st.median(z['delays_ms'])) if z['delays_ms'] else 'held' if z['valid'] else 'n/a')
                                                         for (s2, m), z in B.items() if s2 == s)) for s in dict.fromkeys(s for s, _ in B))
        rows.append(('Callbacks', u, build_ids(rs), kn(sum(z['valid'] for z in B.values()), sum(z['attempted'] for z in B.values())), res))
    for u, rs in by_unit(current(M['gaps'], defaultdict(Counter))):
        G = gaps(rs); U['gap_builds'] |= {build_id(r['fingerprint']) for r in rs if r.get('fingerprint')}
        d = [x for g in DEFERRED if g in G for x in G[g].get('fcl', [])]
        parts = []
        if d:
            U['fcl'][u] = st.median(d); parts.append('first cb. %.2f\\,s (deferred)' % U['fcl'][u])
        if G.get('freeze', {}).get('fcl'):
            parts.append('%s\\,s (freezer)' % sec(st.median(G['freeze']['fcl'])))
        k = [G[g]['miss']['late', 'ev'] for g in LOST if g in G and G[g]['miss']['late', 'ev']]
        if k:
            a, b = sum(x for x, _ in k), sum(y for _, y in k); U['lost'][u] = a == b
            parts.append('Ev missed %s (lost)' % kn(a, b))
        rows.append(('Gaps', u, build_ids(rs), kn(sum(z['n'] for z in G.values()), sum(z['att'] for z in G.values())),
                     '%s: %s' % (', '.join(GSHORT.get(g, g) for g in G), '; '.join(parts) or 'n/a')))
    for u, rs in by_unit(M['stock']):
        Z = race(rs); n = sum(z['n'] for z in Z.values())
        rows.append(('Anchoring race', u, build_ids(rs), str(n), 'stale \\Fresh %s' % kn(sum(z['stale'] for z in Z.values()), n)))
    for u, rs in by_unit(M['host']):
        H = matched_host(rs)
        rows.append(('Host helper', u, build_ids(rs), str(sum(z['n'] for z in H.values())),
                     'refresh $-$ \\stamp %s\\,ms (%s writes)' % (', '.join('%.1f' % z['gain'][0] for z in H.values()), ', '.join(WRITES.get(c, c) for c in H))))
    for u, rs in by_unit(M['boundary']):
        BD = boundary(rs)
        if BD:
            U['cte'][u] = st.median(BD['cte']) if BD['cte'] else None
            rows.append(('Action boundary', u, build_ids(rs), str(BD['n']), 'check-to-effect %s\\,ms; overlap stale %s%s' % (
                '%.1f' % U['cte'][u] if BD['cte'] else 'n/a', kn(*BD['k']('bnd', 'overlaps')),
                ' (band schedule only)' if all('band' in r['_file'] for r in rs) else '')))
    return rows, U


def tex(s):
    """Plain device strings into LaTeX text."""
    return None if s is None else ''.join('\\' + c if c in '_&%#$' else c for c in s)


def android(b0):
    """'Android <release>, SDK <level>' from the B0 identity probe."""
    ids = [r['detail'] for r in b0 if r.get('probe') == 'identity' and r.get('ok') and isinstance(r.get('detail'), dict)]
    v = sorted({'Android %s, SDK %s' % (x.get('ro.build.version.release'), x.get('ro.build.version.sdk')) for x in ids})
    return '; '.join(v) if v else None


def analyze(D):
    """D: experiment key -> records (with _file); keys 's25_<experiment>' hold the Galaxy S25 (b13-*) records. Returns
    (macros, results of main runs, results of pilot runs)."""
    S = {k[4:]: [r for r in v if not pilot(r)] for k, v in D.items() if k.startswith('s25_')}
    s25u = {r.get('device_instance') for v in S.values() for r in v} - {None}
    log = [x for x in D.get('runlog', []) if x['device_instance'] not in s25u]       # RUNLOG lines of S25 units count only there
    s25log = [x for x in D.get('runlog', []) if x['device_instance'] in s25u]
    D = {k: v if k == 'reset_emu' else log if k == 'runlog' else with_runlog([corrected(r) for r in v], log) for k, v in D.items() if not k.startswith('s25_')}
    M = {k: [r for r in v if not pilot(r)] for k, v in D.items()}
    R = {'deploy': deploy(M['deploy']), 'gaps': gaps(M['gaps']), 'coverage': coverage(M['coverage']), 'race': race(M['stock']),
         'boundary': boundary(M['boundary']), 'pitfalls': pitfalls(M['pitfalls']), 'frozen': frozen(M['frozen']),
         'not_run': not_run(D['b0']), 'reset': reset(M['reset']), 'reset_emu': reset(D.get('reset_emu', [])),
         'host': matched_host(M['host']), 'continuous': continuous(M['continuous']), 'host_order': host_order(M['host'])}
    s25_trials = S.get('deploy', []) + [r for r in S.get('stock', []) if r['_file'] not in PARTIAL]
    R['s25'] = {'deploy': deploy(S.get('deploy', [])), 'race': race([r for r in S.get('stock', []) if r['_file'] not in PARTIAL]),
                'froze': froze(S.get('diag', []) + S.get('b0', [])), 'trials': s25_trials, 'partial': sum(r['_file'] in PARTIAL for r in S.get('stock', [])),
                'units': freezer_units({'s25': [r for v in S.values() for r in v] + s25log})}   # PARTIAL counts: it shows its unit's state
    R['phone_froze'] = froze(M['b0'] + M['diag'])
    R['units'], U = per_unit(M)
    X = R['not_run']
    nr = lambda src, val: NR if src in X else val       # a source not run prints NR, not TBD
    P = {'deploy': deploy([r for r in D['deploy'] if pilot(r)]),
         'records': dict(Counter(k for k, v in D.items() if k != 'all' for r in v if pilot(r)))}
    B1, G, BD, F, PF = R['deploy'], R['gaps'], R['boundary'], R['frozen'], R['pitfalls']
    med = lambda s, m: dur(st.median(B1[s, m]['delays_ms'])) if (s, m) in B1 and B1[s, m]['delays_ms'] else None
    fcl = lambda g: sec(st.median(G[g]['fcl'])) if g in G and G[g].get('fcl') else None
    def gmiss(gs, phase, p):
        k = [G[g]['miss'][phase, p] for g in gs if g in G and G[g]['miss'][phase, p]]
        return kn(sum(a for a, _ in k), sum(b for _, b in k)) if k and sum(b for _, b in k) else None
    frz = B1.get(('contacts', 'bg_freezer'))
    race_n, race_k = sum(z['n'] for z in R['race'].values()), sum(z['stale'] for z in R['race'].values())
    has = {'B1': any(z['valid'] for z in B1.values()), 'B2': any(z['n'] for z in G.values()), 'B4': race_n > 0,
           'B6': bool(R['host']), 'B10': bool(R['pitfalls'])}
    evid = lambda *ex: 'phone' if all(has[e] for e in ex) else None   # guidance-table evidence: measured on the phone
    cost = [c for z in G.values() for c in z.get('cost', [])]       # B2 late decisions with the client's lm_cost
    has['cost'] = bool(cost)
    cmed = lambda k: '%.0f' % st.median(c[k] for c in cost) if cost else None
    cci = lambda k: (lambda m: '[%.0f, %.0f]' % (m[1], m[2]))(ea.boot_ci([c[k] for c in cost])) if cost else None
    pf = lambda k: kn(*PF[k]) if PF and PF[k][1] else None          # B10 cell; no trials of that kind: TBD, not 0/0
    bk = lambda m, w: kn(*BD['k'](m, w)) if BD and BD['k'](m, w)[1] else None   # B9 class, same rule
    HO, CT, RS, RE = R['host'], R['continuous'], R['reset'], R['reset_emu']
    gain = lambda c: '%.1f [%.1f, %.1f]' % HO[c]['gain'] if c in HO else None
    det = sum(c[k] for c in CT.values() for k in c if k != 'ambiguous')
    cont = lambda k: kn(sum(c[k] for c in CT.values()), det) if det else None
    exp = [r for k in EXPERIMENTS for r in (current(M[k], defaultdict(Counter)) if k == 'gaps' else M.get(k, ()))]   # behind reported trials
    inst = {r.get('device_instance') for r in exp} - {None}
    fu = freezer_units(M)           # B0 and the freezer diagnosis count here: they show the unit's freezer state
    tfu = {u: on for u, on in fu.items() if u in inst}             # units behind reported trials with a known state
    S1, SR, sfu = R['s25']['deploy'], R['s25']['race'], R['s25']['units']
    smed = lambda s, m: dur(st.median(S1[s, m]['delays_ms'])) if (s, m) in S1 and S1[s, m]['delays_ms'] else None
    srn = sum(z['n'] for z in SR.values())
    nd = lambda B, s: kn(*nodelay(B, s)) if nodelay(B, s)[1] else None
    off = lambda F: kn(sum(not on for on in F.values()), len(F)) if F else None
    sf, pf_ = R['s25']['froze'], R['phone_froze']
    has['S25'] = any(z['valid'] for z in S1.values()) or srn > 0
    rng = lambda vals, f: (f % min(vals), f % max(vals)) if vals else (None, None)
    fmin, fmax = rng([v for v in U['fcl'].values()], '%.2f')
    cmin, cmax = rng([v for v in U['cte'].values() if v is not None], '%.1f')
    rreads = sorted({z['reads'][0] for z in HO.values()})
    macros = {
        'PhysDevice': ('device model', tex(device(D['all'], 'device'))),
        'PhysFingerprint': ('build fingerprint', builds(exp)),
        'PhysBuilds': ('distinct builds behind the reported trials', len({r['fingerprint'] for r in exp if r.get('fingerprint')}) or None),
        'PhysAndroid': ('Android release and SDK level', android(D['b0'])),
        'PhysRooted': ('root status', {'True': 'rooted', 'False': 'not rooted'}.get(device(D['all'], 'rooted') or '', None)),
        'PhysSdk': ('API level', device(D['all'], 'sdk')),
        'PhysInstances': ('distinct physical units', len(inst) or None),
        'PhysFreezerOffUnits': ('units with the freezer off before any run, of units with a known freezer state',
                                kn(sum(not on for on in fu.values()), len(fu)) if fu else None),
        # the two unit denominators, named: units behind reported trials (= PhysInstances) and units whose default
        # freezer state is known (adds units seen only in the B0 probe or the freezer diagnosis)
        'PhysUnitsTrials': ('Pixel 8 units behind the reported trials', len(inst) or None),
        'PhysUnitsFreezerKnown': ('Pixel 8 units with a known default freezer state, probe and diagnosis units included', len(fu) or None),
        'PhysFreezerOffTrialUnits': ('units behind reported trials with the freezer off by default / those with a known state', off(tfu)),
        # per unit (Table tab_phys_units)
        'PhysUnitsGap': ('units behind the gap trials', sum(t == 'Gaps' for t, *_ in R['units']) or None),
        'PhysUnitsGapBuilds': ('builds behind the gap trials', len(U['gap_builds']) or None),
        'PhysUnitFclMin': ('smallest per-unit median first callback over deferred-only gaps, s', fmin),
        'PhysUnitFclMax': ('largest per-unit median first callback over deferred-only gaps, s', fmax),
        'PhysUnitsLostAll': ('units on which event-only missed every lost-coverage change / units with lost-coverage gaps',
                             kn(sum(U['lost'].values()), len(U['lost'])) if U['lost'] else None),
        'PhysUnitsBoundary': ('units behind the boundary trials', sum(t == 'Action boundary' for t, *_ in R['units']) or None),
        'PhysUnitCteMin': ('smallest per-unit median check-to-effect, ms', cmin),
        'PhysUnitCteMax': ('largest per-unit median check-to-effect, ms', cmax),
        # Galaxy S25 (b13-* files)
        'PhysSamsungModel': ('S25 model number', tex(', '.join(sorted({r['device'].split()[-1] for r in R['s25']['trials'] if r.get('device')})) or None)),
        'PhysSamsungBuild': ('S25 build IDs', ', '.join('\\path{%s}' % b for b in build_ids(R['s25']['trials']).split(', ')) if R['s25']['trials'] else None),
        'PhysSamsungUnits': ('S25 units behind the reported trials', len({r.get('device_instance') for r in R['s25']['trials']} - {None}) or None),
        'PhysSamsungFreezerOffUnits': ('S25 units with the freezer off by default / units with a known state', off(sfu)),
        'PhysSamsungDeployTrials': ('S25 valid/attempted callback trials', kn(sum(z['valid'] for z in S1.values()), sum(z['attempted'] for z in S1.values())) if S1 else None),
        'PhysSamsungBgMedian': ('S25 Contacts background unfrozen median callback delay', smed('contacts', 'bg_unfrozen')),
        'PhysSamsungFgMedian': ('S25 Contacts FGS median callback delay', smed('contacts', 'fg')),
        'PhysSamsungAssistMedian': ('S25 Contacts bound assistant median callback delay', smed('contacts', 'assistant')),
        'PhysSamsungMediaBgMedian': ('S25 MediaStore background unfrozen median callback delay', smed('media', 'bg_unfrozen')),
        'PhysSamsungMediaFgMedian': ('S25 MediaStore FGS median callback delay', smed('media', 'fg')),
        'PhysSamsungNoDelay': ('S25 Contacts first callbacks with NOTIFY_NO_DELAY / Contacts first callbacks', nd(S1, 'contacts')),
        'PhysSamsungMediaNoDelay': ('S25 MediaStore first callbacks with NOTIFY_NO_DELAY / MediaStore first callbacks', nd(S1, 'media')),
        'PhysDeployNoDelay': ('Pixel 8 Contacts first callbacks with NOTIFY_NO_DELAY / Contacts first callbacks', nd(B1, 'contacts')),
        'PhysSamsungRaceTrials': ('S25 anchoring-race trials', srn or None),
        'PhysSamsungRaceStale': ('S25 trials with a stale anchor', sum(z['stale'] for z in SR.values()) if srn else None),
        'PhysSamsungFrozen': ('S25 freezer attempts, client cached and freezer on: frozen / attempts', kn(*sf[:2]) if sf[1] else None),
        'PhysSamsungFreezeWindowS': ('S25 shortest time a counted freezer attempt was watched, s', '%.0f' % sf[2] if sf[1] and sf[2] is not None else None),
        'PhysSamsungFreezeDebounceS': ('S25 freezer debounce set for those attempts, s', '%g' % sf[3] if sf[1] and sf[3] is not None else None),
        'PhysFreezerProbeFrozen': ('Pixel 8, same attempts: frozen / attempts', kn(*pf_[:2]) if pf_[1] else None),
        # host helper reads (Table tab_phys_host)
        'PhysHostReadsRefresh': ('B6 facts read per refresh batch, mean', ' to '.join('%.1f' % x for x in rreads) if rreads else None),
        'PhysHostReadsStampMin': ('B6 smallest per-case mean facts read per StampCheck batch', '%.1f' % min(z['reads'][1] for z in HO.values()) if HO else None),
        'PhysHostReadsStampMax': ('B6 largest per-case mean facts read per StampCheck batch', '%.1f' % max(z['reads'][1] for z in HO.values()) if HO else None),
        'PhysDeployTrials': ('B1 valid/attempted trials, all sources', kn(sum(z['valid'] for z in B1.values()), sum(z['attempted'] for z in B1.values())) if B1 else None),
        'PhysDeployBgMedian': ('B1 Contacts background unfrozen median callback delay', med('contacts', 'bg_unfrozen')),
        'PhysDeployFgMedian': ('B1 Contacts FGS median callback delay', med('contacts', 'fg')),
        'PhysDeployAssistMedian': ('B1 Contacts bound assistant median callback delay', med('contacts', 'assistant')),
        'PhysDeployFrozenBeforeThaw': ('B1 Contacts frozen trials with a callback before thaw', kn(frz['before_thaw'], frz['valid']) if frz and frz['valid'] else None),
        'PhysDeployMediaBgMedian': ('B1 MediaStore background unfrozen median callback delay', med('media', 'bg_unfrozen')),
        'PhysDeployMediaFgMedian': ('B1 MediaStore FGS median callback delay', med('media', 'fg')),
        'PhysDeployCalllogBgMedian': ('B1 call log background unfrozen median callback delay', nr('calllog', med('calllog', 'bg_unfrozen'))),
        'PhysDeployCalllogFgMedian': ('B1 call log FGS median callback delay', nr('calllog', med('calllog', 'fg'))),
        'PhysCoverageTrials': ('B3 candidate-stamp trials', R['coverage'].get('n')),
        'PhysGapTrials': ('B2 valid/attempted gap trials', kn(sum(z['n'] for z in G.values()), sum(z['att'] for z in G.values())) if G else None),
        'PhysGapNoneFcl': ('B2 no-gap median first callback, s', fcl('none')),
        'PhysGapFreezeFcl': ('B2 freezer median first callback, s', fcl('freeze')),
        'PhysGapDozeFcl': ('B2 deep Doze median first callback, s', fcl('dozeidle')),
        'PhysGapBucketFcl': ('B2 restricted bucket median first callback, s', fcl('bucket')),
        'PhysGapLostEv': ('B2 lost-coverage gaps, late: event-only missed/changed uses', gmiss(LOST, 'late', 'ev')),
        'PhysGapLostEvr': ('B2 lost-coverage gaps, late: restart-aware missed/changed uses', gmiss(LOST, 'late', 'evr')),
        'PhysGapLostLm': ('B2 lost-coverage gaps, late: StampCheck missed/changed uses', gmiss(LOST, 'late', 'lm')),
        'PhysGapInEpochEv': ('B2 in-epoch gaps, early: event-only missed/changed uses', gmiss(INEPOCH, 'early', 'ev')),
        'PhysGapInEpochEvr': ('B2 in-epoch gaps, early: restart-aware missed/changed uses', gmiss(INEPOCH, 'early', 'evr')),
        'PhysGapInEpochLm': ('B2 in-epoch gaps, early: StampCheck missed/changed uses', gmiss(INEPOCH, 'early', 'lm')),
        'PhysRaceTrials': ('B4 anchoring-race trials', race_n or None),
        'PhysRaceStale': ('B4 trials with a stale anchor', race_k if race_n else None),
        'PhysBoundaryTrials': ('B9 valid boundary trials', BD.get('n')),
        'PhysCteMs': ('B9 median check-to-effect interval, ms', f"{st.median(BD['cte']):.1f}" if BD.get('cte') else None),
        'PhysBndObsStale': ('B9 observation check, change before the action: stale/n', bk('obs', 'before_action')),
        'PhysBndBeforeCheckStale': ('B9 boundary check, change before the check: stale/n', bk('bnd', 'before_check')),
        'PhysBndOverlapStale': ('B9 boundary check, change overlaps check or residual: stale/n', bk('bnd', 'overlaps')),
        'PhysSmsReuse': ('B10 SMS id reuse trials', nr('sms', pf('sms'))),
        'PhysMtimeSame': ('B10 same-second mtime trials', pf('mtime')),
        'PhysClockTrials': ('B10 valid clock set-back trials', PF['clock'][1] if PF and PF['clock'][1] else None),
        'PhysClockStale': ('B10 clock set-back: stale number accepted/trials', pf('clock')),
        'PhysClockTsTransientStale': ('B10 clock, transient: timestamp StampCheck accepted the stale number/trials', pf('clock_ts')),
        'PhysClockTsPersistentGuard': ('B10 clock, persistent: clock guard raised/trials', pf('clock_guard')),
        'PhysFrozenHolds': ('B5 valid frozen holds', F.get('valid')),
        'PhysFrozenStayed': ('B5 holds that stayed frozen', F.get('stayed')),
        'PhysFrozenKilled': ('B5 holds ended by a kill', kn(F['died'], F['valid']) if F.get('valid') else None),
        'PhysFrozenLastUnseen': ('B5 sources whose last change had no later callback', kn(F['unseen'], F['src']) if F.get('valid') else None),
        **{k: ('B11/B12 dropped', NR) for k in DROPPED},
        'PhysHostTrials': ('B6 matched host trials', sum(z['n'] for z in R['host'].values()) or None),
        **{'PhysHostStampGain' + c.title(): ('B6 %s writes: refresh minus StampCheck, mean ms [CI]' % c, gain(c)) for c in ('none', 'one', 'continuous')},
        **{'PhysHostStampGain' + k: ('B6 %s over write cases of refresh minus StampCheck, mean ms' % k.lower(),
                                     '%.1f' % f(z['gain'][0] for z in HO.values()) if HO else None) for k, f in (('Min', min), ('Max', max))},
        'PhysContTrials': ('B7 continuous-write trials', len(M['continuous']) or None),
        'PhysContStaleCert': ('B7 arm trials stale at certification / determined', cont('stale_at_certification')),
        'PhysContActionOnly': ('B7 arm trials fresh at certification, stale at the action / determined', cont('stale_at_action_only')),
        'PhysContAmbiguous': ('B7 ambiguous arm trials / all', kn(sum(c['ambiguous'] for c in CT.values()), sum(sum(c.values()) for c in CT.values())) if CT else None),
        'PhysResetTrials': ('Contacts reset trials', RS.get('n')),
        'PhysResetSameStamp': ('Contacts reset: stamp unchanged / trials', kn(RS['same'], RS['n']) if RS else None),
        'PhysResetUnknown': ('Contacts reset: strict EvCheck UNKNOWN / trials', kn(RS['unknown'], RS['n']) if RS else None),
        'PhysResetEmuSameStamp': ('emulators, same rule: stamp unchanged / trials', kn(RE['same'], RE['n']) if RE else None),
        'PhysCostGl': ('B2 median provider ms per late decision, global refresh', cmed('gl_ms')),
        'PhysCostGlCi': ('B2 bootstrap CI of that median', cci('gl_ms')),
        'PhysCostLm': ('B2 median provider ms per late decision, StampCheck', cmed('lm_ms')),
        'PhysCostLmCi': ('B2 bootstrap CI of that median', cci('lm_ms')),
        'PhysCostN': ('B2 late decisions with cost', len(cost) or None),
        'PhysEvidCheap': ('phone B2 refresh cost', evid('cost')),   # B6 is optional (may be cut); it only adds
        'PhysEvidBound': ('phone B1 and B2', evid('B1', 'B2')),
        'PhysEvidWeak': ('phone B4 and B10', evid('B4', 'B10')),
        'PhysEvidHost': ('phone B6', evid('B6')),
    }
    return macros, R, P


# ------------------------------------------------------------------ tables (no data: one red TBD row)
REPLACED = 'superseded by rerun with StampCheck verdicts'


def gaps_note(G):
    """Gap caption tail: trials replaced by reruns, excluded trials per gap, and what ended the client in no-gap trials."""
    rep = sum(z['excluded'][REPLACED] for z in G.values())
    s = ' Runs whose client recorded no \\stamp verdicts were rerun gap by gap; their %d trials are not counted.' % rep if rep else ''
    ex = ['%d %s trial%s (%s)' % (n, GSHORT.get(g, g), 's' * (n != 1), w) for g, z in G.items() for w, n in sorted(z['excluded'].items()) if w != REPLACED]
    s += ' Excluded: %s.' % ', '.join(ex) if ex else ''
    d = G.get('none', {}).get('exit_desc')
    if d:   # e.g. "[TOO MANY EMPTY PROCS] too many empty": ActivityManager trimming idle cached processes
        s += (' No-gap exit record%s: ActivityManager killed the idle cached client during the hold (%s), and the decision started it again.'
              % ('s' if sum(d.values()) > 1 else '', ', '.join("``%s''" % k.split(']')[-1].strip() for k in sorted(d))))
    return s


def host_note(HO, order):
    """Host caption tail: whether order or unit could explain differences between write cases, and the on-device time
    of the refresh batch per write case."""
    units, alt = order
    if not (HO and alt and all(z['dev_refresh'] is not None for z in HO.values())):
        return ''
    return (' Write cases alternated trial by trial on %s unit%s and arm order was randomized, so the differences between write cases'
            ' are not an order, warm-up or unit effect. The on-device time of the refresh batch differs the same way (medians %s\\,ms'
            ' with %s writes), so the difference arises on the phone; its cause was not measured.'
            % ({1: 'one'}.get(units, units), 's' if units > 1 else '', ', '.join('%.1f' % z['dev_refresh'] for z in HO.values()), ', '.join(WRITES.get(c, c) for c in HO)))


def table(gen, name, caption, cols, header, rows, what, star=False, extra=(), tbd=True, font=''):
    env = 'table*' if star else 'table'
    body = (rows if rows or not tbd else [r'\multicolumn{%d}{c}{\PhysTBD{%s}}\\' % (len(cols), what)]) + list(extra)
    (gen / name).write_text('\n'.join(['%% AUTO-GENERATED by artifact/physical/analyze_phys.py; do not edit', r'\begin{%s}[tp]' % env, r'\centering\mtab',
        r'\caption{%s}' % caption, r'\label{tab:%s}' % name[4:-4].replace('_', '-'), font + r'\begin{tabular}{%s}\toprule' % cols,
        r'\mhead ' + header + r'\\\midrule', *body, r'\bottomrule\end{tabular}', r'\end{%s}' % env]) + '\n', encoding='utf-8', newline='\n')


def tables(gen, R):
    NOT_RUN = R['not_run']
    rows, last = [], None
    for (src, mode), z in R['deploy'].items():
        if src in NOT_RUN:
            continue
        if src != last:
            rows.append(r'\mgroup{5}{%s}' % SOURCES[src]); last = src
        d = z['delays_ms']
        held = 'held' if mode == 'bg_freezer' and z['valid'] else 'n/a'     # no valid trial: nothing was held
        rows.append(f"{NAMES[mode]} & {z['valid']}/{z['attempted']} & {dur(st.median(d)) if d else held} & "
                    f"{'[%s, %s]' % (dur(min(d)), dur(max(d))) if d else 'n/a'} & {kn(z['before_thaw'], z['valid']) if z['valid'] else 'n/a'}\\\\")
    table(gen, 'tab_phys_deploy.tex', "Pixel~8: callbacks per source and deployment, counted only for the trial's own source; valid/attempted trials, median and range of the delay, trials with a callback before thaw." + why(sum((z['excluded'] for z in R['deploy'].values()), Counter()), 'frozen trials'),
          'lrrrr', 'Deployment & Trials & Median & Range & Before thaw', rows, 'B1 deployment trials',
          extra=[r'\mgroup{5}{%s: %s}' % (SOURCES[x], NR) for x in SOURCES if x in NOT_RUN])

    rows = []
    cov = R['coverage']
    for c in cov.get('cells', []):
        if c['main'] and c['source'] not in NOT_RUN:
            cell = lambda k: kn(c[k + '_k'], c[k + '_n']) + ('$^{\\downarrow}$' if c.get(k + '_down') else '') if c.get(k + '_n') else 'n/a'
            rows.append(f"{SRCNAME[c['source']]} & {c['label']} & " + ' & '.join(cell(k) for k in ('insert', 'update', 'delete', 'none')) + r'\\')
    table(gen, 'tab_phys_coverage.tex', 'Pixel~8: trials in which a candidate stamp moved after one mutation of each kind by another app (%s trials); None = source untouched; $\\downarrow$: moved downward in some trials.' % cov.get('n', r'\PhysTBD{coverage trials}'),
          'llrrrr', 'Source & Candidate & Insert & Update & Delete & None', rows, 'B3 coverage trials',
          extra=[r'%s & \multicolumn{5}{l}{%s}\\' % (SRCNAME[x], NR) for x in sorted(NOT_RUN)],
          font=r'\scriptsize\setlength{\tabcolsep}{2.4pt}')   # as the emulator Table tab:coverage; fits one column

    rows = []
    for g, z in R['gaps'].items():
        m = lambda ph, p: kn(*z['miss'][ph, p]) if z['miss'][ph, p] else 'n/a'
        fc = '%s / %s' % (sec(st.median(z['fcl'])), sec(max(z['fcl']))) if z.get('fcl') else 'none'
        rows.append(f"{GAPNAME.get(g, g)} & {z['n']}/{z['att']} & {pct(z.get('survived', 0), z['n'])} & {fc} & {pct(z.get('ev_e', 0), z.get('nsrc', 0))} & "
                    f"{pct(z.get('ev_l', 0), z.get('nsrc', 0))} & {z.get('exit', 0)}/{z['n']} & " + ' & '.join(m(ph, p) for ph in ('early', 'late') for p in ('ev', 'evr', 'lm')) + r'\\')
    table(gen, 'tab_phys_gaps.tex', 'Pixel~8, background client: valid/attempted trials, process survival, first callback (median / max, s), changed provider sources notified by the early (+2\\,s) and late (+14\\,s) decision, new \\texttt{ApplicationExitInfo} records, and changed uses missed by event-only (Ev), restart-aware (Evr) and \\stamp at the early (+2\\,s) and late (+14\\,s) decision (missed/changed).' + gaps_note(R['gaps']),
          'lrrrrrrrrrrrr', r' & & & & \multicolumn{2}{c}{Notified} & & \multicolumn{3}{c}{Missed at +2\,s} & \multicolumn{3}{c}{Missed at +14\,s}\\ \mhead '
          r'Gap & Trials & Surv.\,\% & First cb. & +2\,s\,\% & +14\,s\,\% & Exit & Ev & Evr & \stamp & Ev & Evr & \stamp', rows, 'B2 gap trials', star=True)

    rows = [f"{SRCNAME.get(c, c)} & {z['n']} & {wil(z['stale'], z['n'])} & {z['unknown']}/{z['n']}\\\\" for c, z in sorted(R['race'].items()) if z['n'] and c not in NOT_RUN]
    table(gen, 'tab_phys_race.tex', 'Pixel~8: a writer races the optimistic anchor; trials whose anchor certified a value that had changed (Wilson 95\\% interval) and trials in which strict \\sys returned \\Unknown.',
          'lrrr', r'Source & Trials & Stale \Fresh & \Unknown', rows, 'B4 race trials',
          extra=[r'%s & \multicolumn{3}{l}{%s}\\' % (SRCNAME[x], NR) for x in sorted(NOT_RUN)])

    BD, rows, store = R['boundary'], [], ''
    if BD:
        store = ' The effect is %s.' % ' or '.join(sorted({'contacts': "a Data row of a separate raw contact, not Dana's",
                                                         'calllog': 'a call-log row'}[s] for s in BD['stores']))
        store += " Stale: the value used differs from Dana's number read right after the effect, as in Table~\\ref{tab:boundary}."
        if BD['wall']:
            store += (" The last two rows are a second reading: the number in the effect row against Dana's number at the effect's wall-clock"
                      " time. Undetermined: a change spans that time, so Dana's number at that instant is unknown.")
        for lab, m, w in [('check at observation; change before the action', 'obs', 'before_action'), ('boundary check; change before the check', 'bnd', 'before_check'),
                          ('boundary check; change overlaps check or residual', 'bnd', 'overlaps'), ('boundary check; change after the effect', 'bnd', 'after_effect'),
                          ('boundary check, no change (control)', 'bnd', 'none'), ('observation check, no change (control)', 'obs', 'none')]:
            rows.append(f"{lab} & {kn(*BD['k'](m, w))}\\\\")
        rows += [f"change starts within 10\\,ms of the check & {kn(*BD['bins']['near'])}\\\\", f"change starts 10 to 60\\,ms after it & {kn(*BD['bins']['late'])}\\\\"]
        if BD['wall']:      # second reading, Contacts store
            rows += [f"by the number at the effect's time & {kn(BD['wall']['stale'], BD['wall']['stale'] + BD['wall']['fresh'])}\\\\",
                     f"change spans the effect's time: undetermined & {BD['wall']['undetermined']}\\\\"]
        rows += [f"excluded: {w} & {c}\\\\" for w, c in sorted(BD['excluded'].items())]
    table(gen, 'tab_phys_boundary.tex', 'Pixel~8: stale effects by where the change landed relative to the boundary check and the effect (stale/trials); median check-to-effect interval \\PhysCteMs\\,ms.' + store,
          'lr', 'Placement of the change & Stale effects', rows, 'B9 boundary trials')

    PF, rows = R['pitfalls'], []
    if PF:
        cell = lambda k: wil(*PF[k]) if PF[k][1] else r'\PhysTBD{B10 %s trials}' % k     # no trials of that kind yet
        rows = [f"SMS \\texttt{{\\_id}} reused & {NR if 'sms' in NOT_RUN else cell('sms')}\\\\", f"same-second append keeps mtime & {cell('mtime')}\\\\",
                'clock back 1\\,h: versions keep old number & ' + (wil(*PF['clock']) if PF['clock'][1] else 'not run on this phone') + r'\\']
        if PF['clock_ts'][1]:
            rows.append('same, timestamps, clock restored & %s\\\\' % wil(*PF['clock_ts']))
    table(gen, 'tab_phys_pitfalls.tex', 'Pixel~8: evidence pitfalls, trials affected out of trials (Wilson 95\\% interval).',
          'lr', 'Pitfall & Trials affected', rows, 'B10 pitfall trials',
          extra=[r'SMS \texttt{\_id} reuse & %s\\' % NR] if 'sms' in NOT_RUN and not PF else [])

    F, rows = R['frozen'], []
    if F.get('valid'):
        rows = [f'Holds valid/run & {F["valid"]}/{F["run"]}\\\\', f'Stayed frozen & {F["stayed"]}\\\\', f'Killed & {F["died"]}\\\\', f'Changes & {F["changes"]}\\\\',
                f'Hold $\\geq$ (min) & {F["hold_min"]:.1f}\\\\', f'Lost sources & {F["lost"]}/{F["src"]}\\\\', f'Unseen last & {F["unseen"]}/{F["src"]}\\\\',
                f'Callbacks & {F["callbacks"]}\\\\', 'Restart-aware miss & %d/%d/%d\\\\' % tuple(F['evr'])]
    table(gen, 'tab_phys_frozen.tex', 'Pixel~8: long frozen holds, same metrics as Table~\\ref{tab:frozen}; lost and unseen sources count holds that stayed frozen; last row: changed uses missed by restart-aware event-only at +2/+14/+120\\,s.' + why(F.get('excluded'), 'holds'),
          'lr', 'Metric & Phone', rows, 'B5 frozen holds')

    HO = R['host']
    rows = [f"{c} & {z['n']} & {z['refresh']:.1f} & {z['stamp']:.1f} & {'%.1f' % z['relay'] if z['relay'] is not None else 'n/a'} & "
            f"{'%.1f [%.1f, %.1f]' % z['gain']} & {z['reads'][0]:.1f} / {z['reads'][1]:.1f}\\\\" for c, z in HO.items()]
    table(gen, 'tab_phys_host.tex', 'Pixel~8: matched host helper with a batched \\stamp arm; median batch latency in milliseconds, paired mean of refresh minus \\stamp with trial-bootstrap 95\\% CI, and facts read per batch (refresh / \\stamp); \\stamp re-reads only the facts its stamps do not confirm.' + host_note(HO, R['host_order']),
          'lrrrrrr', r'Writes & Trials & Refresh & \stamp & Relay & Refresh $-$ \stamp [CI] & Reads', rows, 'B6 host trials', star=True)
    CT = R['continuous']
    rows = [f"{a} & {c['fresh']} & {c['stale_at_certification']} & {c['stale_at_action_only']} & {c['ambiguous']}\\\\" for a, c in sorted(CT.items())]
    table(gen, 'tab_phys_continuous.tex', 'Pixel~8: continuous writes to Dana\\textquoteright s number while each arm certifies and then acts. Each arm trial is judged by the true number, from the writer\\textquoteright s timestamps, at two instants: certification (end of the arm\\textquoteright s read batch) and action (start of its effect). Stale at cert.: the value used differs from the number at certification; for refresh, a write committed between its read and the end of the batch. Stale at action: right at certification, wrong at the action. Ambiguous: an instant falls inside a write\\textquoteright s commit window (from the write call to its completion), where the true number is undefined.',
          'lrrrr', 'Arm & Fresh & Stale at cert. & Stale at action & Ambiguous', rows, 'B7 continuous trials')

    rows = ['%s & \\path{%s} & \\path{%s} & %s & %s\\\\' % r for r in R['units']]
    table(gen, 'tab_phys_units.tex', 'Pixel~8 trials per unit (\\texttt{device\\_instance}) and build, each test with the rules of its own table'
          ' (Tables~\\ref{tab:phys-deploy}, \\ref{tab:phys-gaps}, \\ref{tab:phys-race}, \\ref{tab:phys-host} and \\ref{tab:phys-boundary}). Gaps: first-callback'
          ' median over the no-gap, Doze and bucket gaps (deferred) and over the freezer gap; event-only misses at +14\\,s over the gaps that end'
          ' observer coverage (lost). Host helper: paired mean per write case. n/a: no valid trial.',
          'lllr>{\\raggedright\\arraybackslash}p{7.5cm}', 'Test & Unit & Build & Trials & Per-unit result', rows, 'per-unit trials', star=True, font='\\footnotesize')

    S, rows = R['s25'], []
    if S['trials']:
        B1, P = S['deploy'], R['deploy']
        cell = lambda D, k: (lambda z: '%s (%s)' % (dur(st.median(z['delays_ms'])), kn(z['valid'], z['attempted'])) if z['delays_ms'] else
                             'n/a (%s)' % kn(z['valid'], z['attempted']))(D[k]) if k in D else 'not run'
        for src in SOURCES:
            for mode in NAMES:
                if (src, mode) in B1:
                    rows.append('%s, %s & %s & %s\\\\' % (SOURCES[src], MODE[mode], cell(B1, (src, mode)), cell(P, (src, mode))))
        nd = lambda D, s: kn(*nodelay(D, s)) if nodelay(D, s)[1] else 'n/a'
        rows += ['%s, no-delay flag & %s & %s\\\\' % (SOURCES[s], nd(B1, s), nd(P, s)) for s in SOURCES if nodelay(B1, s)[1]]
        rn = lambda Z: kn(sum(z['stale'] for z in Z.values()), sum(z['n'] for z in Z.values())) if Z else 'n/a'
        rows.append('Race: stale \\Fresh & %s & %s\\\\' % (rn(S['race']), rn(R['race'])))
        fz = lambda f: kn(*f[:2]) if f[1] else 'n/a'
        rows.append('Cached client frozen & %s & %s\\\\' % (fz(S['froze']), fz(R['phone_froze'])))
        rows.append('Freezer off by default (units) & \\PhysSamsungFreezerOffUnits & \\PhysFreezerOffUnits\\\\')
    ps, adj = proc_states(S['deploy'].get(('contacts', 'bg_unfrozen'), {}).get('rows', []))
    bg = (' In every background Contacts trial the client was cached (process state %s, \\texttt{oom\\_adj} %s) and unfrozen at every sample.'
          % (' or '.join(sorted(ps)), ' or '.join(sorted(adj)))) if ps and adj else ''
    ident = ' (%s, build \\texttt{%s})' % (tex(S['trials'][0]['device'].split()[-1]), tex(build_ids(S['trials']))) if S['trials'] else ''   # no \path in a caption
    table(gen, 'tab_phys_samsung.tex', 'Galaxy~S25' + ident + ' against Pixel~8, with the rules of Tables~\\ref{tab:phys-deploy}'
          ' and~\\ref{tab:phys-race}; callbacks: median delay (valid/attempted trials). No-delay flag: the callback\\textquoteright s flags carry'
          ' \\texttt{ContentResolver}\\textquoteright s hidden \\texttt{NOTIFY\\_NO\\_DELAY} bit, with which \\texttt{ContentService} skips the 10\\,s'
          ' background deferral.' + bg + ' Frozen: freezer probe and diagnosis attempts with the client cached, \\PhysSamsungFreezeDebounceS\\,s debounce, each watched for at least \\PhysSamsungFreezeWindowS\\,s.'
          + (' A stopped partial race run (%d trial%s whose seeds repeat the full run) is excluded.' % (S['partial'], 's' * (S['partial'] != 1)) if S['partial'] else ''),
          'lrr', 'Measure & Galaxy~S25 & Pixel~8', rows, 'Galaxy S25 trials', font='\\small\\setlength{\\tabcolsep}{4pt}')

    for name, what in (('tab_phys_statelog.tex', '24-hour state log'), ('tab_phys_battery.tex', 'battery drain')):
        table(gen, name, 'Phone %s: not run.' % what, 'l', 'Status', [], what, tbd=False, extra=[WHY + r'\\'])


def write(D, gen):
    macros, R, P = analyze(D)
    lines = ['% AUTO-GENERATED by artifact/physical/analyze_phys.py; do not edit',
             r'\providecommand{\PhysTBD}[1]{}\renewcommand{\PhysTBD}[1]{\textcolor{red}{TBD}}']
    for src, sw in (('calllog', 'Calllog'), ('sms', 'Sms')):      # true unless the latest B0 excludes the source
        lines.append(r'\newif\ifPhys%s\Phys%s%s' % (sw, sw, 'false' if src in R['not_run'] else 'true'))
    lines.append(r'\newif\ifPhysReboot\PhysReboot%s' % ('true' if R['gaps'].get('reboot', {}).get('n') else 'false'))   # valid B2 reboot trials
    lines.append(r'\newif\ifPhysClock\PhysClock%s' % ('true' if R['pitfalls'].get('clock', (0, 0))[1] else 'false'))   # valid B10 clock trials
    lines.append(r'\newif\ifPhysBoundary\PhysBoundary%s' % ('true' if R['boundary'] else 'false'))   # valid, non-pilot B9 trials
    for sw, key in (('Reset', 'reset'), ('Host', 'host'), ('Cont', 'continuous')):    # Contacts reset, B6, B7 have data
        lines.append(r'\newif\ifPhys%s\Phys%s%s' % (sw, sw, 'true' if R[key] else 'false'))
    S = R['s25']        # Galaxy S25: a valid callback trial or race trial
    lines.append(r'\newif\ifPhysSamsung\PhysSamsung%s' % ('true' if any(z['valid'] for z in S['deploy'].values()) or any(z['n'] for z in S['race'].values()) else 'false'))
    for name, (what, val) in macros.items():
        lines.append('\\newcommand{\\%s}{%s\\xspace}' % (name, val if val is not None else '\\PhysTBD{%s}' % what))
    (gen / 'physical_macros.tex').write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
    tables(gen, R)
    return macros, P


def summary(B):
    """One line per (source, mode): valid/attempted, median delay; used for the pilot check on stdout."""
    return {f'{s}/{m}': f"{z['valid']}/{z['attempted']} valid, median {st.median(z['delays_ms']) if z['delays_ms'] else None} ms"
            for (s, m), z in B.items()}


# ------------------------------------------------------------------ self-check on in-memory records
def self_check():
    empty = {k: [] for k in FILES}
    with tempfile.TemporaryDirectory() as d:
        gen = Path(d)
        tab = lambda n: (gen / n).read_text(encoding='utf-8')
        m, _ = write(empty, gen)
        tex = tab('physical_macros.tex')
        assert all(v is None for k, (_, v) in m.items() if k not in DROPPED) and all(m[k][1] == NR for k in DROPPED), 'no data: TBD except dropped B11/B12'
        assert tex.count('\\PhysTBD{') == len(m) - len(DROPPED)
        assert all(s in tex for s in ('\\PhysCalllogtrue', '\\PhysSmstrue', '\\PhysRebootfalse', '\\PhysClockfalse', '\\PhysBoundaryfalse', '\\PhysResetfalse', '\\PhysHostfalse', '\\PhysContfalse')), 'before B0: SMS and call log run; nothing else'
        assert '\\renewcommand{\\PhysTBD}' in tex
        assert '%' not in tex.split('\n', 1)[1], 'a % in a macro would comment out the rest of its line'
        tabs = sorted(p.name for p in gen.glob('tab_phys_*.tex'))
        dropped = {'tab_phys_statelog.tex', 'tab_phys_battery.tex'}
        assert '(\\PhysTBD{coverage trials} trials)' in tab('tab_phys_coverage.tex')
        assert len(tabs) == 13 and all(('\\PhysTBD{' in tab(t)) == (t not in dropped) for t in tabs), tabs
        assert all('Device Farm' in tab(t) for t in dropped)

        D = {k: [] for k in FILES}
        def add(key, fname, *recs):
            for r in recs:
                r = dict(r, _file=fname); D[key].append(r); D['all'].append(r)
        # B1: Contacts, media and call-log trials; media and call-log callbacks never count for Contacts; pilot stays out
        def dep(mode, frozen, t, src=None, ev=None):
            r = {'mode': mode, 'device': 'Pixel_X', 'fingerprint': 'g/x_y:15/A.1:user', 'rooted': False, 'sdk': '35', 'before': {'frozen': frozen}, 'states': [{'frozen': frozen}],
                 'mutation': {'t_pre': 1000}, 'memory_before_thaw': {'events': [{'src': ev or src or 'contacts', 't': t}] if t else []}}
            return dict(r, source=src) if src else r   # no `source`: emulator-schema Contacts trial
        add('deploy', 'deploy-contacts-0900.jsonl', dep('bg_unfrozen', '0', 11000), dep('bg_unfrozen', '0', 11040), dep('bg_unfrozen', '1', 11000),
            dict(dep('bg_freezer', '1', None), use_freezer='true'), {'mode': 'fg', 'error': 'adb lost'})
        add('deploy', 'deploy-media-0930.jsonl', dep('bg_unfrozen', '0', 1500, 'media'), dep('bg_unfrozen', '0', 1200, 'media', ev='contacts'))
        add('deploy', 'deploy-calllog-1000.jsonl', dep('fg', '0', 1005, 'calllog'), dep('fg', '0', 1007, 'calllog'))
        add('deploy', 'deploy-pilot-contacts-0800.jsonl', dep('fg', '0', 1006, 'contacts'))
        # B2: two no-gap trials (callback 10 s after the change) on two device instances, one force-stop trial without the
        # AWS fields (older schema); a pilot trial and the B0 probe add instances that must not count
        def gap(g, pid_late, ev_t, mem, evr):
            f = {'src': 'contacts', 'ev': 'KEEP', 'te': 'KEEP', 'lm': 'CHANGED', 'lme': 'CHANGED', 'evr': evr, 'mem': mem, 'truth': 'B', 'refresh_ns': 2000000}
            dec = lambda t, ev: {'t_dec': t, 'fg': False, 'pid': pid_late, 'facts': {'c.dana': f}, 'events': ev, 'last_start': {},
                                 'lm_cost': {'contacts': {'ns': 2000000}, 'probe_contacts': 1000000}}
            ev = [{'src': 'contacts', 't': ev_t}] if ev_t else []
            return {'gap': g, 'protocol': 'v3', 'fg': False, 'trial': 0, 't_obs': 0, 't_gap_start': 100, 'hold': 5, 'pid_obs': 7,
                    'muts': [{'src': 'contacts', 'kind': 'update', 't_pre': 1000, 't_dev': 1000}], 'early': dec(7000, []), 'late': dec(19000, ev)}
        aws = lambda r, i: dict(r, device_instance='arn:devinst/' + i, run_arn='arn:run/' + i)
        add('gaps', 'gaps-none-1100.jsonl', aws(gap('none', 7, 11000, 'A', 'KEEP'), 'A'), aws(gap('none', 7, 11040, 'A', 'KEEP'), 'B'))
        add('gaps', 'gaps-forcestop-1130.jsonl', gap('forcestop', 8, None, 'A', 'REFRESH'))
        add('gaps', 'gaps-pilot-none-0800.jsonl', aws(gap('none', 7, 30000, 'A', 'KEEP'), 'C'))
        # B3, B4, B9, B10
        add('coverage', 'coverage-1200.jsonl', {'fg': False, 'p0': {'contacts.sum_raw_version': '5'}, 'p1': {'contacts.sum_raw_version': '6'},
                                                'muts': [{'src': 'contacts', 'kind': 'update', 't_pre': 0}], 'events': []})
        st_ = lambda changed: {'case': 'contacts', 'before': {'values': {'c.dana': 'A'}}, 'after': {'values': {'c.dana': 'B' if changed else 'A'}},
                               'historical': {'verdicts': {'c.dana': 'FRESH'}}, 'repaired': {'c.dana': {'verdict': 'UNKNOWN'}}}
        add('stock', 'stock-X-1230.jsonl', st_(True), st_(False))
        bnd = lambda mode, ms, me, stale: {'mode': mode, 'change': True, 'mut': {'mut_start': ms, 'mut_end': me},
                                           'res': {'stale': stale, 'check2_start': 100, 'effect_start': 120, 'effect_end': 130}}
        add('boundary', 'boundary-1300.jsonl', bnd('bnd', 50, 60, False), bnd('bnd', 105, 112, True), bnd('obs', 50, 60, True))
        add('pitfalls', 'pitfalls-1330.jsonl', {'exp': 'sms_reuse', 'res': {'ok': True, 'did': '5->5'}},
            {'exp': 'mtime', 'res': [{'ok': True}, {'ok': True, 'did': '7->8'}]})
        # B5: one hold that stayed frozen, one killed
        def hold(pid_v):
            dec = lambda **k: {'events': [], 'facts': {}, **k}
            return {'trial': 0, 'frozen_samples': [[0, '1']], 'frozen_at_end': '1', 'muts': [{'src': 'contacts', 't_pre': 100}], 't_gap_end': 700,
                    't_first_mut': 100, 'pid_obs': 5, 'frozen_with_pending_s': 600, 'early': dec(t_recv=700), 'late': dec(),
                    'vlate': dec(events=[{'src': 'contacts', 't': 701}], pid=pid_v, last_start={'exit': {'ts': 400, 'desc': 'too many cached'}})}
        add('frozen', 'frozen-0100.jsonl', dict(hold(5), use_freezer='true'), dict(hold(6), use_freezer='true'))
        add('b0', 'b0-probe-0600.jsonl', aws({'probe': 'identity', 'ok': True, 'detail': {'ro.build.version.release': '15', 'ro.build.version.sdk': '35'}}, 'D'))

        m, P = write(D, gen)
        v = {k: x for k, (_, x) in m.items()}
        assert v['PhysDeployBgMedian'] == '10.0\\,s' and v['PhysDeployTrials'] == '7/9' and v['PhysDeployFrozenBeforeThaw'] == '0/1', v['PhysDeployTrials']
        assert v['PhysDeployFgMedian'] is None, 'pilot or call-log trials leaked into Contacts FGS'
        assert v['PhysDeployMediaBgMedian'] == '500\\,ms' and v['PhysDeployCalllogFgMedian'] == '6\\,ms' and v['PhysDeployCalllogBgMedian'] is None
        assert v['PhysDevice'] == 'Pixel\\_X' and v['PhysRooted'] == 'not rooted' and v['PhysSdk'] == '35', v['PhysDevice']
        assert v['PhysFingerprint'] == '\\path{g/x_y:15/A.1:user}' and v['PhysAndroid'] == 'Android 15, SDK 35', (v['PhysFingerprint'], v['PhysAndroid'])
        assert v['PhysGapTrials'] == '3/3' and v['PhysGapNoneFcl'] == '10.0' and v['PhysGapFreezeFcl'] is None, (v['PhysGapTrials'], v['PhysGapNoneFcl'])
        assert v['PhysGapInEpochEv'] == '2/2' and v['PhysGapInEpochLm'] == '0/2' and v['PhysGapLostEvr'] == '0/1' and v['PhysGapLostEv'] == '1/1'
        assert v['PhysCoverageTrials'] == 1 and v['PhysRaceTrials'] == 2 and v['PhysRaceStale'] == 1
        assert v['PhysBoundaryTrials'] == 3 and v['PhysCteMs'] == '30.0' and v['PhysBndBeforeCheckStale'] == '0/1'
        assert v['PhysBndOverlapStale'] == '1/1' and v['PhysBndObsStale'] == '1/1'
        assert v['PhysSmsReuse'] == '1/1' and v['PhysMtimeSame'] == '0/1', 'no B0 yet: SMS runs'
        assert v['PhysFrozenHolds'] == 2 and v['PhysFrozenKilled'] == '1/2' and v['PhysFrozenLastUnseen'] == '0/2'
        assert v['PhysInstances'] == 2 and all(v[k] == NR for k in DROPPED), v['PhysInstances']
        assert P['deploy'][('contacts', 'fg')]['valid'] == 1 and P['records'] == {'deploy': 1, 'gaps': 1}
        assert v['PhysEvidBound'] == 'phone' and v['PhysEvidWeak'] == 'phone' and v['PhysEvidCheap'] == 'phone' and v['PhysHostTrials'] is None and v['PhysEvidHost'] is None   # B2 without B6 suffices
        assert v['PhysCostGl'] == '2' and v['PhysCostLm'] == '5' and v['PhysCostN'] == 3 and v['PhysCostLmCi'] == '[5, 5]', (v['PhysCostGl'], v['PhysCostLm'])
        nocost = dict(D, gaps=[dict(r, late={k: x for k, x in r['late'].items() if k != 'lm_cost'}) for r in D['gaps']])
        m, _ = write(nocost, gen); w = {k: x for k, (_, x) in m.items()}
        assert w['PhysEvidCheap'] is None and w['PhysCostGl'] is None and w['PhysGapTrials'] == '3/3', 'B2 without cost numbers must not claim phone evidence'
        # B6: two quiet trials, refresh 200 ms and 11 reads, StampCheck 150 ms and 4 reads; an error and an arm-less
        # record stay out
        arm = lambda ms, reads: {'_host_ns': ms * 1e6, 'fact_reads': reads, 'values': {'c.dana': 'A'}}
        hr = {'case': 'none', 'arms': {'refresh': arm(200, 11), 'stamp': arm(150, 4), 'relay': arm(50, 0)}, 'truth_after': {'values': {'c.dana': 'A'}}, 'writer_errors': []}
        add('host', 'host-X-1400.jsonl', hr, hr, {'case': 'none', 'arms': {}}, {'case': 'one', 'error': 'adb lost'})
        # B7: one change committed in [1000, 1010] ms; refresh certifies and acts before it (fresh), stamp certifies
        # after it with the old value (stale at certification), relay certifies before and acts after (stale at the
        # action only), x certifies inside the commit window (ambiguous)
        b7 = lambda tc, ta: {'batch': {'values': {'c.dana': 'A'}, 'wall_offset_ms': 0, 'end_ns': tc * 1e6, 'reads': {}}, 'effect': {'wall_ms': ta}}
        add('continuous', 'continuous-pilot-1400.jsonl', {'truth0': {'values': {'c.dana': 'A'}}, 'mutations': [], 'arms': {'stamp': b7(1500, 1600)}})
        add('continuous', 'continuous-1500.jsonl', {'truth0': {'values': {'c.dana': 'A'}}, 'mutations': [{'t_pre': 1000, 't_dev': 1010, 'tag': 'B'}],
                                                    'arms': {'refresh': b7(500, 600), 'stamp': b7(1500, 1600), 'relay': b7(900, 1100), 'x': b7(1005, 1100)}})
        # Galaxy S25 (b13-*): its own macros. Contacts callback after 12 ms carrying NOTIFY_NO_DELAY, MediaStore deferred
        # without it; the partial race run and diagnosis variant a (client keeps its FGS) do not count; the S25 unit's
        # RUNLOG line (freezer off by default) counts for the S25 only, never for the Pixel macros
        s25 = lambda r, f: dict(r, device='samsung SM-X', fingerprint='samsung/p/p:15/S.1/x:user/release-keys', device_instance='sA', _file=f)
        sd, sm = dep('bg_unfrozen', '0', 1012, 'contacts'), dep('bg_unfrozen', '0', 11000, 'media')
        sd['memory_before_thaw']['events'][0]['flags'], sm['memory_before_thaw']['events'][0]['flags'] = NO_DELAY | 1, 9
        D['s25_deploy'] = [s25(sd, 'b13-t-deploy-contacts-0600.jsonl'), s25(sm, 'b13-t-deploy-media-0600.jsonl')]
        D['s25_stock'] = [s25(st_(True), 'b13-t-stock-sA-0600.jsonl'), s25(st_(True), next(iter(PARTIAL)))]
        D['s25_diag'] = [s25({'exp': 'freeze_diag', 'variant': x, 'froze': False, 'use_freezer': 'true', 'debounce_ms': 2000,
                              'samples': [{'t_s': 3.8, 'frozen': '0'}, {'t_s': 26.0 if x == 'b' else 9.0, 'frozen': '0'}]}, 'b13-t-diag-0600.jsonl') for x in 'ab']
        D['runlog'] = [{'run_arn': 'arn:run/s', 'device_instance': 'sA', 'use_freezer_before': 'false', 'use_freezer': 'true', '_file': 'RUNLOG.md'}]
        m, _ = write(D, gen); v = {k: x for k, (_, x) in m.items()}
        assert v['PhysSamsungBgMedian'] == '12\\,ms' and v['PhysSamsungMediaBgMedian'] == '10.0\\,s' and v['PhysSamsungNoDelay'] == '1/1' and v['PhysSamsungMediaNoDelay'] == '0/1'
        assert v['PhysSamsungRaceTrials'] == 1 and v['PhysSamsungRaceStale'] == 1 and v['PhysSamsungFrozen'] == '0/1' and v['PhysSamsungFreezerOffUnits'] == '1/1', \
            (v['PhysSamsungRaceTrials'], v['PhysSamsungFrozen'], v['PhysSamsungFreezerOffUnits'])
        assert (v['PhysSamsungFreezeWindowS'], v['PhysSamsungFreezeDebounceS']) == ('26', '2'), 'window of the counted attempt b only (a keeps its FGS)'
        m, _ = write(dict(D, s25_b0=[s25({'probe': 'freezer_debounce_2s', 'ok': False, 'detail': {'frozen': '0', 'after_s': 25.1, 'debounce_get': '2000'}}, 'b13-t-b0-probe-0600.jsonl')]), gen)
        assert (m['PhysSamsungFrozen'][1], m['PhysSamsungFreezeWindowS'][1]) == ('0/2', '25'), 'the shortest watched attempt sets the window'
        assert v['PhysDevice'] == 'Pixel\\_X' and v['PhysInstances'] == 2 and v['PhysFreezerOffUnits'] is None and v['PhysDeployNoDelay'] == '0/2', 'S25 leaked into Pixel macros'
        assert v['PhysSamsungModel'] == 'SM-X' and v['PhysSamsungBuild'] == '\\path{S.1}' and '\\PhysSamsungtrue' in tab('physical_macros.tex')
        assert 'partial race run (1 trial whose' in tab('tab_phys_samsung.tex') and 'Contacts, no-delay flag & 1/1 & 0/2' in tab('tab_phys_samsung.tex')
        # per unit: no-gap trials on units A (10.0 s) and B (10.04 s), force-stop on a unit without device_instance
        assert v['PhysUnitsGap'] == 3 and (v['PhysUnitFclMin'], v['PhysUnitFclMax']) == ('10.00', '10.04') and v['PhysUnitsLostAll'] == '1/1', (v['PhysUnitsGap'], v['PhysUnitFclMin'])
        assert '\\path{arn:devinst/B} & \\path{?} & 1/1 & no gap: first cb. 10.04\\,s (deferred)' in tab('tab_phys_units.tex'), tab('tab_phys_units.tex')
        assert v['PhysHostReadsRefresh'] == '11.0' and v['PhysHostReadsStampMin'] == v['PhysHostReadsStampMax'] == '4.0'
        assert v['PhysEvidCheap'] == 'phone' and v['PhysEvidHost'] == 'phone' and v['PhysHostTrials'] == 2 and v['PhysHostStampGainNone'] == '50.0 [50.0, 50.0]' and v['PhysHostStampGainOne'] is None and v['PhysHostStampGainMin'] == v['PhysHostStampGainMax'] == '50.0'
        assert 'none & 2 & 200.0 & 150.0 & 50.0 & 50.0 [50.0, 50.0] & 11.0 / 4.0' in tab('tab_phys_host.tex'), tab('tab_phys_host.tex')
        assert v['PhysContTrials'] == 1 and v['PhysContStaleCert'] == '1/3' and v['PhysContActionOnly'] == '1/3' and v['PhysContAmbiguous'] == '1/4'
        assert 'refresh & 1 & 0 & 0 & 0' in tab('tab_phys_continuous.tex') and 'relay & 0 & 0 & 1 & 0' in tab('tab_phys_continuous.tex')
        assert '\\mgroup{5}{MediaStore}' in tab('tab_phys_deploy.tex') and tab('tab_phys_deploy.tex').count('Foreground service') == 2
        assert 'Force-stop & 1/1' in tab('tab_phys_gaps.tex') and '1/1 & 0/1 & 0/1 & 1/1 & 0/1 & 0/1' in tab('tab_phys_gaps.tex')
        assert 'not run on this phone' in tab('tab_phys_pitfalls.tex') and 'reused & 1/1 [' in tab('tab_phys_pitfalls.tex')
        assert not any('\\PhysTBD{' in tab(t) for t in tabs), [t for t in tabs if '\\PhysTBD{' in tab(t)]
        # \ifPhysReboot: true only with a valid, non-pilot B2 reboot trial
        rb = lambda f, **k: dict(gap('reboot', 8, None, 'A', 'REFRESH'), _file=f, **k)
        write(dict(D, gaps=D['gaps'] + [rb('gaps-reboot-1500.jsonl', error='adb lost'), rb('gaps-pilot-reboot-1500.jsonl')]), gen)
        assert '\\PhysRebootfalse' in tab('physical_macros.tex')
        write(dict(D, gaps=D['gaps'] + [rb('gaps-reboot-1500.jsonl')]), gen)
        assert '\\PhysReboottrue' in tab('physical_macros.tex')
        # B10 with mtime trials only: the SMS cell is TBD, never 0/0
        m, _ = write(dict(empty, pitfalls=[r for r in D['pitfalls'] if r['exp'] == 'mtime']), gen); w = {k: x for k, (_, x) in m.items()}
        assert w['PhysSmsReuse'] is None and w['PhysMtimeSame'] == '0/1' and '\\PhysTBD{B10 sms trials}' in tab('tab_phys_pitfalls.tex')
        assert '\\PhysClockfalse' in tab('physical_macros.tex') and w['PhysClockTrials'] is None
        # B10 clock set-back only (AWS schema): one stale number kept, one edit detected, one unchanged number; a trial whose clock did not move
        # back and an error record are invalid
        ck = lambda lm, stale, back=3599500, **k: {'exp': 'clock', 'variant': 'transient', 'lm': lm, 'stale_if_used': stale, 'clock_jump': False,
                                                  'clock_method': 'cmd alarm set-time', 'clock_moved_back_ms': back, **k}
        m, _ = write(dict(empty, pitfalls=[dict(r, _file='pitfalls-1700.jsonl') for r in (ck('FRESH', True), ck('CHANGED', True), ck('FRESH', False), ck('FRESH', True, back=0),
                                                                                          ck('FRESH', True, error='adb lost'))]), gen)
        w = {k: x for k, (_, x) in m.items()}
        assert w['PhysClockStale'] == '1/3' and w['PhysClockTrials'] == 3 and w['PhysMtimeSame'] is None, (w['PhysClockStale'], w['PhysClockTrials'])
        assert '\\PhysClocktrue' in tab('physical_macros.tex') and 'keep old number & 1/3 [' in tab('tab_phys_pitfalls.tex')
        # B1 frozen trials that all failed: no 0/0 and no "held" claim
        m, _ = write(dict(empty, deploy=[{'mode': 'bg_freezer', 'source': 'contacts', 'error': 'AssertionError', '_file': 'deploy-contacts-1700.jsonl'}]), gen)
        assert m['PhysDeployFrozenBeforeThaw'][1] is None and 'Background, frozen & 0/1 & n/a & n/a & n/a' in tab('tab_phys_deploy.tex')
        # B0 says the call log runs: call-log macros and B9 are computed (latest B0 record wins)
        add('b0', 'b0-probe-0600.jsonl', {'probe': 'user_info', 'ok': True, 'excluded_sources': ['sms', 'calllog'], 'detail': {}})
        add('b0', 'b0-probe-0700.jsonl', {'probe': 'user_info', 'ok': True, 'excluded_sources': ['sms'], 'detail': {}})
        m, _ = write(D, gen); v = {k: x for k, (_, x) in m.items()}
        assert v['PhysDeployCalllogFgMedian'] == '6\\,ms' and v['PhysBoundaryTrials'] == 3 and v['PhysSmsReuse'] == NR
        assert '\\PhysCalllogtrue' in tab('physical_macros.tex') and 'Call log' in tab('tab_phys_deploy.tex') and NR not in tab('tab_phys_boundary.tex')
        assert '\\PhysSmsfalse' in tab('physical_macros.tex') and NR in tab('tab_phys_pitfalls.tex')
        # B0 excludes the call log: call-log cells print NR, never TBD; B9 and other sources are unaffected
        add('b0', 'b0-probe-0800.jsonl', {'probe': 'user_info', 'ok': True, 'excluded_sources': ['sms', 'calllog'], 'detail': {}})
        m, _ = write(D, gen); v = {k: x for k, (_, x) in m.items()}
        assert v['PhysDeployCalllogBgMedian'] == NR and v['PhysDeployCalllogFgMedian'] == NR and v['PhysSmsReuse'] == NR
        assert v['PhysBoundaryTrials'] == 3 and v['PhysCteMs'] == '30.0' and '\\PhysBoundarytrue' in tab('physical_macros.tex'), 'B9 no longer depends on the call log'
        assert v['PhysDeployMediaBgMedian'] == '500\\,ms' and v['PhysMtimeSame'] == '0/1' and '\\PhysCalllogfalse' in tab('physical_macros.tex')
        assert 'Call log: ' + NR in tab('tab_phys_deploy.tex') and tab('tab_phys_deploy.tex').count('Foreground service') == 1
        assert all(NR in tab(t) for t in ('tab_phys_coverage.tex', 'tab_phys_race.tex', 'tab_phys_pitfalls.tex')) and NR not in tab('tab_phys_boundary.tex')
        assert '\\PhysTBD{' not in tab('tab_phys_boundary.tex')
        # same exclusion without any data: B9 is TBD like every other table
        bare = dict(empty, b0=D['b0'][-1:])
        m, _ = write(bare, gen); v = {k: x for k, (_, x) in m.items()}
        assert v['PhysBoundaryTrials'] is None and v['PhysDeployBgMedian'] is None and '\\PhysTBD{' in tab('tab_phys_boundary.tex')
        assert '\\PhysBoundaryfalse' in tab('physical_macros.tex')
        assert '\\PhysTBD{' in tab('tab_phys_deploy.tex') and 'Call log: ' + NR in tab('tab_phys_deploy.tex')
        # a later B0 runs every source: SMS and call log are computed again
        add('b0', 'b0-probe-0900.jsonl', {'probe': 'user_info', 'ok': True, 'excluded_sources': [], 'detail': {}})
        m, _ = write(D, gen); v = {k: x for k, (_, x) in m.items()}
        assert v['PhysSmsReuse'] == '1/1' and v['PhysBoundaryTrials'] == 3 and '\\PhysSmstrue' in tab('physical_macros.tex') and '\\PhysCalllogtrue' in tab('physical_macros.tex')
        # B9 with the effect in Contacts (AWS). Cells: the client's flag (value used vs Dana's number read right after the
        # effect), as on the emulators. Second reading: effect_row.number against Dana's number at wall_ms. check2 at
        # 100 ms, effect 120 to 130 ms, wall 125 ms, truth read 2 ms (c5: 20 ms). c1 change before the check; c2 change
        # ends inside the residual, old number used (stale both ways); c3 change spans wall_ms (undetermined by time);
        # c4 change after the effect, old number known (dana_number_before); c5 change starts inside the truth read,
        # old number unknown (undetermined); c12 as c5 with the old number known: the flag says stale (the read saw the
        # new number), the effect's time says fresh; c6 control; c10 observation check, change before the action. Excluded: c7
        # control whose VERSION moved, c8 no effect row, c9 change not made, c11 effect row is not the value used.
        bc = lambda mode, change, ms=None, me=None, num='B', truth='B', read_ns=2e6, used=None, **k: {
            'mode': mode, 'change': change, 'effect_store': 'contacts', 'mut': {'mut_start': ms, 'mut_end': me} if ms else {'ok': False} if change else None,
            'effect_row': {'number': num, 'id': 'r', 'wall_ms': 125, 'raw_contact_id': '9'}, 'dana_version_before': '7',
            'dana_version_after': '7', 'dana_version_unchanged': True, '_file': 'boundary-1800.jsonl',
            'res': {'stale': (used or num) != truth, 'used': used or num, 'check2_start': 100, 'check2_end': 118, 'effect_start': 120, 'effect_end': 130,
                    'truth_after_effect': truth, 'truth_read_ns': read_ns, 'effect_store': 'contacts'}, **k}
        recs = recs9 = [bc('bnd', 1, 50, 60), bc('bnd', 1, 105, 112, num='A'), bc('bnd', 1, 122, 128), bc('bnd', 1, 200, 205, num='A', truth='A', dana_number_before='A'),
                bc('bnd', 1, 131, 140, read_ns=20e6), bc('bnd', 0), bc('obs', 0, dana_version_after='8', dana_version_unchanged=False),
                bc('bnd', 0, effect_row={'raw': 'No result found.'}), bc('bnd', 1), bc('obs', 1, 50, 60, num='A'), bc('bnd', 0, num='X', used='B'),
                bc('bnd', 1, 131, 140, num='A', read_ns=20e6, dana_number_before='A'),
                bc('bnd', 1, 105, 112, num='A', _file='boundary-pilot-1800.jsonl')]
        m, _ = write(dict(empty, boundary=recs), gen); w = {k: x for k, (_, x) in m.items()}
        assert w['PhysBoundaryTrials'] == 8 and w['PhysCteMs'] == '30.0' and w['PhysBndBeforeCheckStale'] == '0/1', (w['PhysBoundaryTrials'], w['PhysCteMs'])
        assert w['PhysBndOverlapStale'] == '1/2' and w['PhysBndObsStale'] == '1/1' and '\\PhysBoundarytrue' in tab('physical_macros.tex'), w['PhysBndOverlapStale']
        bt = tab('tab_phys_boundary.tex')
        assert 'separate raw contact' in bt and 'after the effect & 1/3' in bt and 'no change (control) & 0/1' in bt, bt
        assert "by the number at the effect's time & 2/6" in bt and "change spans the effect's time: undetermined & 2" in bt, bt
        assert "VERSION moved in a control & 1" in bt and 'no effect row & 1' in bt and 'change not made & 1' in bt and 'effect row is not the value used & 1' in bt
        m, _ = write(dict(empty, boundary=[r for r in recs if r['mode'] == 'bnd' and not r['change']][1:]), gen)   # every trial excluded
        assert m['PhysBoundaryTrials'][1] is None and '\\PhysBoundaryfalse' in tab('physical_macros.tex')
        m, _ = write(dict(empty, boundary=[r for r in recs if r['mode'] == 'bnd']), gen)   # no observation trial: TBD, not 0/0
        assert m['PhysBndObsStale'][1] is None and m['PhysBndOverlapStale'][1] == '1/2'
        # freezer state (some Device Farm units ship with it off): a freezer trial counts only with the freezer on, read
        # from use_freezer, else from the saved `dumpsys activity settings` (config), else excluded as unknown
        fzd = lambda f, **k: dict(dep('bg_freezer', '1', None), _file=f, **k)
        cfg = lambda on: 'ACTIVITY MANAGER SETTINGS (dumpsys activity settings)\n  use_freezer=%s\n  freeze_debounce_timeout=10000' % on
        recs = [fzd('deploy-contacts-2000.jsonl', device_instance='uA', config=cfg('false')),          # old schema, unit off
                fzd('deploy-contacts-2000.jsonl', device_instance='uB', use_freezer_before='false', use_freezer='true'),   # turned on: valid
                fzd('deploy-contacts-2000.jsonl', device_instance='uG', config=cfg('true')),           # old schema, on: valid
                fzd('deploy-contacts-2000.jsonl', device_instance='uF'),                               # unknown
                fzd('deploy-contacts-2000.jsonl', device_instance='uA', use_freezer='false', config=cfg('true')),   # the field wins
                fzd('deploy-pilot-contacts-2000.jsonl', device_instance='uE', config=cfg('false'))]   # pilot: no trial, no unit
        b0p = {'probe': 'freezer_debounce_2s', 'ok': True, 'detail': {'frozen': '1'}, 'device_instance': 'uC', '_file': 'b0-probe-2000.jsonl'}
        dg = {'exp': 'diag', 'variant': 'b', 'froze': True, 'device_instance': 'uD', '_file': 'diag-b1-freeze-2000.jsonl'}
        m, _ = write(dict(empty, deploy=recs, b0=[b0p], diag=[dg]), gen); w = {k: x for k, (_, x) in m.items()}
        assert w['PhysDeployFrozenBeforeThaw'] == '0/2' and w['PhysFreezerOffUnits'] == '2/5' and w['PhysInstances'] == 4, (w['PhysDeployFrozenBeforeThaw'], w['PhysFreezerOffUnits'])
        assert 'Background, frozen & 2/5' in tab('tab_phys_deploy.tex')
        assert 'Excluded frozen trials: 2 (freezer off), 1 (freezer state unknown).' in tab('tab_phys_deploy.tex')
        gz = lambda **k: dict(gap('freeze', 7, 11000, 'A', 'KEEP'), frozen='1', _file='gaps-freeze-2000.jsonl', **k)
        hz = lambda **k: dict(hold(5), _file='frozen-2000.jsonl', **k)
        m, _ = write(dict(empty, gaps=[gz(use_freezer='true'), gz(use_freezer='false'), gz(), dict(gap('kill', 8, None, 'A', 'REFRESH'), _file='gaps-kill-2000.jsonl')],
                          frozen=[hz(use_freezer='true'), hz()]), gen); w = {k: x for k, (_, x) in m.items()}
        assert w['PhysGapTrials'] == '2/4' and w['PhysFrozenHolds'] == 1 and w['PhysFreezerOffUnits'] is None, (w['PhysGapTrials'], w['PhysFrozenHolds'])
        assert 'Excluded: 1 freezer trial (freezer off), 1 freezer trial (freezer state unknown).' in tab('tab_phys_gaps.tex')
        assert 'Excluded holds: 1 (freezer state unknown).' in tab('tab_phys_frozen.tex')
        m, _ = write(dict(empty, frozen=[hz(use_freezer='false')]), gen)                      # every hold excluded
        assert m['PhysFrozenHolds'][1] is None and '\\PhysTBD{' in tab('tab_phys_frozen.tex') and 'Excluded holds: 1 (freezer off).' in tab('tab_phys_frozen.tex')
        # the revised client reports strict EvCheck under `lm` (fact-keyed lm_cost with verdicts, as in B2 part 2 on the
        # phone): such trials give no StampCheck misses and no StampCheck cost; event-only is still counted
        strict = lambda t: dict(t, late=dict(t['late'], lm_cost={'c.dana': {'verdict': 'UNKNOWN', 'reason': 'strict_epoch_and_snapshot_unavailable',
                                                                            'fact': 'c.dana', 'start_ns': 1, 'end_ns': 2}}))
        m, _ = write(dict(empty, gaps=[strict(dict(gap('kill', 8, None, 'A', 'REFRESH'), _file='gaps-kill-2100.jsonl'))]), gen)
        w = {k: x for k, (_, x) in m.items()}
        assert w['PhysGapLostEv'] == '1/1' and w['PhysGapLostLm'] is None and w['PhysCostN'] is None and w['PhysEvidCheap'] is None, (w['PhysGapLostEv'], w['PhysGapLostLm'])
        assert 'am kill}) & 1/1' in tab('tab_phys_gaps.tex') and '& 1/1 & 0/1 & n/a\\\\' in tab('tab_phys_gaps.tex'), tab('tab_phys_gaps.tex')
        # RUNLOG "freezer on" lines (C7): parsed per run block; B1F shape: the saved settings read true after campaign.py
        # turned the freezer on, so the trial counts and the unit still counts as off; a record with neither field nor
        # settings takes the run's line; a run without a line stays unknown
        (gen / 'RUNLOG.md').write_text('- 00:57 AWS fetch arn:aws:devicefarm:r:1:run:p/R1: 4 files\n  - 17:47 B1F freezer on uH: use_freezer false -> true (x)\n'
                                       '  - 17:47 B1F setup: ...\n- 00:58 AWS fetch arn:aws:devicefarm:r:1:run:p/R2: 1 files\n  - 18:00 B1F setup: ...\n'
                                       '- 01:00 note: freezer on uZ: use_freezer false -> true, top level, not a run line\n', encoding='utf-8')
        log = runlog_freezer(gen / 'RUNLOG.md')
        assert [(x['run_arn'], x['device_instance'], x['use_freezer_before'], x['use_freezer']) for x in log] == [('arn:aws:devicefarm:r:1:run:p/R1', 'uH', 'false', 'true')], log
        recs = [fzd('deploy-contacts-freezer-1747.jsonl', device_instance='uH', run_arn='arn:aws:devicefarm:r:1:run:p/R1', config=cfg('true')),
                fzd('deploy-contacts-freezer-1747.jsonl', device_instance='uH', run_arn='arn:aws:devicefarm:r:1:run:p/R1'),
                fzd('deploy-contacts-freezer-1747.jsonl', device_instance='uI', run_arn='arn:aws:devicefarm:r:1:run:p/R2')]
        m, _ = write(dict(empty, deploy=recs, runlog=log), gen); w = {k: x for k, (_, x) in m.items()}
        assert w['PhysDeployFrozenBeforeThaw'] == '0/2' and w['PhysFreezerOffUnits'] == '1/1' and w['PhysInstances'] == 2, (w['PhysDeployFrozenBeforeThaw'], w['PhysFreezerOffUnits'])
        assert 'Excluded frozen trials: 1 (freezer state unknown).' in tab('tab_phys_deploy.tex')
        # client C6 (B2): StampCheck in lm_hist with lm_hist_cost, strict EvCheck in lm; the StampCheck columns and the
        # cost use lm_hist, as the emulator v3 `lm`; a strict-only trial stays out of them
        def c6(t, lmh):
            v = lambda D: dict(D, lm_cost={'c.dana': {'verdict': 'UNKNOWN', 'reason': 'strict_epoch_and_snapshot_unavailable'}},
                               lm_hist_cost={'contacts': {'ns': 3000000, 'reason': 'wm_moved'}, 'probe_contacts': 1000000},
                               facts={k: dict(f, lm='UNKNOWN', lmts='UNKNOWN', lm_hist=lmh, lmts_hist=lmh) for k, f in D['facts'].items()})
            return dict(t, early=v(t['early']), late=v(t['late']))
        kill = dict(gap('kill', 8, None, 'A', 'REFRESH'), _file='gaps-kill-2200.jsonl')
        m, _ = write(dict(empty, gaps=[c6(kill, 'CHANGED'), c6(kill, 'FRESH'), strict(kill)]), gen); w = {k: x for k, (_, x) in m.items()}
        assert w['PhysGapLostLm'] == '1/2' and w['PhysGapLostEv'] == '3/3' and w['PhysCostN'] == 2 and w['PhysCostLm'] == '5', (w['PhysGapLostLm'], w['PhysCostN'], w['PhysCostLm'])
        # B10 clock with the C6 fields: VERSION StampCheck from lm_hist, timestamp StampCheck from lm_ts_hist (transient),
        # the clock guard on persistent trials; a strict-only record (no lm_hist) is left out
        ck6 = lambda variant, lmh, lmts, jump=False, **k: dict({'exp': 'clock', 'variant': variant, 'lm': 'UNKNOWN', 'reason': 'strict_epoch_and_snapshot_unavailable',
                                                                'lm_hist': lmh, 'lm_ts_hist': lmts, 'reason_hist': 'wm_moved', 'stale_if_used': True,
                                                                'clock_jump': jump, 'clock_moved_back_ms': 3599000, '_file': 'pitfalls-2200.jsonl'}, **k)
        m, _ = write(dict(empty, pitfalls=[ck6('transient', 'CHANGED', 'FRESH'), ck6('persistent', 'CHANGED', 'UNKNOWN', True),
                                           ck6('transient', None, None)]), gen); w = {k: x for k, (_, x) in m.items()}
        assert w['PhysClockTrials'] == 2 and w['PhysClockStale'] == '0/2' and w['PhysClockTsTransientStale'] == '1/1' and w['PhysClockTsPersistentGuard'] == '1/1', \
            (w['PhysClockStale'], w['PhysClockTsTransientStale'], w['PhysClockTsPersistentGuard'])
        assert 'timestamps, clock restored & 1/1 [' in tab('tab_phys_pitfalls.tex')
        # B9: an ACT with the strict validator never enters the cells compared with the emulator
        m, _ = write(dict(empty, boundary=recs9[:2] + [dict(recs9[0], validator='strict')] + [dict(recs9[1], res=dict(recs9[1]['res'], validator='strict'))]), gen)
        assert m['PhysBoundaryTrials'][1] == 2 and 'excluded: EvCheck validator & 2' in tab('tab_phys_boundary.tex'), m['PhysBoundaryTrials']
        # B2 one consistent set per gap: a run with StampCheck verdicts (lm_hist) supersedes, gap by gap, runs without them,
        # also for a gap whose rerun trials are all invalid (freeze); a gap rerun nowhere keeps its old trials. The
        # FREEZER_FIX run's freeze file reads use_freezer true but ran with the freezer off.
        old = lambda g, **k: dict(gap(g, 8, None, 'A', 'REFRESH'), run_arn='arn:run:p/OLD', _file='gaps-%s-0100.jsonl' % g, device_instance='uS' if g == 'forcestop' else 'uK', **k)
        new = lambda g, **k: dict(c6(gap(g, 8, None, 'A', 'REFRESH'), 'CHANGED'), run_arn='arn:run:p/c3579ab2', _file='gaps-%s-1834.jsonl' % g, device_instance='uN', **k)
        fz = dict(gap('freeze', 7, 11000, 'A', 'KEEP'), frozen='1', use_freezer='true', run_arn='arn:run:p/c3579ab2', _file='gaps-freeze-1834.jsonl')
        m, _ = write(dict(empty, gaps=[old('forcestop'), old('forcestop'), new('forcestop'), old('kill'), old('freeze', frozen='1', use_freezer='true'), fz]), gen)
        w = {k: x for k, (_, x) in m.items()}
        assert w['PhysGapTrials'] == '2/3' and w['PhysGapLostLm'] == '0/2' and w['PhysGapFreezeFcl'] is None, (w['PhysGapTrials'], w['PhysGapLostLm'])
        assert w['PhysInstances'] == 2, 'a unit seen only in superseded trials is not behind a reported trial'
        assert 'their 3 trials are not counted. Excluded: 1 freezer trial (freezer off).' in tab('tab_phys_gaps.tex'), tab('tab_phys_gaps.tex')
        # Contacts reset (phone and the emulator counterpart, same rule); several builds print their build IDs
        rs = lambda same, **k: dict({'case': 'contacts_reset', 'reset_result': 'Success', 'before': {'watermark': 'V1'}, 'after': {'watermark': 'V1' if same else 'V2'},
                                     'verdict': {'verdict': 'UNKNOWN'}, '_file': 'contacts-reset-1840.jsonl'}, **k)
        m, _ = write(dict(empty, reset=[rs(True, fingerprint='g/s/s:15/A.1/9:user/r'), rs(False, fingerprint='g/s/s:15/B.2/9:user/r'), rs(True, reset_result='Error')],
                          reset_emu=[rs(True), rs(True)]), gen); w = {k: x for k, (_, x) in m.items()}
        assert w['PhysResetTrials'] == 2 and w['PhysResetSameStamp'] == '1/2' and w['PhysResetUnknown'] == '2/2' and w['PhysResetEmuSameStamp'] == '2/2'
        assert w['PhysFingerprint'] == '\\path{A.1}, \\path{B.2}' and w['PhysBuilds'] == 2 and '\\PhysResettrue' in tab('physical_macros.tex'), w['PhysFingerprint']
        # the real AWS sequence: an older partial B0 lists nothing, the valid later one lists calllog and sms
        b0 = lambda f, ex: {'probe': 'identity', 'ok': True, 'excluded_sources': ex, 'detail': {}, '_file': f}
        write(dict(empty, b0=[b0('b0-probe-1533.jsonl', []), b0('b0-probe-1551.jsonl', ['calllog', 'sms'])]), gen)
        assert '\\PhysSmsfalse' in tab('physical_macros.tex') and '\\PhysCalllogfalse' in tab('physical_macros.tex')
        # B6 over two write cases (gains 50 and 10 ms): the smallest and largest mean gain
        h2 = [dict(hr, _file='host-X-1400.jsonl'), dict(hr, case='one', arms=dict(hr['arms'], stamp=arm(190, 7)), _file='host-X-1400.jsonl')]
        m, _ = write(dict(empty, host=h2), gen)
        assert (m['PhysHostStampGainMin'][1], m['PhysHostStampGainMax'][1]) == ('10.0', '50.0')
        assert (m['PhysHostReadsStampMin'][1], m['PhysHostReadsStampMax'][1]) == ('4.0', '7.0')
        # B6 order: write cases that alternate on one unit; a repeated case breaks the alternation
        ho = lambda *cs: [{'case': c, 'start': i, 'device_instance': 'u', 'arms': {}} for i, c in enumerate(cs)]
        assert host_order(ho('none', 'one', 'continuous', 'none')) == (1, True) and host_order(ho('none', 'none', 'one'))[1] is False
        # a no-gap trial whose client ActivityManager killed during the hold: the caption names the exit description
        g = gap('none', 9, 11000, 'A', 'KEEP'); g['late'] = dict(g['late'], last_start={'exit': {'ts': 50, 'desc': '[TOO MANY EMPTY PROCS] too many empty'}})
        write(dict(empty, gaps=[dict(g, _file='gaps-none-2300.jsonl')]), gen)
        assert "No-gap exit record: ActivityManager killed the idle cached client during the hold (``too many empty'')" in tab('tab_phys_gaps.tex')
        # b13-* files load only for b13-* patterns
        (gen / 'physical-x').mkdir()
        for f in ('deploy-a.jsonl', 'b13-t-deploy-a.jsonl'):
            (gen / 'physical-x' / f).write_text('{"f": "%s"}\n' % f, encoding='utf-8')
        assert [r['f'] for r in load(gen, 'deploy*.jsonl')] == [r['f'] for r in load(gen, '*.jsonl')] == ['deploy-a.jsonl']
        assert [r['f'] for r in load(gen, B13 + '*-deploy*.jsonl')] == ['b13-t-deploy-a.jsonl']
    print('analyze_phys self-check ok')


if __name__ == '__main__':
    if '--self-check' in sys.argv:
        self_check()
    else:
        res = ROOT / 'artifact/results'
        emu = [dict(json.loads(l), _file=p.name) for p in sorted((res / 'revision-20261115').glob('supplement-final-emulator-*.jsonl'))
               for l in p.read_text(encoding='utf-8').splitlines() if '"contacts_reset"' in l]     # same rule on the emulators
        D = dict({k: load(res, p) for k, p in FILES.items()}, runlog=runlog_freezer(res / 'RUNLOG.md'), reset_emu=emu,
                 **{'s25_' + k: load(res, B13 + '*-' + p) for k, p in S25_FILES.items()})
        m, P = write(D, ROOT / 'manuscript/generated')
        print(json.dumps({'macros': len(m), 'tbd': sum(v is None for _, v in m.values()), 'runs': len({r.get('run_arn') for r in D['all']} - {None}),
                          'pilot_records': P['records'], 'pilot_deploy': summary(P['deploy'])}))
