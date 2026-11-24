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
macros and Table tab_phys_samsung with the same B1, B4 and freezer rules. Files named phys-*-pixel8aa17-* and
b13-pixel8aa17-* (Pixel 8a, Android 17) feed only the \\PhysEightA* macros, Tables tab_phys_eighta*, and the Pixel 8a
column of tab_phys_pitfalls. Captions name no experiment codes.
Run `python physical/analyze_phys.py --self-check`.
"""
import json, re, statistics as st, sys, tempfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'artifact/scripts'))
sys.path[:0] = [str(ROOT / 'artifact/revision'), str(ROOT / 'artifact/physical')]
import analyze as ea                      # noqa: E402  emulator analysis rules
from render import GAPNAME, SRCNAME, sci  # noqa: E402
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
B13 = 'b13-'        # other models (campaign.py --tag); data-dict keys '<model>_<experiment>'
MODELS = {'s25': 'b13-galaxys25-', 'p9': 'b13-pixel9a16-'}     # data-dict prefix -> file prefix
S25_FILES = dict({k: FILES[k] for k in ('deploy', 'stock', 'diag', 'b0', 'gaps', 'boundary')}, all='*.jsonl',
                 flags='notify-flags-*.jsonl', long='freeze-long-*.jsonl', screenoff='freeze-screenoff-*.jsonl')
P9_FILES = {k: FILES[k] for k in ('deploy', 'stock', 'b0')}
# Pixel 8a, Android 17 (second Device Farm account, campaign.py --tag pixel8aa17; experiment report F6): data-dict
# keys 'p8a_<test>', macros \PhysEightA*. Its L1 SMS part (0/50 valid, writes dropped) never enters a number.
P8A_FILES = {'b0': 'b13-pixel8aa17-b0-probe-*.jsonl', 'cost': 'phys-g14-pixel8aa17-cost-persource-*.jsonl',
             'scale': 'phys-g15-pixel8aa17-scale-*.jsonl', 'fgcost': 'phys-g16-pixel8aa17-fgcost-*.jsonl',
             'host': 'phys-g17-pixel8aa17-host-unbatched-*.jsonl', 'longdoze': 'phys-g18-pixel8aa17-longdoze-*.jsonl',
             'pitfalls': 'phys-l1-pixel8aa17-pitfalls-*.jsonl'}
GROUPS = (B13, 'phys-')     # file-name groups of other models (load)
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
    """All records of one experiment, with the file name; nothing is rewritten. Files of another model (b13-*, phys-*)
    load only for a pattern of the same group, so no Galaxy S25, Pixel 9 or Pixel 8a record reaches a Pixel 8 macro."""
    grp = lambda s: next((g for g in GROUPS if s.startswith(g)), '')
    return [dict(json.loads(l), _file=p.name) for p in sorted(res.glob('physical-*/' + pattern)) if grp(p.name) == grp(pattern)
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


def span(v):
    """Sorted values as 'lo to hi', or the one value."""
    return ' to '.join(str(a) for a in dict.fromkeys((v[0], v[-1])))


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


def needs_freezer(rows, excl, seen=None):
    """Rows whose trial depends on the freezer: keep those that ran with it on, count the others by reason. seen(r): the
    trial's own cgroup samples show the client frozen, which settles an unknown setting (Android 16 no longer prints
    use_freezer in `dumpsys activity settings`)."""
    keep = []
    for r in rows:
        fz = freezer_on(r)
        if fz or fz is None and seen and seen(r):
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
            frozen_seen = lambda r: (r.get('before') or {}).get('frozen') == '1' and bool(r.get('states')) and all(x.get('frozen') == '1' for x in r['states'])
            for r in needs_freezer(rs, excl, frozen_seen) if mode == 'bg_freezer' else rs:
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


KINDS = ('update', 'insert', 'delete')
REASON = {'unknown': 'no stamp', 'racy': 'racy mtime'}   # historical.cost reason of a never-certifying source


def flag_probe(rows):
    """S25 flag probe (physical/notify_flags.py): who sets NOTIFY_NO_DELAY. Groups: writes through the Contacts provider
    (writer mut or shell), an app's own notifyChange (writer notify; `kept`: the callback carries exactly the flags passed,
    case suffix _f<k>), and writes or notifies on other sources. Each: (with NO_DELAY, trials), median first delay ms."""
    T = [r for r in rows if r.get('exp') == 'notify_flags' and 'error' not in r and r.get('first_flags') is not None]
    if not T:
        return {}
    grp = {'writes': [r for r in T if r.get('source') == 'contacts' and r.get('writer') != 'notify'],
           'notify': [r for r in T if r.get('source') == 'contacts' and r.get('writer') == 'notify'],
           'other': [r for r in T if r.get('source') != 'contacts']}
    out = {k: (sum(bool(r['first_flags'] & NO_DELAY) for r in v), len(v), st.median(r['first_delay_ms'] for r in v) if v else None) for k, v in grp.items()}
    out['kept'] = (sum(r['first_flags'] == int(r['case'].rsplit('_f', 1)[1]) for r in grp['notify'] if '_f' in r['case']), len(grp['notify']))
    out['cases'], out['per_case'] = len({r['case'] for r in T}), min(Counter(r['case'] for r in T).values()) if T else 0
    return out


def contacts_flags(rows):
    """S25: every logged Contacts callback that a write through the provider produced. Events anywhere in a record (B1, B2,
    B0 trials: dicts with src, t and flags, counted once per record) and flag-probe callbacks after a write (writer not
    notify). Returns (with NOTIFY_NO_DELAY, callbacks), units and fingerprints of the records that logged one."""
    k = n = 0; units, fps = set(), set()
    def walk(x, out):
        if isinstance(x, dict):
            if {'src', 't', 'flags'} <= x.keys():
                out.add((x['src'], x['t'], x['flags']))
            for v in x.values():
                walk(v, out)
        elif isinstance(x, list):
            for v in x:
                walk(v, out)
    for r in rows:
        if r.get('exp') == 'notify_flags':
            fl = r.get('flags_all') or [] if r.get('source') == 'contacts' and r.get('writer') != 'notify' and 'error' not in r else []
        else:
            ev = set(); walk(r, ev); fl = [f for src, _, f in ev if src == 'contacts']
        if fl:
            k += sum(bool(f & NO_DELAY) for f in fl); n += len(fl)
            units.add(r.get('device_instance')); fps.add(r.get('fingerprint'))
    return (k, n), units - {None}, fps - {None}


def v1_frozen(cgroup):
    """The process sits in a cgroup v1 freezer group named frozen (Samsung), whatever Android's own freezer reports."""
    return any(':freezer:' in l and l.rstrip().endswith('/frozen') for l in str(cgroup).splitlines())


def long_freeze(rows):
    """S25 long window (physical/freeze_long.py), samples by phase: Android's freezer (isFrozen, cgroup v2) and the cgroup
    v1 freezer path. Phases run in order; the first screen-off phase is the first whose wakefulness is Dozing."""
    T = [r for r in rows if r.get('exp') == 'freeze_long']
    if not T:
        return {}
    phases = list(dict.fromkeys(r['phase'] for r in T))
    on = [r for r in T if r['phase'] == phases[0]]
    off = next((ph for ph in phases if all('Dozing' in r['wake'] for r in T if r['phase'] == ph)), None)
    to_v1 = [r['t_s'] for r in T if r['phase'] == off and v1_frozen(r['cgroup'])]
    def phase(ph):      # per phase, in run order: screen state, battery saver, samples in the v1 group and running there
        P = [r for r in T if r['phase'] == ph]
        v1 = [r for r in P if v1_frozen(r['cgroup'])]
        return {'name': ph, 'n': len(P), 'off': all('Dozing' in r['wake'] for r in P), 'saver': all(r.get('low_power') == '1' for r in P),
                'secs': max(r['t_s'] for r in P), 'in_v1': len(v1), 'running': sum('R (running)' in r['state'] for r in v1),
                'first_v1': min((r['t_s'] for r in v1), default=None)}
    return {'n': len(T), 'android_frozen': sum(r['isFrozen'] == 'true' or r['frozen'] == '1' for r in T),
            'on_s': max(r['t_s'] for r in on), 'on_v1': sum(v1_frozen(r['cgroup']) for r in on), 'to_v1': min(to_v1) if to_v1 else None,
            'running_in_v1': sum(v1_frozen(r['cgroup']) and 'R (running)' in r['state'] for r in T), 'in_v1': sum(v1_frozen(r['cgroup']) for r in T),
            'phases': [phase(ph) for ph in phases]}


def screen_off(rows):
    """S25 screen-off trials (physical/freeze_screenoff.py): client in the cgroup v1 frozen group when the change was
    written; trials that entered it while the screen was off and when (s after screen off); trials whose Contacts and
    MediaStore callbacks both arrived before the screen came back; the shortest screen-off observation."""
    T = [r for r in rows if r.get('exp') == 'freeze_screenoff' and 'error' not in r]
    if not T:
        return {}
    later = [next(x['t_s'] for x in r['samples'] if x['v1'] == '/frozen') for r in T if any(x['v1'] == '/frozen' for x in r['samples'])]
    return {'n': len(T), 'at_write': sum(r['v1_at_mutation'] == '/frozen' for r in T), 'later': later,
            'callbacks': sum(bool(r['contacts'].get('first_before_wake') and r['media'].get('first_before_wake')) for r in T),
            'off_s': min(r['samples'][-1]['t_s'] for r in T)}


def race_kinds(rows):
    """B4 by source and write kind. The schedule is seeded (revision/run.py: kinds cycle update, delete, insert; settings
    only update), so each (source, kind) cell is a fixed outcome. A source certifies when StampCheck ever returned FRESH or
    CHANGED for its own facts; otherwise every verdict was UNKNOWN (reasons from historical.cost: 'unknown' = no stamp,
    'racy' = racy-mtime guard). Returns per source {kind: (stale, n)}, certifying, reasons, and the totals
    stamped (stale over update or insert), deletes (caught = not stale), stampless (all own facts UNKNOWN)."""
    by = defaultdict(lambda: {'k': defaultdict(lambda: [0, 0]), 'cert': False, 'why': set(), 'unknown': 0, 'n': 0})
    for r in rows:
        if 'error' in r:
            continue
        z, kind, own = by[r['case']], r['mutation']['kind'], r['before']['values']
        stale = any(v != r['after']['values'][f] and r['historical']['verdicts'][f] == 'FRESH' for f, v in own.items())
        z['k'][kind][0] += stale; z['k'][kind][1] += 1; z['n'] += 1
        verdicts = {r['historical']['verdicts'][f] for f in own}
        z['cert'] |= verdicts != {'UNKNOWN'}; z['unknown'] += verdicts == {'UNKNOWN'}
        z['why'].add((r['historical'].get('cost', {}).get(r['case']) or {}).get('reason'))
    def tot(f):
        pairs = [p for z in by.values() for p in f(z)]
        return sum(a for a, _ in pairs), sum(b for _, b in pairs)
    return {'src': dict(by),
            'stamped': tot(lambda z: [(z['k'][k][0], z['k'][k][1]) for k in ('update', 'insert')] if z['cert'] else []),
            'deletes': tot(lambda z: [(z['k']['delete'][1] - z['k']['delete'][0], z['k']['delete'][1])] if z['cert'] and 'delete' in z['k'] else []),
            'stampless': tot(lambda z: [(z['unknown'], z['n'])] if not z['cert'] else [])}


def same_by_seed(a, b):
    """(trials of b whose stale outcome equals that of the a trial with the same source, trial and seed, matched trials)."""
    key = lambda r: (r.get('case'), r.get('trial'), r.get('seed'))
    stale = lambda r: any(v != r['after']['values'][f] and r['historical']['verdicts'][f] == 'FRESH' for f, v in r['before']['values'].items())
    A = {key(r): stale(r) for r in a if 'error' not in r}
    m = [(A[key(r)], stale(r)) for r in b if 'error' not in r and key(r) in A]
    return sum(x == y for x, y in m), len(m)


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
    wall_at, band = Counter(), []     # second reading per (mode, placement); planned offsets of band trials
    for r in rows:
        wc = None
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
            wc = 'undetermined' if truth is None else 'stale' if row['number'] != truth.split(',')[0] else 'fresh'
            wall[wc] += 1
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
        if wc:
            wall_at[r['mode'], where, wc] += 1
        if r.get('band') and r.get('delta_planned_ms') is not None:
            band.append(r['delta_planned_ms'])
    k = lambda m, w: (cls[m, w, True], cls[m, w, True] + cls[m, w, False])
    n = len(rows) - sum(excl.values())
    return {'n': n, 'cte': cte, 'k': k, 'bins': bins, 'excluded': excl, 'wall': wall, 'wall_at': wall_at, 'band': band, 'stores': stores} if n else {}


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
                                        if all('end_ns' in r['arms']['refresh'] for r in T) else None,   # on-device time of the refresh batch
                         # per arm: median on-device batch time, and median transport (host round trip minus on-device time)
                         'dev': {a: st.median((r['arms'][a]['end_ns'] - r['arms'][a]['start_ns']) / 1e6 for r in T) for a in ('refresh', 'stamp')
                                 if all('end_ns' in r['arms'][a] for r in T)},
                         'transport': {a: st.median((r['arms'][a]['_host_ns'] - (r['arms'][a]['end_ns'] - r['arms'][a]['start_ns'])) / 1e6 for r in T)
                                       for a in ('refresh', 'stamp', 'relay') if all(a in r['arms'] and 'end_ns' in r['arms'][a] for r in T)}}
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
    rows, U = [], {'fcl': {}, 'lost': {}, 'cte': {}, 'gap_builds': set(), 'fcl_builds': set()}
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
            U['fcl_builds'] |= {build_id(r['fingerprint']) for r in rs if r.get('fingerprint') and r['gap'] in DEFERRED}
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
        rows.append(('Anchoring race', u, build_ids(rs), str(n), 'stale \\Fresh after %s updates or inserts to stamped sources' % kn(*race_kinds(rs)['stamped'])))
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
    # the other tests, so that every unit behind a reported trial has a row
    for u, rs in by_unit(M['coverage']):
        n = coverage(rs).get('n')
        if n:
            rows.append(('Coverage', u, build_ids(rs), str(n), 'as Table~\\ref{tab:phys-coverage}'))
    for u, rs in by_unit(M['frozen']):
        F = frozen(rs)
        if F.get('valid'):
            rows.append(('Frozen holds', u, build_ids(rs), kn(F['valid'], F['run']), 'stayed frozen %d, killed %d' % (F['stayed'], F['died'])))
    for u, rs in by_unit(M['pitfalls']):
        PF = pitfalls(rs)
        if PF:
            parts = ['%s %s' % (w, kn(*PF[k])) for k, w in (('mtime', 'mtime kept'), ('clock', 'clock stale'), ('sms', 'SMS id reused')) if PF[k][1]]
            rows.append(('Pitfalls', u, build_ids(rs), str(sum(PF[k][1] for k in ('mtime', 'clock', 'sms'))), '; '.join(parts)))
    for u, rs in by_unit(M['reset']):
        RS = reset(rs)
        if RS:
            rows.append(('Contacts reset', u, build_ids(rs), str(RS['n']), 'stamp unchanged %s' % kn(RS['same'], RS['n'])))
    for u, rs in by_unit(M['continuous']):
        CT = continuous(rs); det = sum(c[k] for c in CT.values() for k in c if k != 'ambiguous')
        if CT:
            rows.append(('Continuous writes', u, build_ids(rs), str(len(rs)), 'arm trials stale at certification %s' % kn(sum(c['stale_at_certification'] for c in CT.values()), det)))
    return rows, U


def tex(s):
    """Plain device strings into LaTeX text."""
    return None if s is None else ''.join('\\' + c if c in '_&%#$' else c for c in s)


def android(b0):
    """'Android <release>, SDK <level>' from the B0 identity probe."""
    ids = [r['detail'] for r in b0 if r.get('probe') == 'identity' and r.get('ok') and isinstance(r.get('detail'), dict)]
    v = sorted({'Android %s, SDK %s' % (x.get('ro.build.version.release'), x.get('ro.build.version.sdk')) for x in ids})
    return '; '.join(v) if v else None


# ------------------------------------------------------------------ Pixel 8a, Android 17: cost tests (emulator rules)
COST_SRC = ('contacts', 'media', 'calendar', 'settings', 'files')
SCALE = {'contacts+0': 'Zero', 'contacts+1000': 'OneK', 'contacts+5000': 'FiveK', 'contacts+10000': 'TenK',
         'media+1000': 'MediaOneK', 'media+10000': 'MediaTenK'}       # phys_cost.py scale levels -> macro suffix


def persource_cost(rows):
    """Per-use cost (phys_cost.py persource; each round changes one source or none): per source, median ms to refresh
    one of its facts (every record) and of its \\stamp check (lm_hist_cost, the emulator `lm` of tab:cost) after that
    source changed and when it did not; stamp: some check found evidence (reason not 'unknown')."""
    rows, out = [r for r in rows if 'error' not in r], {}
    for s in COST_SRC:
        ref = [ns / 1e6 for r in rows for f, ns in r['refresh_ns'].items() if r['fact_src'].get(f) == s]
        sc = {ch: [r['costs']['lm_hist_cost'][s]['ns'] / 1e6 for r in rows if (r['source'] == s) == ch and s in r['costs']['lm_hist_cost']] for ch in (True, False)}
        if ref and sc[True] and sc[False]:
            out[s] = {'refresh': st.median(ref), 'changed': st.median(sc[True]), 'unchanged': st.median(sc[False]),
                      'stamp': any(r['costs']['lm_hist_cost'][s]['reason'] != 'unknown' for r in rows if s in r['costs']['lm_hist_cost'])}
    return out


def scale_cost(rows):
    """Cost versus source size (phys_cost.py scale): the columns of the emulator Table tab:scale (scripts/render.py e12)
    with \\stamp = lm_hist_cost and its timestamp adapter lmts_hist_cost; per level, medians over decisions without and
    after a change, refresh of the 3 Contacts and the 2 media facts, check-to-effect of the ACT records. fit: e12's
    least-squares line of check-to-effect on raw contacts over the ACT records of the Contacts levels."""
    rows, lv = [r for r in rows if 'error' not in r], {}
    med = lambda v: st.median(v) if v else None
    for L in dict.fromkeys(r['level'] for r in rows):
        R = [r for r in rows if r['level'] == L and not r.get('act')]; A = [r for r in rows if r['level'] == L and r.get('act')]
        if not R:
            continue
        sc = lambda key, s, ch: med([r['costs'][key][s]['ns'] / 1e6 for r in R if bool(r['change']) == ch and s in r['costs'].get(key, {})])
        rf = lambda fs: med([sum(r['refresh_ns'][f] for f in fs) / 1e6 for r in R])
        lv[L] = {'raw': R[0]['raw_contacts'], 'img': R[0]['images'], 'vc': sc('lm_hist_cost', 'contacts', False), 'vcc': sc('lm_hist_cost', 'contacts', True),
                 'vts': sc('lmts_hist_cost', 'contacts', False), 'rc': rf(('c.dana', 'c.omar', 'c.set')), 'vm': sc('lm_hist_cost', 'media', False),
                 'vmc': sc('lm_hist_cost', 'media', True), 'rm': rf(('m.latest', 'm.tracked')), 'cte': med([a['check_to_effect_ms'] for a in A]),
                 'n': len(R), 'acts': len(A), 'miss': sum(r.get('lm_miss', 0) for r in R)}
    A = [r for r in rows if r.get('act') and r['level'].startswith('contacts')]
    fit = None
    if len(A) > 2:
        x, y = [r['raw_contacts'] for r in A], [r['check_to_effect_ms'] for r in A]
        lr = st.linear_regression(x, y)
        fit = {'slope': lr.slope * 1000, 'intercept': lr.intercept, 'rsq': st.correlation(x, y) ** 2, 'n': len(A)}
    return {'levels': lv, 'fit': fit} if lv else {}


def fg_cost(rows):
    """FGS cost (phys_fgcost.py), as the emulator Table tab:fgcost (scripts/render.py e11): per mode, windows, changes
    and length per window, median CPU time (ticks / 100), PSS, BatteryStats' estimated charge over the windows that list
    the UID, and oom_score_adj. Estimates only: the phone stayed plugged in."""
    out = {}
    for mode in ('bg', 'fg'):
        R = [r for r in rows if r.get('mode') == mode and 'error' not in r]
        if R:
            pw = [r['est_power_mah'] for r in R if r.get('est_power_mah') is not None]
            out[mode] = {'n': len(R), 'window_s': st.median(r['window_s'] for r in R), 'changes': st.median(r['mutations'] for r in R),
                         'cpu_s': st.median(r['cpu_ticks'] for r in R) / 100, 'pss_mb': st.median(r['pss_kb'] for r in R) / 1024,
                         'power': st.median(pw) if pw else None, 'listed': len(pw), 'adj': sorted({int(r['oom_score_adj']) for r in R})}
    return out


def host_unbatched(rows):
    """Unbatched host agent (phys_host.py; one adb call per read, as the emulator Table tab:host): median ms to re-read
    every fact (global) and to read the watermarks and re-read what they do not certify (evcheck, \\stamp of tab:host),
    per decision kind (one change, none) and over all; the ratio of the medians; facts re-read; changed facts and those
    missed; median adb time of one content query (Contacts, MediaStore and Calendar facts, prefixes c. m. k.)."""
    T = [r for r in rows if 'error' not in r]
    if not T:
        return {}
    case = lambda C: {'n': len(C), 'gl': st.median(r['t_global_ms'] for r in C), 'ev': st.median(r['t_evcheck_ms'] for r in C),
                      'faster': sum(r['t_evcheck_ms'] < r['t_global_ms'] for r in C), 'reread': st.mean(r['n_reread'] for r in C),
                      'changed': sum(len(r['changed']) for r in C), 'missed': sum(len(r['evcheck_miss']) for r in C)}
    out = dict(case(T), facts=max(r['n_global'] for r in T), reread_med=st.median(r['n_reread'] for r in T),
               query_ms=st.median(v for r in T for f, v in r['ms_global'].items() if f[:2] in ('c.', 'm.', 'k.')),
               cases={ch: case(C) for ch in (True, False) for C in [[r for r in T if bool(r.get('change')) == ch]] if C})
    out['ratio'] = out['ev'] / out['gl']
    return out


def long_doze(rows):
    """Verified long Doze (e2v3_gaps.py longdoze2): gaps() with the emulator validity rule (IDLE at both mutation
    batches, client cgroup not frozen at either); the shortest Doze span of a valid trial, min; units."""
    z = gaps(rows).get('longdoze2')
    if not z:
        return {}
    V = [r for r in rows if ea.valid(r)[0]]
    return dict(z, span_min=min((r['t_gap_end'] - r['t_gap_start']) / 60000 for r in V) if V else None,
                units=len({r.get('device_instance') for r in rows} - {None}))


def eighta(P):
    """Pixel 8a results from its data dict (keys without the p8a_ prefix); the SMS part of the pitfalls file is left out."""
    pit = P.get('pitfalls', [])
    sms = [r for r in pit if r.get('exp') == 'sms_reuse']
    tests = [r for k in ('cost', 'scale', 'fgcost', 'host', 'longdoze', 'pitfalls') for r in P.get(k, [])]
    return {'cost': persource_cost(P.get('cost', [])), 'scale': scale_cost(P.get('scale', [])), 'fg': fg_cost(P.get('fgcost', [])),
            'host': host_unbatched(P.get('host', [])), 'doze': long_doze(P.get('longdoze', [])),
            'pitfalls': pitfalls([r for r in pit if r.get('exp') != 'sms_reuse']), 'sms': (sum(bool(r['res'].get('ok')) for r in sms), len(sms)),
            'tests': tests, 'android': android(P.get('b0', [])), 'units': len({r.get('device_instance') for r in tests} - {None}),
            'cost_n': sum('error' not in r for r in P.get('cost', []))}


def analyze(D):
    """D: experiment key -> records (with _file); keys 's25_<experiment>' hold the Galaxy S25 (b13-*) records. Returns
    (macros, results of main runs, results of pilot runs)."""
    S = {k[4:]: [r for r in v if not pilot(r)] for k, v in D.items() if k.startswith('s25_')}
    N = {k[3:]: [r for r in v if not pilot(r)] for k, v in D.items() if k.startswith('p9_')}
    E = {k[4:]: [r for r in v if not pilot(r)] for k, v in D.items() if k.startswith('p8a_')}
    s25u = {r.get('device_instance') for v in S.values() for r in v} - {None}
    p9u = {r.get('device_instance') for v in N.values() for r in v} - {None}
    p8au = {r.get('device_instance') for v in E.values() for r in v} - {None}
    log = [x for x in D.get('runlog', []) if x['device_instance'] not in s25u | p9u | p8au]   # RUNLOG lines of other models count only there
    s25log = [x for x in D.get('runlog', []) if x['device_instance'] in s25u]
    D = {k: v if k.endswith('_emu') else log if k == 'runlog' else with_runlog([corrected(r) for r in v], log) for k, v in D.items() if not k.startswith(('s25_', 'p9_', 'p8a_'))}
    M = {k: [r for r in v if not pilot(r)] for k, v in D.items()}
    R = {'deploy': deploy(M['deploy']), 'gaps': gaps(M['gaps']), 'coverage': coverage(M['coverage']), 'race': race(M['stock']),
         'boundary': boundary(M['boundary']), 'pitfalls': pitfalls(M['pitfalls']), 'frozen': frozen(M['frozen']),
         'not_run': not_run(D['b0']), 'reset': reset(M['reset']), 'reset_emu': reset(D.get('reset_emu', [])),
         'host': matched_host(M['host']), 'continuous': continuous(M['continuous']), 'host_order': host_order(M['host'])}
    s25_trials = S.get('deploy', []) + [r for r in S.get('stock', []) if r['_file'] not in PARTIAL] + sum((S.get(k, []) for k in ('gaps', 'boundary', 'flags', 'long', 'screenoff')), [])
    R['s25'] = {'deploy': deploy(S.get('deploy', [])), 'race': race([r for r in S.get('stock', []) if r['_file'] not in PARTIAL]),
                'froze': froze(S.get('diag', []) + S.get('b0', [])), 'trials': s25_trials, 'partial': sum(r['_file'] in PARTIAL for r in S.get('stock', [])),
                'units': freezer_units({'s25': [r for v in S.values() for r in v] + s25log})}   # PARTIAL counts: it shows its unit's state
    R['phone_froze'] = froze(M['b0'] + M['diag'])
    R['units'], U = per_unit(M)
    s25_stock = [r for r in S.get('stock', []) if r['_file'] not in PARTIAL]
    R['race_kinds'], R['s25']['race_kinds'] = race_kinds(M['stock']), race_kinds(s25_stock)
    R['s25']['same'] = same_by_seed(M['stock'], s25_stock)
    R['emu'] = {'race': race_kinds(D.get('stock_emu', [])), 'deploy': deploy(D.get('deploy_emu', []))}   # emulator cells, same rules
    R['s25'].update(gaps=gaps(S.get('gaps', [])), boundary=boundary(S.get('boundary', [])), flags=flag_probe(S.get('flags', [])),
                    long=long_freeze(S.get('long', [])), screen=screen_off(S.get('screenoff', [])),
                    gap_units=len({r.get('device_instance') for r in S.get('gaps', [])} - {None}), cflags=contacts_flags(S.get('all', [])),
                    bnd_changes=sum(bool(r.get('change')) and r.get('mode') == 'bnd' and not r.get('band') for r in S.get('boundary', [])))
    R['p9'] = {'deploy': deploy(N.get('deploy', [])), 'race_kinds': race_kinds(N.get('stock', [])), 'same': same_by_seed(M['stock'], N.get('stock', [])),
               'froze': froze(N.get('b0', [])), 'trials': N.get('deploy', []) + N.get('stock', []), 'android': android(N.get('b0', [])),
               'probe_s': min(((r.get('detail') or {}).get('after_s') for r in N.get('b0', []) if r.get('probe') == 'freezer_debounce_2s'
                               and (r.get('detail') or {}).get('frozen') == '1'), default=None)}
    R['p8a'] = eighta(E)
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
    rk = lambda K, key: kn(*K[key]) if K[key][1] else None          # race_kinds total
    off = lambda F: kn(sum(not on for on in F.values()), len(F)) if F else None
    sf, pf_ = R['s25']['froze'], R['phone_froze']
    has['S25'] = any(z['valid'] for z in S1.values()) or srn > 0
    rng = lambda vals, f: (f % min(vals), f % max(vals)) if vals else (None, None)
    fmin, fmax = rng([v for v in U['fcl'].values()], '%.2f')
    cmin, cmax = rng([v for v in U['cte'].values() if v is not None], '%.1f')
    rreads = sorted({z['reads'][0] for z in HO.values()})
    (G25, B25, FL, LG, SO), P9 = (R['s25'][k] for k in ('gaps', 'boundary', 'flags', 'long', 'screen')), R['p9']
    def g25(gs, p):
        k = [G25[g]['miss']['late', p] for g in gs if g in G25 and G25[g]['miss']['late', p]]
        return kn(sum(a for a, _ in k), sum(b for _, b in k)) if k and sum(b for _, b in k) else None
    b25 = lambda m, w: kn(*B25['k'](m, w)) if B25 and B25['k'](m, w)[1] else None
    n9 = lambda s_, m: dur(st.median(P9['deploy'][s_, m]['delays_ms'])) if (s_, m) in P9['deploy'] and P9['deploy'][s_, m]['delays_ms'] else None
    nfz = P9['deploy'].get(('contacts', 'bg_freezer'))
    A8 = R['p8a']
    C8, FG8, H8, DZ8, PF8 = (A8[k] for k in ('cost', 'fg', 'host', 'doze', 'pitfalls'))
    lv8, fit8 = A8['scale'].get('levels', {}), A8['scale'].get('fit')
    f1 = lambda x: None if x is None else '%.1f' % x
    sl = lambda L, k: f1(lv8[L][k]) if L in lv8 else None
    dz = lambda ph, p: kn(*DZ8['miss'][ph, p]) if DZ8 and DZ8['miss'][ph, p] else None
    pf8 = lambda k: kn(*PF8[k]) if PF8 and PF8[k][1] else None
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
        'PhysUnitsDeferred': ('units behind deferred-only gap trials (no gap, Doze, bucket)', len(U['fcl']) or None),
        'PhysUnitsDeferredBuilds': ('builds behind deferred-only gap trials', len(U['fcl_builds']) or None),
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
        'PhysSamsungFreezerOffTrialUnits': ('S25 units behind reported trials with the freezer off by default / those with a known state',
                                            off({u: on for u, on in sfu.items() if u in {r.get('device_instance') for r in R['s25']['trials']}})),
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
        'PhysSamsungRaceStampedStale': ('S25 race: stale FRESH / updates and inserts on certifying sources', rk(R['s25']['race_kinds'], 'stamped')),
        # Galaxy S25: gaps, boundary, flag probe, long window, screen off (one unit per test unless stated)
        'PhysSamsungGapTrials': ('S25 valid/attempted gap trials', kn(sum(z['n'] for z in G25.values()), sum(z['att'] for z in G25.values())) if G25 else None),
        'PhysSamsungGapUnits': ('S25 units behind the gap trials', R['s25']['gap_units'] or None),
        'PhysSamsungGapNoneEv': ('S25 no gap, late: event-only missed/changed uses', g25(['none'], 'ev')),
        'PhysSamsungGapLostEv': ('S25 lost-coverage gaps, late: event-only missed/changed uses', g25(LOST, 'ev')),
        'PhysSamsungGapLostEvr': ('S25 lost-coverage gaps, late: restart-aware missed/changed uses', g25(LOST, 'evr')),
        'PhysSamsungGapLostLm': ('S25 lost-coverage gaps, late: StampCheck missed/changed uses', g25(LOST, 'lm')),
        'PhysSamsungBoundaryTrials': ('S25 valid boundary trials', B25.get('n')),
        'PhysSamsungBndChanges': ('S25 boundary-check changes over the planning window', R['s25']['bnd_changes'] or None),
        'PhysSamsungBndBandTrials': ('S25 boundary trials with the change in the band', len(B25['band']) if B25 and B25['band'] else None),
        'PhysSamsungCteMs': ('S25 median check-to-effect interval, ms', '%.1f' % st.median(B25['cte']) if B25 and B25['cte'] else None),
        'PhysSamsungBndObsStale': ('S25 observation check, change before the action: stale/n', b25('obs', 'before_action')),
        'PhysSamsungBndBeforeCheckStale': ('S25 boundary check, change before the check: stale/n', b25('bnd', 'before_check')),
        'PhysSamsungBndOverlapStale': ('S25 boundary check, change overlaps: stale/n', b25('bnd', 'overlaps')),
        **{'PhysSamsungBndOverlapWall' + w.title()[:5]: ('S25 overlap trials by the number at the effect time: %s' % w, B25['wall_at'][('bnd', 'overlaps', w)] if B25 and B25['wall_at'] else None)
           for w in ('stale', 'fresh', 'undetermined')},
        'PhysSamsungFlagWrites': ('S25 flag probe: writes through the Contacts provider whose first callback has NOTIFY_NO_DELAY / trials', kn(*FL['writes'][:2]) if FL and FL['writes'][1] else None),
        'PhysSamsungFlagNotify': ('S25 flag probe: an app notifyChange on the Contacts URI with NOTIFY_NO_DELAY / trials', kn(*FL['notify'][:2]) if FL and FL['notify'][1] else None),
        'PhysSamsungFlagKept': ('S25 flag probe: app notifyChange callbacks carrying exactly the flags passed / trials', kn(*FL['kept']) if FL and FL['kept'][1] else None),
        'PhysSamsungFlagOther': ('S25 flag probe: Calendar, MediaStore, Settings cases with NOTIFY_NO_DELAY / trials', kn(*FL['other'][:2]) if FL and FL['other'][1] else None),
        'PhysSamsungFlagNotifyDelay': ('S25 flag probe: median first delay after an app notifyChange on the Contacts URI', dur(FL['notify'][2]) if FL and FL['notify'][1] else None),
        'PhysSamsungFlagCallbacks': ('S25: logged Contacts callbacks after a write through the provider with NOTIFY_NO_DELAY / those callbacks',
                                     kn(*R['s25']['cflags'][0]) if R['s25']['cflags'][0][1] else None),
        'PhysSamsungFlagUnits': ('S25 units that logged such callbacks', len(R['s25']['cflags'][1]) or None),
        'PhysSamsungFlagBuilds': ('S25 build fingerprints of those units', len(R['s25']['cflags'][2]) or None),
        'PhysSamsungFlagCases': ('S25 flag probe cases', FL.get('cases') or None),
        'PhysSamsungFlagPerCase': ('S25 flag probe trials per case (smallest)', FL.get('per_case') or None),
        'PhysSamsungLongSamples': ('S25 long window samples', LG.get('n')),
        'PhysSamsungLongAndroidFrozen': ('S25 long window: samples frozen by Android (isFrozen or cgroup v2) / samples', kn(LG['android_frozen'], LG['n']) if LG else None),
        'PhysSamsungLongScreenOnS': ('S25 long window: screen-on cached phase, s', '%.0f' % LG['on_s'] if LG else None),
        'PhysSamsungLongToGroupS': ('S25 long window: first sample in the cgroup v1 frozen group after screen off, s', '%.0f' % LG['to_v1'] if LG and LG['to_v1'] is not None else None),
        'PhysSamsungLongRunning': ('S25 long window: samples in the v1 frozen group whose /proc state is R / samples in that group', kn(LG['running_in_v1'], LG['in_v1']) if LG and LG['in_v1'] else None),
        'PhysSamsungScreenTrials': ('S25 screen-off trials', SO.get('n')),
        'PhysSamsungScreenAtWrite': ('S25 screen-off trials with the client in the v1 frozen group at the write / trials', kn(SO['at_write'], SO['n']) if SO else None),
        'PhysSamsungScreenLater': ('S25 screen-off trials that entered the v1 frozen group while the screen was off / trials', kn(len(SO['later']), SO['n']) if SO else None),
        'PhysSamsungScreenLaterMin': ('S25 earliest entry into the v1 frozen group, s after screen off', '%.0f' % min(SO['later']) if SO and SO['later'] else None),
        'PhysSamsungScreenLaterMax': ('S25 latest entry into the v1 frozen group, s after screen off', '%.0f' % max(SO['later']) if SO and SO['later'] else None),
        'PhysSamsungScreenCallbacks': ('S25 screen-off trials whose Contacts and MediaStore callbacks arrived before wake / trials', kn(SO['callbacks'], SO['n']) if SO else None),
        'PhysSamsungScreenNever': ('S25 screen-off trials that never entered the v1 frozen group while the screen was off / trials', kn(SO['n'] - len(SO['later']), SO['n']) if SO else None),
        'PhysSamsungScreenOffS': ('S25 shortest screen-off observation, s', '%.0f' % SO['off_s'] if SO else None),
        # Pixel 9, Android 16 (b13-pixel9a16-*)
        'PhysNineModel': ('Pixel 9 model', tex(', '.join(sorted({r['device'].split(' ', 1)[-1] for r in P9['trials'] if r.get('device')})) or None)),
        'PhysNineBuild': ('Pixel 9 build IDs', ', '.join('\\path{%s}' % b for b in build_ids(P9['trials']).split(', ')) if P9['trials'] else None),
        'PhysNineAndroid': ('Pixel 9 Android release and SDK level', P9['android']),
        'PhysNineUnits': ('Pixel 9 units behind the reported trials', len({r.get('device_instance') for r in P9['trials']} - {None}) or None),
        'PhysNineDeployTrials': ('Pixel 9 valid/attempted callback trials', kn(sum(z['valid'] for z in P9['deploy'].values()), sum(z['attempted'] for z in P9['deploy'].values())) if P9['deploy'] else None),
        'PhysNineBgMedian': ('Pixel 9 Contacts background unfrozen median callback delay', n9('contacts', 'bg_unfrozen')),
        'PhysNineFgMedian': ('Pixel 9 Contacts FGS median callback delay', n9('contacts', 'fg')),
        'PhysNineAssistMedian': ('Pixel 9 Contacts bound assistant median callback delay', n9('contacts', 'assistant')),
        'PhysNineMediaBgMedian': ('Pixel 9 MediaStore background unfrozen median callback delay', n9('media', 'bg_unfrozen')),
        'PhysNineMediaFgMedian': ('Pixel 9 MediaStore FGS median callback delay', n9('media', 'fg')),
        'PhysNineFrozen': ('Pixel 9 background frozen Contacts trials valid (frozen before and during the hold) / attempted', kn(nfz['valid'], nfz['attempted']) if nfz else None),
        'PhysNineFrozenBeforeThaw': ('Pixel 9 frozen trials with a callback before thaw / valid', kn(nfz['before_thaw'], nfz['valid']) if nfz and nfz['valid'] else None),
        'PhysNineNoDelay': ('Pixel 9 Contacts first callbacks with NOTIFY_NO_DELAY / Contacts first callbacks', nd(P9['deploy'], 'contacts')),
        'PhysNineRaceStampedStale': ('Pixel 9 race: stale FRESH / updates and inserts on certifying sources', rk(P9['race_kinds'], 'stamped')),
        'PhysNineRaceSameAsPixel': ('Pixel 9 race trials with the Pixel 8 outcome of the same source, trial and seed / matched', kn(*P9['same']) if P9['same'][1] else None),
        'PhysNineProbeFrozenS': ('Pixel 9 freezer probe: frozen after, s', '%.1f' % P9['probe_s'] if P9['probe_s'] is not None else None),
        # Pixel 8a, Android 17 (phys-*-pixel8aa17-*, b13-pixel8aa17-b0-*): cost, scale, FGS cost, unbatched host, long Doze, B10
        'PhysEightAModel': ('Pixel 8a model', tex(', '.join(sorted({r['device'].split(' ', 1)[-1] for r in A8['tests'] if r.get('device')})) or None)),
        'PhysEightABuild': ('Pixel 8a build IDs', ', '.join('\\path{%s}' % b for b in build_ids(A8['tests']).split(', ')) if A8['tests'] else None),
        'PhysEightAAndroid': ('Pixel 8a Android release and SDK level', A8['android']),
        'PhysEightAUnits': ('Pixel 8a units behind the reported tests', A8['units'] or None),
        'PhysEightACostDecisions': ('Pixel 8a per-source cost decisions', A8['cost_n'] or None),
        **{'PhysEightACost%s%s' % (s.title(), k): ('Pixel 8a %s: median ms, %s' % (s, w), f1(C8[s][key]) if s in C8 else None) for s in COST_SRC
           for k, key, w in (('Refresh', 'refresh', 'refresh of one fact'), ('Stamp', 'unchanged', 'StampCheck, source unchanged'),
                             ('StampChanged', 'changed', 'StampCheck after the source changed'))},
        **{'PhysEightAScale%s%s' % (sfx, k): ('Pixel 8a scale level %s: %s' % (L, w), sl(L, key)) for L, sfx in SCALE.items()
           for k, key, w in (('Vc', 'vc', 'Contacts StampCheck, unchanged, ms'), ('Vcc', 'vcc', 'Contacts StampCheck after a change, ms'),
                             ('Rc', 'rc', 'refresh of the 3 Contacts facts, ms'), ('Vm', 'vm', 'MediaStore StampCheck, unchanged, ms'),
                             ('Vmc', 'vmc', 'MediaStore StampCheck after a change, ms'), ('Rm', 'rm', 'refresh of the 2 media facts, ms'))},
        # check-to-effect medians are whole or half ms (medians of whole ms)
        **{'PhysEightAScale%sCte' % sfx: ('Pixel 8a scale level %s: median check-to-effect, ms' % L, '%g' % lv8[L]['cte'] if L in lv8 and lv8[L]['cte'] is not None else None)
           for L, sfx in SCALE.items()},
        **{'PhysEightAScale%s%s' % (sfx, k): ('Pixel 8a scale level %s: %s' % (L, key), '{:,}'.format(lv8[L][key]).replace(',', '{,}') if L in lv8 else None)
           for L, sfx in SCALE.items() for k, key in (('Raw', 'raw'), ('Img', 'img'))},
        'PhysEightAScaleCteSlope': ('Pixel 8a: check-to-effect fit over the Contacts levels, ms per 1,000 raw contacts', '%.1f' % fit8['slope'] if fit8 else None),
        'PhysEightAScaleCteIntercept': ('Pixel 8a: that fit, intercept ms', '%.1f' % fit8['intercept'] if fit8 else None),
        'PhysEightAScaleCteRsq': ('Pixel 8a: that fit, R squared', '%.2f' % fit8['rsq'] if fit8 else None),
        'PhysEightAScaleCteN': ('Pixel 8a: that fit, boundary trials', fit8['n'] if fit8 else None),
        **{'PhysEightA%s%s' % (m.title(), k): ('Pixel 8a %s windows: %s' % (m, w), fn(FG8[m]) if m in FG8 else None) for m in ('bg', 'fg')
           for k, w, fn in (('Cpu', 'median CPU s per window', lambda z: '%.2f' % z['cpu_s']), ('Pss', 'median PSS, MB', lambda z: '%.1f' % z['pss_mb']),
                            ('Power', 'BatteryStats estimate, median over the windows that list the UID, mAh', lambda z: sci(z['power']) if z['power'] is not None else 'not listed'),
                            ('Listed', 'windows that list the UID / windows', lambda z: kn(z['listed'], z['n'])), ('Windows', 'windows', lambda z: z['n']),
                            ('Adj', 'oom_score_adj', lambda z: span(z['adj'])))},
        'PhysEightAFgWindowS': ('Pixel 8a FGS cost: median window, s', '%.0f' % st.median(z['window_s'] for z in FG8.values()) if FG8 else None),
        'PhysEightAFgChanges': ('Pixel 8a FGS cost: changes per window, median', '%.0f' % st.median(z['changes'] for z in FG8.values()) if FG8 else None),
        'PhysEightAHostN': ('Pixel 8a unbatched host decisions', H8.get('n')),
        'PhysEightAHostFacts': ('Pixel 8a unbatched host: facts per decision', H8.get('facts')),
        'PhysEightAHostGlS': ('Pixel 8a unbatched host: median s to re-read every fact', '%.1f' % (H8['gl'] / 1000) if H8 else None),
        'PhysEightAHostEvS': ('Pixel 8a unbatched host: median s to check watermarks and re-read the rest', '%.1f' % (H8['ev'] / 1000) if H8 else None),
        'PhysEightAHostRatio': ('Pixel 8a unbatched host: ratio of those medians (StampCheck / global)', '%.2f' % H8['ratio'] if H8 else None),
        'PhysEightAHostReread': ('Pixel 8a unbatched host: median facts re-read by StampCheck', '%g' % H8['reread_med'] if H8 else None),
        'PhysEightAHostChanged': ('Pixel 8a unbatched host: changed facts', H8['changed'] if H8 else None),
        'PhysEightAHostMissed': ('Pixel 8a unbatched host: changed facts StampCheck missed / changed facts', kn(H8['missed'], H8['changed']) if H8 else None),
        'PhysEightAHostQueryS': ('Pixel 8a unbatched host: median adb time of one content query, s', '%.1f' % (H8['query_ms'] / 1000) if H8 else None),
        'PhysEightADozeTrials': ('Pixel 8a verified long Doze: valid / attempted trials', kn(DZ8['n'], DZ8['att']) if DZ8 else None),
        'PhysEightADozeUnits': ('Pixel 8a verified long Doze: units', DZ8.get('units')),
        'PhysEightADozeSurvived': ('Pixel 8a verified long Doze: process survived / valid trials', kn(DZ8['survived'], DZ8['n']) if DZ8.get('n') else None),
        'PhysEightADozeFclMin': ('Pixel 8a verified long Doze: earliest first callback, s', '%.2f' % min(DZ8['fcl']) if DZ8.get('fcl') else None),
        'PhysEightADozeFclMax': ('Pixel 8a verified long Doze: latest first callback, s', '%.2f' % max(DZ8['fcl']) if DZ8.get('fcl') else None),
        'PhysEightADozeSpanMin': ('Pixel 8a verified long Doze: shortest Doze span, min', '%.1f' % DZ8['span_min'] if DZ8.get('span_min') is not None else None),
        **{'PhysEightADoze%s%s' % (p.title(), ph.title()): ('Pixel 8a verified long Doze, %s decision: %s missed/changed uses' % (ph, p), dz(ph, p))
           for ph in ('early', 'late') for p in ('ev', 'evr', 'lm')},
        'PhysEightAMtimeSame': ('Pixel 8a same-second mtime trials', pf8('mtime')),
        'PhysEightAClockTrials': ('Pixel 8a valid clock set-back trials', PF8['clock'][1] if PF8 and PF8['clock'][1] else None),
        'PhysEightAClockStale': ('Pixel 8a clock set-back: stale number accepted/trials', pf8('clock')),
        'PhysEightAClockTsTransientStale': ('Pixel 8a clock, transient: timestamp StampCheck accepted the stale number/trials', pf8('clock_ts')),
        'PhysEightAClockTsPersistentGuard': ('Pixel 8a clock, persistent: clock guard raised/trials', pf8('clock_guard')),
        'PhysEightASmsValid': ('Pixel 8a SMS id reuse: valid / attempted trials (failed, excluded from every number)', kn(*A8['sms']) if A8['sms'][1] else None),
        'PhysSamsungRaceSameAsPixel': ('S25 race trials with the Pixel 8 outcome of the same source, trial and seed / matched trials',
                                       kn(*R['s25']['same']) if R['s25']['same'][1] else None),
        'PhysSamsungFrozen': ('S25 freezer attempts, client cached and freezer on: frozen / attempts', kn(*sf[:2]) if sf[1] else None),
        'PhysSamsungFreezeWindowS': ('S25 shortest time a counted freezer attempt was watched, s', '%.0f' % sf[2] if sf[1] and sf[2] is not None else None),
        'PhysSamsungFreezeDebounceS': ('S25 freezer debounce set for those attempts, s', '%g' % sf[3] if sf[1] and sf[3] is not None else None),
        'PhysFreezerProbeFrozen': ('Pixel 8, same attempts: frozen / attempts', kn(*pf_[:2]) if pf_[1] else None),
        # host helper reads (Table tab_phys_host)
        'PhysHostTransportMin': ('B6 smallest per-arm median adb transport (host round trip minus on-device time), ms',
                                 '%.1f' % min(t for z in HO.values() for t in z['transport'].values()) if HO and any(z['transport'] for z in HO.values()) else None),
        'PhysHostTransportMax': ('B6 largest per-arm median adb transport, ms',
                                 '%.1f' % max(t for z in HO.values() for t in z['transport'].values()) if HO and any(z['transport'] for z in HO.values()) else None),
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
        'PhysRaceStampedStale': ('race: stale FRESH / updates and inserts on certifying sources', rk(R['race_kinds'], 'stamped')),
        'PhysRaceMediaStampedStale': ('race, MediaStore only: stale FRESH / updates and inserts',
                                      (lambda z: kn(sum(z['k'][k][0] for k in ('update', 'insert') if k in z['k']), sum(z['k'][k][1] for k in ('update', 'insert') if k in z['k']))
                                       if any(k in z['k'] for k in ('update', 'insert')) else None)(R['race_kinds']['src']['media']) if 'media' in R['race_kinds']['src'] else None),
        'PhysRaceDeletesCaught':('race: deletes caught (no stale FRESH) / deletes on certifying sources', rk(R['race_kinds'], 'deletes')),
        'PhysRaceStamplessUnknown': ('race: trials with UNKNOWN on every own fact / trials of sources StampCheck never certified', rk(R['race_kinds'], 'stampless')),
        'PhysRaceEmuStampedStale': ('emulators, same rule as PhysRaceStampedStale', rk(R['emu']['race'], 'stamped')),
        'PhysEmuNoDelay': ('emulators: Contacts first callbacks with NOTIFY_NO_DELAY / Contacts first callbacks', nd(R['emu']['deploy'], 'contacts')),
        'PhysEmuFrozen': ('emulators: background frozen Contacts trials valid (frozen before and during the hold) / attempted',
                          (lambda z: kn(z['valid'], z['attempted']) if z else None)(R['emu']['deploy'].get(('contacts', 'bg_freezer')))),
        'PhysBoundaryTrials': ('B9 valid boundary trials', BD.get('n')),
        'PhysCteMs': ('B9 median check-to-effect interval, ms', f"{st.median(BD['cte']):.1f}" if BD.get('cte') else None),
        'PhysCteMsInt': ('B9 median check-to-effect interval, whole ms', f"{st.median(BD['cte']):.0f}" if BD.get('cte') else None),
        'PhysBndObsStale': ('B9 observation check, change before the action: stale/n', bk('obs', 'before_action')),
        'PhysBndBeforeCheckStale': ('B9 boundary check, change before the check: stale/n', bk('bnd', 'before_check')),
        'PhysBndOverlapStale': ('B9 boundary check, change overlaps check or residual: stale/n', bk('bnd', 'overlaps')),
        **{'PhysBndOverlapWall' + w.title()[:5]: ('B9 overlap trials by the number at the effect time: %s' % w, BD['wall_at'][('bnd', 'overlaps', w)] if BD and BD['wall_at'] else None)
           for w in ('stale', 'fresh', 'undetermined')},
        'PhysBndBandTrials': ('B9 trials whose change was drawn in the band around the check', len(BD['band']) if BD and BD['band'] else None),
        'PhysBndBandMin': ('B9 smallest planned band offset from the check, ms', '$%.1f$' % min(BD['band']) if BD and BD['band'] else None),
        'PhysBndBandMax': ('B9 largest planned band offset from the check, ms', '$%.1f$' % max(BD['band']) if BD and BD['band'] else None),
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
    tr = [t for z in HO.values() for t in z['transport'].values()]
    return (' Write cases alternated trial by trial on %s unit%s and arm order was randomized, so the differences between write cases'
            ' are not an order, warm-up or unit effect. On device and adb (refresh / \\stamp): median time of the batch on the phone, and'
            ' median host round trip minus that time%s, so the differences between arms and between write cases arise on the phone;'
            ' the cause of the write-case differences was not measured.'
            % ({1: 'one'}.get(units, units), 's' if units > 1 else '', ', from %.1f to %.1f\\,ms in every arm and case' % (min(tr), max(tr)) if tr else ''))


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

    K, rows = R['race_kinds'], []
    for cert, head in ((True, 'Sources whose stamp certified'), (False, 'Sources whose stamp never certified (\\stamp: \\Unknown)')):
        src = sorted(x for x, z in K['src'].items() if z['cert'] == cert and x not in NOT_RUN)
        rows += [r'\mgroup{5}{%s}' % head] if src else []
        for x in src:
            z = K['src'][x]
            note = '' if cert else ' (%s)' % ', '.join(sorted(REASON.get(w, str(w)) for w in z['why']))
            rows.append(f"{SRCNAME.get(x, x)}{note} & " + ' & '.join(kn(*z['k'][k]) if k in z['k'] else 'n/a' for k in KINDS)
                        + f" & {R['race'][x]['unknown']}/{R['race'][x]['n']}\\\\")
    table(gen, 'tab_phys_race.tex', 'Pixel~8: a separate app writes once between the optimistic anchor\\textquoteright s fact read and its watermark assignment.'
          ' Write columns: trials whose anchor certified the changed value as \\Fresh, out of trials with that write; last column: trials in which'
          ' strict \\sys returned \\Unknown. The write schedule is seeded and deterministic (writes cycle through update, delete and insert;'
          ' Settings only updates), so each cell is a fixed outcome of source and write kind: the counts are counterexamples, not frequencies.'
          ' Every update or insert to a source whose stamp certified gave stale \\Fresh (\\PhysRaceStampedStale), every delete there was caught'
          ' (\\PhysRaceDeletesCaught), and \\stamp returned \\Unknown for every trial of the other sources (\\PhysRaceStamplessUnknown).',
          'lrrrr', r'Source & Update & Insert & Delete & \Unknown', rows, 'B4 race trials',
          extra=[r'%s & \multicolumn{4}{l}{%s}\\' % (SRCNAME[x], NR) for x in sorted(NOT_RUN)])

    BD, rows, store = R['boundary'], [], ''
    if BD:
        store = ' The effect is %s.' % ' or '.join(sorted({'contacts': "a Data row of a separate raw contact, not Dana's",
                                                         'calllog': 'a call-log row'}[s] for s in BD['stores']))
        store += " Overlaps: the change overlaps the check or the check-to-effect interval. Stale: the value used differs from Dana's number read right after the effect, as in Table~\\ref{tab:boundary}."
        if BD['wall']:
            store += (" Last column, a second reading: the number in the effect row against Dana's number at the effect's wall-clock time,"
                      " as stale/fresh/undetermined; undetermined: a change spans or ends at that time, so Dana's number at that instant is unknown.")
        if BD['band']:
            store += (' Rates depend on where the changes were injected: %d trial%s drew the change in a band around the check (planned'
                      ' offsets from $%.1f$ to $%.1f$\\,ms), the others over the whole planning window.'
                      % (len(BD['band']), 's' * (len(BD['band']) != 1), min(BD['band']), max(BD['band'])))
        wall_at = lambda m, w: '/'.join(str(BD['wall_at'][m, w, c]) for c in ('stale', 'fresh', 'undetermined')) if any(BD['wall_at'][m, w, c] for c in ('stale', 'fresh', 'undetermined')) else 'n/a'
        for lab, m, w in [('observation check; change before action', 'obs', 'before_action'), ('boundary check; change before check', 'bnd', 'before_check'),
                          ('boundary check; change overlaps', 'bnd', 'overlaps'), ('boundary check; change after effect', 'bnd', 'after_effect'),
                          ('boundary check; no change (control)', 'bnd', 'none'), ('observation check; no change (control)', 'obs', 'none')]:
            rows.append(f"{lab} & {kn(*BD['k'](m, w))} & {wall_at(m, w)}\\\\")
        rows += [f"change starts within 10\\,ms of check & {kn(*BD['bins']['near'])} & n/a\\\\", f"change starts 10 to 60\\,ms after check & {kn(*BD['bins']['late'])} & n/a\\\\"]
        rows += [f"excluded: {w} & {c} & \\\\" for w, c in sorted(BD['excluded'].items())]
    table(gen, 'tab_phys_boundary.tex', 'Pixel~8: stale effects by where the change landed relative to the boundary check and the effect (stale/trials); median check-to-effect interval \\PhysCteMs\\,ms.' + store,
          'lrr', "Placement of the change & Stale & At effect time", rows, 'B9 boundary trials')

    PF, rows = R['pitfalls'], []
    if PF:
        cell = lambda k: wil(*PF[k]) if PF[k][1] else r'\PhysTBD{B10 %s trials}' % k     # no trials of that kind yet
        rows = [f"SMS \\texttt{{\\_id}} reused & {NR if 'sms' in NOT_RUN else cell('sms')}\\\\", f"same-second append keeps mtime & {cell('mtime')}\\\\",
                'clock back 1\\,h: versions keep old number & ' + (wil(*PF['clock']) if PF['clock'][1] else 'not run on this phone') + r'\\']
        if PF['clock_ts'][1]:
            rows.append('same, timestamps, clock restored & %s\\\\' % wil(*PF['clock_ts']))
    A8 = R['p8a']; P8, sms = A8['pitfalls'], A8['sms']
    two = bool(rows and (P8 or sms[1]))          # a Pixel 8a column next to the Pixel 8 one, same rules; its SMS part only says it failed
    if two:
        c8 = lambda k: wil(*P8[k]) if P8 and P8[k][1] else 'n/a'
        sc = ('failed (%s valid)' if sms[0] == 0 else 'excluded (%s valid)') % kn(*sms) if sms[1] else 'not run on phone'
        rows = ['%s & %s\\\\' % (r[:-2], c) for r, c in zip(rows, (sc, c8('mtime'), c8('clock'), c8('clock_ts')))]
    table(gen, 'tab_phys_pitfalls.tex', ('Pixel~8 (Android~15) and Pixel~8a (Android~17)' if two else 'Pixel~8') + ': evidence pitfalls, trials affected out of trials (Wilson 95\\% interval).'
          + (' On the Pixel~8a the SMS writes were dropped although the writer held the SMS role, so that test failed and gives no number.' if two and sms[1] and sms[0] == 0 else ''),
          'lrr' if two else 'lr', 'Pitfall & Pixel~8 & Pixel~8a' if two else 'Pitfall & Trials affected', rows, 'B10 pitfall trials',
          extra=[r'SMS \texttt{\_id} reuse & %s\\' % NR] if 'sms' in NOT_RUN and not PF else [], font='\\scriptsize' if two else '')   # two columns fit the column only so

    F, rows = R['frozen'], []
    if F.get('valid'):
        rows = [f'Holds valid/run & {F["valid"]}/{F["run"]}\\\\', f'Stayed frozen & {F["stayed"]}\\\\', f'Killed & {F["died"]}\\\\', f'Changes & {F["changes"]}\\\\',
                f'Hold $\\geq$ (min) & {F["hold_min"]:.1f}\\\\', f'Lost sources & {F["lost"]}/{F["src"]}\\\\', f'Unseen last & {F["unseen"]}/{F["src"]}\\\\',
                f'Callbacks & {F["callbacks"]}\\\\', 'Restart-aware miss & %d/%d/%d\\\\' % tuple(F['evr'])]
    table(gen, 'tab_phys_frozen.tex', 'Pixel~8: long frozen holds, same metrics as Table~\\ref{tab:frozen}; lost and unseen sources count holds that stayed frozen; last row: changed uses missed by restart-aware event-only at +2/+14/+120\\,s.' + why(F.get('excluded'), 'holds'),
          'lr', 'Metric & Phone', rows, 'B5 frozen holds')

    HO = R['host']
    rows = [f"{c} & {z['n']} & {z['refresh']:.1f} & {z['stamp']:.1f} & {'%.1f' % z['relay'] if z['relay'] is not None else 'n/a'} & "
            f"{'%.1f [%.1f, %.1f]' % z['gain']} & {z['reads'][0]:.1f} / {z['reads'][1]:.1f} & "
            + ' & '.join(' / '.join('%.1f' % z[k][a] for a in ('refresh', 'stamp')) if all(a in z[k] for a in ('refresh', 'stamp')) else 'n/a' for k in ('dev', 'transport'))
            + '\\\\' for c, z in HO.items()]
    table(gen, 'tab_phys_host.tex', 'Pixel~8: matched host helper with a batched \\stamp arm; median batch latency in milliseconds, paired mean of refresh minus \\stamp with trial-bootstrap 95\\% CI, and facts read per batch (refresh / \\stamp); \\stamp re-reads only the facts its stamps do not confirm.' + host_note(HO, R['host_order']),
          'lrrrrrrrr', r'Writes & Trials & Refresh & \stamp & Relay & Refresh $-$ \stamp [CI] & Reads & On device & adb', rows, 'B6 host trials', star=True)
    CT = R['continuous']
    rows = [f"{a} & {c['fresh']} & {c['stale_at_certification']} & {c['stale_at_action_only']} & {c['ambiguous']}\\\\" for a, c in sorted(CT.items())]
    table(gen, 'tab_phys_continuous.tex', 'Pixel~8: continuous writes to Dana\\textquoteright s number while each arm certifies and then acts. Each arm trial is judged by the true number, from the writer\\textquoteright s timestamps, at two instants: certification (end of the arm\\textquoteright s read batch) and action (start of its effect). Stale at cert.: the value used differs from the number at certification; for refresh, a write committed between its read and the end of the batch. Stale at action: right at certification, wrong at the action. Ambiguous: an instant falls inside a write\\textquoteright s commit window (from the write call to its completion), where the true number is undefined.',
          'lrrrr', 'Arm & Fresh & Stale at cert. & Stale at action & Ambiguous', rows, 'B7 continuous trials')

    rows = ['%s & \\path{%s} & \\path{%s} & %s & %s\\\\' % r for r in R['units']]
    table(gen, 'tab_phys_units.tex', 'Pixel~8 trials per unit (\\texttt{device\\_instance}) and build, each test with the rules of its own table'
          ' (Tables~\\ref{tab:phys-deploy}, \\ref{tab:phys-gaps}, \\ref{tab:phys-race}, \\ref{tab:phys-host} and \\ref{tab:phys-boundary}). Gaps: first-callback'
          ' median over the no-gap, Doze and bucket gaps (deferred) and over the freezer gap; event-only misses at +14\\,s over the gaps that end'
          ' observer coverage (lost). Host helper: paired mean per write case. n/a: no valid trial. Every unit behind a reported trial has a row (%s units).'
          % len({r[1] for r in R['units']}),
          'lllr>{\\raggedright\\arraybackslash}p{7.5cm}', 'Test & Unit & Build & Trials & Per-unit result', rows, 'per-unit trials', star=True, font='\\footnotesize')

    S, P9, rows = R['s25'], R['p9'], []
    if S['trials'] or P9['trials']:
        B1, B9, P = S['deploy'], P9['deploy'], R['deploy']
        cell = lambda D, k: (lambda z: '%s (%s)' % (dur(st.median(z['delays_ms'])), kn(z['valid'], z['attempted'])) if z['delays_ms'] else
                             ('held (%s)' if k[1] == 'bg_freezer' and z['valid'] else 'n/a (%s)') % kn(z['valid'], z['attempted']))(D[k]) if k in D else 'not run'
        for src in SOURCES:
            for mode in NAMES:
                if (src, mode) in B1 or (src, mode) in B9:
                    rows.append('%s, %s & %s & %s & %s\\\\' % (SOURCES[src], MODE[mode], cell(B1, (src, mode)), cell(B9, (src, mode)), cell(P, (src, mode))))
        nd = lambda D, s: kn(*nodelay(D, s)) if nodelay(D, s)[1] else 'n/a'
        rows += ['%s, no-delay flag & %s & %s & %s\\\\' % (SOURCES[s], nd(B1, s), nd(B9, s), nd(P, s)) for s in SOURCES if nodelay(B1, s)[1] or nodelay(B9, s)[1]]
        rk = lambda K: kn(*K['stamped']) if K['stamped'][1] else 'n/a'
        rows.append('Race: update, insert stale & %s & %s & %s\\\\' % (rk(S['race_kinds']), rk(P9['race_kinds']), rk(R['race_kinds'])))
        fz = lambda f: kn(*f[:2]) if f[1] else 'n/a'
        rows.append('Freezer probe, client frozen & %s & %s & %s\\\\' % (fz(S['froze']), fz(P9['froze']), fz(R['phone_froze'])))
        rows.append('Freezer off as provisioned (units with trials) & \\PhysSamsungFreezerOffTrialUnits & n/a & \\PhysFreezerOffTrialUnits\\\\')   # as tab:phone-results
    ps, adj = proc_states(S['deploy'].get(('contacts', 'bg_unfrozen'), {}).get('rows', []))
    bg = (' In every S25 background Contacts trial the client was cached (process state %s, \\texttt{oom\\_adj} %s) and unfrozen at every sample.'
          % (' or '.join(sorted(ps)), ' or '.join(sorted(adj)))) if ps and adj else ''
    ident = lambda T: ' (%s, build \\texttt{%s})' % (tex(T[0]['device'].split(' ', 1)[-1]), tex(build_ids(T))) if T else ''   # no \path in a caption
    table(gen, 'tab_phys_samsung.tex', 'Galaxy~S25' + ident(S['trials']) + ', Android~15, and Pixel~9' + (' (build \\texttt{%s})' % tex(build_ids(P9['trials'])) if P9['trials'] else '') + ', Android~16, against Pixel~8,'
          ' with the rules of Tables~\\ref{tab:phys-deploy} and~\\ref{tab:phys-race}; callbacks: median delay (valid/attempted trials). No-delay flag: the'
          ' callback\\textquoteright s flags carry \\texttt{ContentResolver}\\textquoteright s hidden \\texttt{NOTIFY\\_NO\\_DELAY} bit, with which'
          ' \\texttt{ContentService} skips the 10\\,s background deferral.' + bg + ' Freezer probe: probe and diagnosis attempts with the client cached,'
          ' \\PhysSamsungFreezeDebounceS\\,s debounce (S25: each watched for at least \\PhysSamsungFreezeWindowS\\,s). Freezer off: Android~16 no longer'
          ' prints the setting; the Pixel~9 frozen trials show it on.'
          + (' The race uses the same seeded write schedule on every model; the S25 (\\PhysSamsungRaceSameAsPixel) and the Pixel~9'
             ' (\\PhysNineRaceSameAsPixel) matched the Pixel~8 trial by trial, by source, trial and seed: reproducibility, not independent rates.' if S['same'][1] else '')
          + (' A stopped partial S25 race run (%d trial%s whose seeds repeat the full run) is excluded.' % (S['partial'], 's' * (S['partial'] != 1)) if S['partial'] else ''),
          'lrrr', 'Measure & Galaxy~S25 & Pixel~9 & Pixel~8', rows, 'other-model trials', star=True)

    G25, B25, FL, LG, SO, rows = S['gaps'], S['boundary'], S['flags'], S['long'], S['screen'], []
    if G25:
        rows.append(r'\mgroup{2}{Gaps (background client, late decision; \PhysSamsungGapUnits units, %s trials)}' % kn(sum(z['n'] for z in G25.values()), sum(z['att'] for z in G25.values())))
        for g, z in G25.items():
            m = lambda p_: kn(*z['miss']['late', p_]) if z['miss']['late', p_] else 'n/a'
            rows.append('%s & missed: event-only %s, restart-aware %s, \\stamp %s\\\\' % (GAPNAME.get(g, g), m('ev'), m('evr'), m('lm')))
    if B25:
        wall = lambda m_, w: '/'.join(str(B25['wall_at'][m_, w, c]) for c in ('stale', 'fresh', 'undetermined'))
        rows.append(r'\mgroup{2}{Action boundary (one unit; %d boundary-check changes over the planning window, %d in the band)}' % (S['bnd_changes'], len(B25['band'])))
        rows += ['observation check; change before action & stale %s\\\\' % kn(*B25['k']('obs', 'before_action')),
                 'boundary check; change before check & stale %s\\\\' % kn(*B25['k']('bnd', 'before_check')),
                 'boundary check; change overlaps & stale %s; at effect time %s (stale/fresh/undet.)\\\\' % (kn(*B25['k']('bnd', 'overlaps')), wall('bnd', 'overlaps')),
                 'check-to-effect, median & %.1f\\,ms (%d trials)\\\\' % (st.median(B25['cte']), len(B25['cte']))]
    if FL:
        rows.append(r'\mgroup{2}{Who sets the no-delay flag (one unit, %d cases, %d trials each)}' % (FL['cases'], FL['per_case']))
        rows += ['write through the Contacts provider (app or shell) & flagged %s\\\\' % kn(*FL['writes'][:2]),
                 'app\\textquoteright s own notifyChange on the Contacts URI & flagged %s; flags as passed %s; median %s\\\\' % (kn(*FL['notify'][:2]), kn(*FL['kept']), dur(FL['notify'][2])),
                 'Calendar, MediaStore, Settings writes; Calendar notifyChange & flagged %s\\\\' % kn(*FL['other'][:2])]
    if S['cflags'][0][1]:
        rows.append('every logged Contacts callback after a write through the provider & flagged %s, on %d units and %d builds\\\\'
                    % (kn(*S['cflags'][0]), len(S['cflags'][1]), len(S['cflags'][2])))
    if LG:
        rows.append(r'\mgroup{2}{Long freezer window (one unit, %d samples; phases ran in this order on one process, so C and D start where B left it)}' % LG['n'])
        rows.append('frozen by Android (isFrozen or cgroup v2), all phases & %s samples\\\\' % kn(LG['android_frozen'], LG['n']))
        for i, ph in enumerate(LG['phases']):   # phases ran in this order on the same process, so later phases inherit earlier ones
            lab = '%s: screen %s%s' % ('ABCDEFGH'[i], 'off' if ph['off'] else 'on', ', battery saver' if ph['saver'] else '') + (', cached' if i == 0 else '')
            res = ('%.0f\\,s, in \\texttt{/frozen} %s samples' % (ph['secs'], kn(ph['in_v1'], ph['n'])) + (' (first at %.0f\\,s)' % ph['first_v1'] if ph['in_v1'] and i and not LG['phases'][i - 1]['in_v1'] else '')
                   + ('; /proc state R in %s there' % kn(ph['running'], ph['in_v1']) if ph['in_v1'] else ''))
            rows.append('%s & %s\\\\' % (lab, res))
    if SO:
        rows.append(r'\mgroup{2}{Screen off, freshly started client (one unit, %d trials)}' % SO['n'])
        rows += ['in \\texttt{/frozen} when the change was written & %s\\\\' % kn(SO['at_write'], SO['n']),
                 'entered \\texttt{/frozen} with the screen off & %s, from %.0f to %.0f\\,s after screen off\\\\' % (kn(len(SO['later']), SO['n']), min(SO['later']), max(SO['later'])) if SO['later']
                 else 'entered \\texttt{/frozen} with the screen off & 0/%d\\\\' % SO['n'],
                 'Contacts and MediaStore callbacks before wake & %s\\\\' % kn(SO['callbacks'], SO['n'])]
    table(gen, 'tab_phys_s25.tex', 'Galaxy~S25, tests beyond callbacks and race, each on the unit and sample size given (no generalization beyond them).'
          ' Gaps and boundary use the rules of Tables~\\ref{tab:phys-gaps} and~\\ref{tab:phys-boundary}. Flag probe: first callback after a write'
          ' through a provider, or after an app\\textquoteright s own \\texttt{notifyChange} on the same URI. Long window and screen off: Android\\textquoteright s'
          ' freezer (\\texttt{isFrozen}, cgroup v2) against Samsung\\textquoteright s cgroup v1 freezer group \\texttt{/frozen}; whether that group holds'
          ' callbacks was not tested.',
          'l>{\\raggedright\\arraybackslash}p{9.5cm}', 'Test & Result', rows, 'S25 tests', star=True)

    # Pixel 8a, Android 17: the tests that had emulator results only (the pitfalls column is in tab_phys_pitfalls)
    A8, rows = R['p8a'], []
    C8, FG8, H8, DZ8 = (A8[k] for k in ('cost', 'fg', 'host', 'doze'))
    EMU = {'contacts': ('Contacts', True), 'media': ('Media', True), 'calendar': ('Calendar', False), 'settings': ('Settings', False), 'files': ('Files', True)}
    if C8:
        rows.append(r'\mgroup{2}{Per-use cost (one unit, %d decisions; each round changes one source or none; median ms; emulator: Table~\ref{tab:cost})}' % A8['cost_n'])
        for s, z in C8.items():
            e, val = EMU[s]
            sc = ('\\stamp %.1f unchanged, %.1f after a change' % (z['unchanged'], z['changed']) if z['stamp'] else
                  '\\stamp answers \\Unknown (no stamp) in %.1f' % max(z['unchanged'], z['changed']))
            rows.append('%s & refresh of one fact %.1f; %s; emulator: refresh \\CostRef%s%s\\\\' % (SRCNAME[s], z['refresh'], sc, e, ', validate \\CostVal%s' % e if val else ''))
    if FG8:
        rows.append(r'\mgroup{2}{Foreground-service cost (one unit, %s windows of %.0f\,s with %.0f changes each; medians; Table~\ref{tab:fgcost})}'
                    % (' and '.join(str(z['n']) for z in FG8.values()), st.median(z['window_s'] for z in FG8.values()), st.median(z['changes'] for z in FG8.values())))
        for m, nm in (('bg', 'Background (cached)'), ('fg', 'Foreground service')):
            if m in FG8:
                z = FG8[m]
                rows.append('%s & CPU %.2f\\,s, PSS %.1f\\,MB, \\texttt{oom\\_score\\_adj} %s; BatteryStats estimate %s (listed in %s windows)\\\\'
                            % (nm, z['cpu_s'], z['pss_mb'], span(z['adj']), sci(z['power']) + '\\,mAh' if z['power'] is not None else 'not listed', kn(z['listed'], z['n'])))
    if H8:
        rows.append(r'\mgroup{2}{Unbatched host agent over adb (one unit, %d decisions of %d facts; one adb call per read, median %.1f\,s per content query; Table~\ref{tab:host})}'
                    % (H8['n'], H8['facts'], H8['query_ms'] / 1000))
        for ch, nm in ((True, 'One change'), (False, 'No change')):
            if ch in H8['cases']:
                z = H8['cases'][ch]
                rows.append('%s (%d) & global %.1f\\,s, \\stamp %.1f\\,s (ratio %.2f, faster in %s); %.1f facts re-read (mean)%s\\\\'
                            % (nm, z['n'], z['gl'] / 1000, z['ev'] / 1000, z['ev'] / z['gl'], kn(z['faster'], z['n']), z['reread'],
                               '; changed facts missed %s' % kn(z['missed'], z['changed']) if z['changed'] else ''))
    if DZ8:
        rows.append(r'\mgroup{2}{Verified long Doze (%d units, %s valid trials; deep idle at both change batches, client cgroup not frozen at either; Table~\ref{tab:gaps})}'
                    % (DZ8['units'], kn(DZ8['n'], DZ8['att'])))
        if DZ8['n']:
            rows.append('Process and callbacks & survived %s; first callback from %.2f to %.2f\\,s; Doze held at least %.1f\\,min\\\\'
                        % (kn(DZ8['survived'], DZ8['n']), min(DZ8['fcl']), max(DZ8['fcl']), DZ8['span_min']))
            m = lambda ph, p: kn(*DZ8['miss'][ph, p]) if DZ8['miss'][ph, p] else 'n/a'
            rows += ['%s decision & missed: event-only %s, restart-aware %s, \\stamp %s\\\\' % (ph.title(), m(ph, 'ev'), m(ph, 'evr'), m(ph, 'lm')) for ph in ('early', 'late')]
    ident = (' (build \\texttt{%s})' % tex(build_ids(A8['tests']))) if A8['tests'] else ''
    table(gen, 'tab_phys_eighta.tex', 'Pixel~8a' + ident + ', Android~17, on a second Device Farm account: tests that had emulator results only, with the'
          ' rules of the emulator tables named in each block, each on the units and sample sizes given. BatteryStats gives estimates, and the phone stayed'
          ' plugged in. Host times are dominated by adb on Device Farm, so only the ratio compares with the emulator.',
          'l>{\\raggedright\\arraybackslash}p{12.6cm}', 'Test & Result', rows, 'Pixel 8a tests', star=True)

    SC8, rows = A8['scale'], []
    g = lambda x, fmt='%.1f': fmt % x if x is not None else 'n/a'
    for L, z in SC8.get('levels', {}).items():
        rows.append(' & '.join(['{:,}'.format(z['raw']).replace(',', '{,}'), '{:,}'.format(z['img']).replace(',', '{,}')]
                               + [g(z[k]) for k in ('vc', 'vcc', 'vts', 'rc', 'vm', 'vmc', 'rm')] + [g(z['cte'], '%g')]) + '\\\\')
    F, lv = SC8.get('fit'), list(SC8.get('levels', {}).values())
    table(gen, 'tab_phys_eighta_scale.tex', 'Pixel~8a, Android~17, one unit: cost versus source size with the columns and rules of Table~\\ref{tab:scale} (medians, ms)'
          + ('; per level %d decisions, half after a change, and %d boundary checks whose effect is a Contacts row' % (lv[0]['n'], lv[0]['acts']) if lv else '')
          + ('. A least-squares fit of check-to-effect on raw contacts over the %d boundary trials of the Contacts levels gives %.1f\\,ms per 1{,}000 raw contacts plus %.1f\\,ms ($R^2=%.2f$).'
             % (F['n'], F['slope'], F['intercept'], F['rsq']) if F else '.'),
          'rrrrrrrrrr', 'Raw contacts & Images & C.\\ val. & C.\\ val.\\,$\\Delta$ & C.\\ val.\\ TS & C.\\ refresh & M.\\ val. & M.\\ val.\\,$\\Delta$ & M.\\ refresh & Check$\\to$effect',
          rows, 'Pixel 8a scale', star=True, font='\\scriptsize')

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
    lines.append(r'\newif\ifPhysNine\PhysNine%s' % ('true' if any(z['valid'] for z in R['p9']['deploy'].values()) or R['p9']['race_kinds']['stamped'][1] else 'false'))
    lines.append(r'\newif\ifPhysEightA\PhysEightA%s' % ('true' if R['p8a']['tests'] else 'false'))     # any Pixel 8a test record
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
        assert len(tabs) == 16 and all(('\\PhysTBD{' in tab(t)) == (t not in dropped) for t in tabs), tabs
        assert '\\PhysEightAfalse' in tex and 'Pitfall & Trials affected' in tab('tab_phys_pitfalls.tex')
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
        st_ = lambda changed, kind='update', case='contacts', v='FRESH': {
            'case': case, 'mutation': {'kind': kind}, 'before': {'values': {'c.dana': 'A'}}, 'after': {'values': {'c.dana': 'B' if changed else 'A'}},
            'historical': {'verdicts': {'c.dana': v}, 'cost': {case: {'reason': 'unknown' if v == 'UNKNOWN' else 'wm_equal'}}}, 'repaired': {'c.dana': {'verdict': 'UNKNOWN'}}}
        add('stock', 'stock-X-1230.jsonl', st_(True), st_(False))
        # race by write kind: update and insert certified stale, a delete caught, a stampless source UNKNOWN; errors stay out
        K = race_kinds([st_(True), st_(True, 'insert'), st_(True, 'delete', v='CHANGED'), st_(True, 'update', 'calendar', 'UNKNOWN'), dict(st_(True), error='x')])
        assert (K['stamped'], K['deletes'], K['stampless']) == ((2, 2), (1, 1), (1, 1)) and K['src']['calendar']['why'] == {'unknown'}, K
        assert same_by_seed([dict(st_(True), trial=0, seed=1), dict(st_(False), trial=1, seed=1)],
                            [dict(st_(True), trial=0, seed=1), dict(st_(True), trial=1, seed=1), dict(st_(True), trial=2, seed=1)]) == (1, 2)
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
        D['s25_gaps'] = [dict(gap('kill', 8, None, 'A', 'REFRESH'), _file='b13-t-gaps-kill-0600.jsonl', device_instance='sG')]   # S25 test table
        D['s25_diag'] = [s25({'exp': 'freeze_diag', 'variant': x, 'froze': False, 'use_freezer': 'true', 'debounce_ms': 2000,
                              'samples': [{'t_s': 3.8, 'frozen': '0'}, {'t_s': 26.0 if x == 'b' else 9.0, 'frozen': '0'}]}, 'b13-t-diag-0600.jsonl') for x in 'ab']
        D['runlog'] = [{'run_arn': 'arn:run/s', 'device_instance': 'sA', 'use_freezer_before': 'false', 'use_freezer': 'true', '_file': 'RUNLOG.md'}]
        m, _ = write(D, gen); v = {k: x for k, (_, x) in m.items()}
        assert v['PhysSamsungBgMedian'] == '12\\,ms' and v['PhysSamsungMediaBgMedian'] == '10.0\\,s' and v['PhysSamsungNoDelay'] == '1/1' and v['PhysSamsungMediaNoDelay'] == '0/1'
        assert v['PhysSamsungGapLostEv'] == '1/1' and v['PhysSamsungGapUnits'] == 1 and 'Killed' in tab('tab_phys_s25.tex') and v['PhysGapTrials'] == '3/3', v['PhysSamsungGapLostEv']
        assert v['PhysSamsungRaceStampedStale'] == '1/1' and v['PhysRaceStampedStale'] == '1/2' and v['PhysRaceDeletesCaught'] is None, (v['PhysSamsungRaceStampedStale'], v['PhysRaceStampedStale'])
        assert v['PhysSamsungRaceTrials'] == 1 and v['PhysSamsungRaceStale'] == 1 and v['PhysSamsungFrozen'] == '0/1' and v['PhysSamsungFreezerOffUnits'] == '1/1', \
            (v['PhysSamsungRaceTrials'], v['PhysSamsungFrozen'], v['PhysSamsungFreezerOffUnits'])
        assert (v['PhysSamsungFreezeWindowS'], v['PhysSamsungFreezeDebounceS']) == ('26', '2'), 'window of the counted attempt b only (a keeps its FGS)'
        m, _ = write(dict(D, s25_b0=[s25({'probe': 'freezer_debounce_2s', 'ok': False, 'detail': {'frozen': '0', 'after_s': 25.1, 'debounce_get': '2000'}}, 'b13-t-b0-probe-0600.jsonl')]), gen)
        assert (m['PhysSamsungFrozen'][1], m['PhysSamsungFreezeWindowS'][1]) == ('0/2', '25'), 'the shortest watched attempt sets the window'
        assert v['PhysDevice'] == 'Pixel\\_X' and v['PhysInstances'] == 2 and v['PhysFreezerOffUnits'] is None and v['PhysDeployNoDelay'] == '0/2', 'S25 leaked into Pixel macros'
        assert v['PhysSamsungModel'] == 'SM-X' and v['PhysSamsungBuild'] == '\\path{S.1}' and '\\PhysSamsungtrue' in tab('physical_macros.tex')
        assert 'partial S25 race run (1 trial whose' in tab('tab_phys_samsung.tex') and 'Contacts, no-delay flag & 1/1 & n/a & 0/2' in tab('tab_phys_samsung.tex'), tab('tab_phys_samsung.tex')
        # per unit: no-gap trials on units A (10.0 s) and B (10.04 s), force-stop on a unit without device_instance
        assert v['PhysUnitsGap'] == 3 and (v['PhysUnitFclMin'], v['PhysUnitFclMax']) == ('10.00', '10.04') and v['PhysUnitsLostAll'] == '1/1', (v['PhysUnitsGap'], v['PhysUnitFclMin'])
        assert '\\path{arn:devinst/B} & \\path{?} & 1/1 & no gap: first cb. 10.04\\,s (deferred)' in tab('tab_phys_units.tex'), tab('tab_phys_units.tex')
        assert v['PhysHostReadsRefresh'] == '11.0' and v['PhysHostReadsStampMin'] == v['PhysHostReadsStampMax'] == '4.0'
        assert 'stale \\Fresh after 1/2 updates or inserts to stamped sources' in tab('tab_phys_units.tex'), 'per-unit race row in the stamped-write form'
        assert 'Freezer off as provisioned (units with trials) & \\PhysSamsungFreezerOffTrialUnits & n/a & \\PhysFreezerOffTrialUnits' in tab('tab_phys_samsung.tex')
        # Android 16 (Pixel 9): use_freezer is not printed ('?'); a frozen trial whose own cgroup samples show it frozen counts,
        # one with unfrozen samples does not; a b13-pixel9a16 file never reaches the Pixel 8 macros
        p9 = lambda frozen, **k: dict(dep('bg_freezer', frozen, None, 'contacts'), device='Google Pixel 9', fingerprint='google/t/t:16/BP2.1/1:user/release-keys',
                                      use_freezer='?', use_freezer_before='?', device_instance='n9', _file='b13-pixel9a16-deploy-contacts-0700.jsonl', **k)
        nine = dict(D, p9_deploy=[p9('1'), p9('0'), dep('fg', '0', 1054, 'contacts') | {'device': 'Google Pixel 9', 'device_instance': 'n9', '_file': 'b13-pixel9a16-deploy-contacts-0700.jsonl'}],
                    p9_stock=[dict(st_(True), trial=0, seed=1, device_instance='n9s', _file='b13-pixel9a16-stock-0700.jsonl')])
        m, _ = write(nine, gen); w = {k: x for k, (_, x) in m.items()}
        assert (w['PhysNineFrozen'], w['PhysNineFgMedian'], w['PhysNineModel'], w['PhysNineUnits'], w['PhysNineRaceStampedStale']) == ('1/2', '54\\,ms', 'Pixel 9', 2, '1/1'), w['PhysNineFrozen']
        assert w['PhysDeployFgMedian'] == v['PhysDeployFgMedian'] and w['PhysInstances'] == v['PhysInstances'] and '\\PhysNinetrue' in tab('physical_macros.tex')
        # S25 flag probe, long window and screen off
        fl = lambda case, src, writer, flags, d=10000: {'exp': 'notify_flags', 'case': case, 'source': src, 'writer': writer, 'first_flags': flags, 'first_delay_ms': d}
        F = flag_probe([fl('mut_contacts', 'contacts', 'mut', NO_DELAY | 1, 13), fl('notify_contacts_f1', 'contacts', 'notify', 1), fl('notify_contacts_f0', 'contacts', 'notify', 1),
                        fl('mut_media', 'media', 'mut', 9), dict(fl('mut_contacts', 'contacts', 'mut', 1), error='x')])
        assert (F['writes'][:2], F['notify'][:2], F['kept'], F['other'][:2], F['cases'], F['per_case']) == ((1, 1), (0, 2), (1, 2), (0, 1), 4, 1), F
        cg = lambda v1: '6:freezer:%s\n0::/uid_1/pid_2' % v1
        lf = lambda ph, t, v1, wake='mWakefulness=Awake', fz='false', state='S (sleeping)': {'exp': 'freeze_long', 'phase': ph, 't_s': t, 'cgroup': cg(v1), 'isFrozen': fz,
                                                                                               'frozen': '0', 'wake': wake, 'state': 'State:\t' + state}
        L = long_freeze([lf('A', 0.1, '/'), lf('A', 600.0, '/'), lf('B', 0.2, '/', 'mWakefulness=Dozing'), lf('B', 15.0, '/frozen', 'mWakefulness=Dozing', state='R (running)'),
                         lf('C', 0.1, '/frozen', state='R (running)', fz='true'), {'exp': 'freeze_long_cmd'}])
        assert (L['n'], L['android_frozen'], L['on_s'], L['on_v1'], L['to_v1'], L['running_in_v1'], L['in_v1']) == (5, 1, 600.0, 0, 15.0, 2, 2), L
        assert [(x['n'], x['off'], x['in_v1'], x['running'], x['first_v1']) for x in L['phases']] == [(2, False, 0, 0, None), (2, True, 1, 1, 15.0), (1, False, 1, 1, 0.1)], L['phases']
        so = lambda at, later, cb=True: {'exp': 'freeze_screenoff', 'v1_at_mutation': at, 'samples': [{'t_s': 46.0, 'v1': '/'}] + ([{'t_s': later, 'v1': '/frozen'}] if later else []) + [{'t_s': 85.0, 'v1': '/frozen' if later else '/'}],
                                         'contacts': {'first_before_wake': cb}, 'media': {'first_before_wake': True}}
        O = screen_off([so('/', 61.3), so('/', None), so('/', 64.0, cb=False)])
        assert (O['n'], O['at_write'], O['later'], O['callbacks'], O['off_s']) == (3, 0, [61.3, 64.0], 2, 85.0), O
        assert v['PhysEvidCheap'] == 'phone' and v['PhysEvidHost'] == 'phone' and v['PhysHostTrials'] == 2 and v['PhysHostStampGainNone'] == '50.0 [50.0, 50.0]' and v['PhysHostStampGainOne'] is None and v['PhysHostStampGainMin'] == v['PhysHostStampGainMax'] == '50.0'
        assert 'none & 2 & 200.0 & 150.0 & 50.0 & 50.0 [50.0, 50.0] & 11.0 / 4.0' in tab('tab_phys_host.tex'), tab('tab_phys_host.tex')
        assert v['PhysContTrials'] == 1 and v['PhysContStaleCert'] == '1/3' and v['PhysContActionOnly'] == '1/3' and v['PhysContAmbiguous'] == '1/4'
        assert 'refresh & 1 & 0 & 0 & 0' in tab('tab_phys_continuous.tex') and 'relay & 0 & 0 & 1 & 0' in tab('tab_phys_continuous.tex')
        assert '\\mgroup{5}{MediaStore}' in tab('tab_phys_deploy.tex') and tab('tab_phys_deploy.tex').count('Foreground service') == 2
        assert 'Force-stop & 1/1' in tab('tab_phys_gaps.tex') and '1/1 & 0/1 & 0/1 & 1/1 & 0/1 & 0/1' in tab('tab_phys_gaps.tex')
        assert 'not run on this phone' in tab('tab_phys_pitfalls.tex') and 'reused & 1/1 [' in tab('tab_phys_pitfalls.tex')
        assert not any('\\PhysTBD{' in tab(t) for t in tabs if 'eighta' not in t), [t for t in tabs if '\\PhysTBD{' in tab(t)]   # no Pixel 8a data here
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
        recs = recs9 = [bc('bnd', 1, 50, 60, band=True, delta_planned_ms=-5.0), bc('bnd', 1, 105, 112, num='A'), bc('bnd', 1, 122, 128), bc('bnd', 1, 200, 205, num='A', truth='A', dana_number_before='A'),
                bc('bnd', 1, 131, 140, read_ns=20e6), bc('bnd', 0), bc('obs', 0, dana_version_after='8', dana_version_unchanged=False),
                bc('bnd', 0, effect_row={'raw': 'No result found.'}), bc('bnd', 1), bc('obs', 1, 50, 60, num='A'), bc('bnd', 0, num='X', used='B'),
                bc('bnd', 1, 131, 140, num='A', read_ns=20e6, dana_number_before='A'),
                bc('bnd', 1, 105, 112, num='A', _file='boundary-pilot-1800.jsonl')]
        m, _ = write(dict(empty, boundary=recs), gen); w = {k: x for k, (_, x) in m.items()}
        assert w['PhysBoundaryTrials'] == 8 and w['PhysCteMs'] == '30.0' and w['PhysBndBeforeCheckStale'] == '0/1', (w['PhysBoundaryTrials'], w['PhysCteMs'])
        assert w['PhysBndOverlapStale'] == '1/2' and w['PhysBndObsStale'] == '1/1' and '\\PhysBoundarytrue' in tab('physical_macros.tex'), w['PhysBndOverlapStale']
        bt = tab('tab_phys_boundary.tex')
        assert 'separate raw contact' in bt and 'after effect & 1/3' in bt and 'no change (control) & 0/1' in bt, bt
        assert 'change overlaps & 1/2 & 1/0/1' in bt and 'change after effect & 1/3 & 0/2/1' in bt and 'before check & 0/1 & 0/1/0' in bt, bt
        assert '1 trial drew the change in a band around the check (planned offsets from $-5.0$ to $-5.0$' in bt, bt
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
                dict(dep('bg_freezer', '0', None), _file='deploy-contacts-2000.jsonl', device_instance='uF'),   # unknown, cgroup not frozen                               # unknown
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
                dict(dep('bg_freezer', '0', None), _file='deploy-contacts-freezer-1747.jsonl', device_instance='uI', run_arn='arn:aws:devicefarm:r:1:run:p/R2')]
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
        # B6 on-device and adb transport: refresh 200 ms round trip, 150 on device; StampCheck 150 and 90
        H = matched_host([dict(hr, arms={'refresh': dict(arm(200, 11), start_ns=0, end_ns=150e6), 'stamp': dict(arm(150, 4), start_ns=0, end_ns=90e6)})])
        assert H['none']['dev'] == {'refresh': 150.0, 'stamp': 90.0} and H['none']['transport'] == {'refresh': 50.0, 'stamp': 60.0}, H['none']
        # S25: the flag on every logged Contacts callback after a write through the provider; an app notifyChange does not count
        ev = lambda *fs: {'events': [{'src': s_, 't': t, 'flags': f} for t, (s_, f) in enumerate(fs)]}
        cf = contacts_flags([{'device_instance': 'u1', 'fingerprint': 'f1', 'memory_before_thaw': ev(('contacts', NO_DELAY | 1), ('media', 9)), 'memory_after_thaw': ev(('contacts', NO_DELAY | 1))},
                             {'exp': 'notify_flags', 'source': 'contacts', 'writer': 'mut', 'flags_all': [NO_DELAY | 1], 'device_instance': 'u2', 'fingerprint': 'f2'},
                             {'exp': 'notify_flags', 'source': 'contacts', 'writer': 'notify', 'flags_all': [1], 'device_instance': 'u3', 'fingerprint': 'f3'},
                             {'device_instance': 'u4', 'fingerprint': 'f4', 'late': ev(('contacts', 1))}])
        assert cf == ((2, 3), {'u1', 'u2', 'u4'}, {'f1', 'f2', 'f4'}), cf
        # B6 order: write cases that alternate on one unit; a repeated case breaks the alternation
        ho = lambda *cs: [{'case': c, 'start': i, 'device_instance': 'u', 'arms': {}} for i, c in enumerate(cs)]
        assert host_order(ho('none', 'one', 'continuous', 'none')) == (1, True) and host_order(ho('none', 'none', 'one'))[1] is False
        # a no-gap trial whose client ActivityManager killed during the hold: the caption names the exit description
        g = gap('none', 9, 11000, 'A', 'KEEP'); g['late'] = dict(g['late'], last_start={'exit': {'ts': 50, 'desc': '[TOO MANY EMPTY PROCS] too many empty'}})
        write(dict(empty, gaps=[dict(g, _file='gaps-none-2300.jsonl')]), gen)
        assert "No-gap exit record: ActivityManager killed the idle cached client during the hold (``too many empty'')" in tab('tab_phys_gaps.tex')
        # b13-* files load only for b13-* patterns
        (gen / 'physical-x').mkdir()
        for f in ('deploy-a.jsonl', 'b13-t-deploy-a.jsonl', 'phys-g14-t-cost-a.jsonl'):
            (gen / 'physical-x' / f).write_text('{"f": "%s"}\n' % f, encoding='utf-8')
        assert [r['f'] for r in load(gen, 'deploy*.jsonl')] == [r['f'] for r in load(gen, '*.jsonl')] == ['deploy-a.jsonl']
        assert [r['f'] for r in load(gen, B13 + '*-deploy*.jsonl')] == ['b13-t-deploy-a.jsonl']
        assert [r['f'] for r in load(gen, 'phys-g14-*.jsonl')] == ['phys-g14-t-cost-a.jsonl']

        # Pixel 8a (F6). Per-use cost: refresh over the source's facts, StampCheck split by whether the round changed it
        cr = lambda src, ns: {'source': src, 'refresh_ns': {'c.dana': 2e6, 'k.set': 4e6}, 'fact_src': {'c.dana': 'contacts', 'k.set': 'calendar'},
                              'costs': {'lm_hist_cost': {'contacts': {'ns': ns, 'reason': 'wm_equal'}, 'calendar': {'ns': 1e5, 'reason': 'unknown'}}}}
        PC = persource_cost([cr('contacts', 9e6), cr('calendar', 3e6), cr('none', 5e6), {'error': 'adb lost'}])
        assert PC['contacts'] == {'refresh': 2.0, 'changed': 9.0, 'unchanged': 4.0, 'stamp': True} and PC['calendar']['stamp'] is False and 'media' not in PC, PC
        # scale: a level without decisions is skipped; the fit uses the ACT records of the Contacts levels only
        sr = lambda L, raw, ch, vc: {'level': L, 'raw_contacts': raw, 'images': 3, 'change': ['contacts', 'media'] if ch else [], 'lm_miss': 0,
                                     'refresh_ns': dict.fromkeys(('c.dana', 'c.omar', 'c.set', 'm.latest', 'm.tracked'), 1e6),
                                     'costs': {'lm_hist_cost': {'contacts': {'ns': vc * 1e6}, 'media': {'ns': 2e6}}}}
        act = lambda L, raw, cte: {'level': L, 'raw_contacts': raw, 'images': 3, 'act': True, 'check_to_effect_ms': cte}
        SX = scale_cost([sr('contacts+0', 2, False, 10), sr('contacts+0', 2, True, 20), act('contacts+0', 2, 60), act('contacts+0', 2, 61),
                         sr('contacts+1000', 1002, False, 60), act('contacts+1000', 1002, 110), act('media+1000', 1002, 999)])
        z = SX['levels']['contacts+0']
        assert list(SX['levels']) == ['contacts+0', 'contacts+1000'] and (z['vc'], z['vcc'], z['vts'], z['rc'], z['rm'], z['cte'], z['acts']) == (10, 20, None, 3.0, 2.0, 60.5, 2), z
        assert SX['fit']['n'] == 3 and abs(SX['fit']['slope'] - 49.5) < 1e-6, SX['fit']
        # FGS cost: CPU ticks / 100, PSS in MB, the estimate over the windows that list it; an error window is left out
        fw = lambda m, cpu, pw, adj: {'mode': m, 'window_s': 250.0, 'mutations': 12, 'cpu_ticks': cpu, 'pss_kb': 2048, 'est_power_mah': pw, 'oom_score_adj': adj}
        FX = fg_cost([fw('bg', 1, 1e-5, '905'), fw('bg', 3, None, '925'), fw('fg', 150, 0.02, '200'), {'mode': 'fg', 'error': 'adb lost'}])
        assert FX['bg'] == {'n': 2, 'window_s': 250.0, 'changes': 12, 'cpu_s': 0.02, 'pss_mb': 2.0, 'power': 1e-5, 'listed': 1, 'adj': [905, 925]} and FX['fg']['n'] == 1, FX
        # unbatched host: ratio of the medians, content-query time over c./m./k. facts only
        h8 = lambda ch, gl, ev, n, miss=(): {'change': ch, 't_global_ms': gl, 't_evcheck_ms': ev, 'n_global': 11, 'n_reread': n, 'changed': ['c.dana'] if ch else [],
                                             'evcheck_miss': list(miss), 'ms_global': {'c.dana': 1000.0, 'g.mode': 100.0, 'f.todo': 100.0}}
        HX = host_unbatched([h8(True, 10000, 7000, 6, ['c.dana']), h8(False, 10000, 5000, 4), h8(False, 9000, 9500, 4)])
        assert (HX['ratio'], HX['reread_med'], HX['changed'], HX['missed'], HX['query_ms'], HX['cases'][False]['faster']) == (0.7, 4, 1, 1, 1000.0, 1), HX
        # long Doze: a trial whose cgroup sample reads frozen (an int, as phones log it) is invalid
        ld = lambda fz: dict(gap('longdoze2', 7, 11000, 'A', 'KEEP'), state_m1='IDLE', state_m2='IDLE', frozen_m1=0, frozen_m2=fz, t_gap_end=600100, device_instance='u8a')
        DX = long_doze([ld(0), ld(1)])
        assert (DX['n'], DX['att'], DX['span_min'], DX['units'], DX['miss']['late', 'lm']) == (1, 2, 10.0, 1, (0, 1)), DX
        # Pixel 8a records never change a Pixel 8 macro (its units' RUNLOG lines included); its SMS part gives no number
        p8 = lambda r, f: dict(r, device_instance='u8a', _file=f)
        E8 = {'p8a_cost': [p8(cr('contacts', 9e6), 'phys-g14-c.jsonl'), p8(cr('calendar', 3e6), 'phys-g14-c.jsonl'), p8(cr('none', 5e6), 'phys-g14-c.jsonl')],
              'p8a_longdoze': [p8(ld(0), 'phys-g18-d.jsonl')],
              'p8a_pitfalls': [p8(r, 'phys-l1-p.jsonl') for r in ({'exp': 'sms_reuse', 'res': {'ok': False}}, {'exp': 'mtime', 'res': [{'ok': True, 'did': '1->2'}, {'ok': True, 'did': '2->3'}]},
                                                                  ck6('transient', 'CHANGED', 'FRESH'))]}
        m0, _ = write(D, gen)
        m1, _ = write(dict(D, runlog=D.get('runlog', []) + [{'run_arn': None, 'device_instance': 'u8a', 'use_freezer_before': 'false', 'use_freezer': 'true', '_file': 'RUNLOG.md'}], **E8), gen)
        assert {k: v for k, (_, v) in m1.items() if not k.startswith('PhysEightA')} == {k: v for k, (_, v) in m0.items() if not k.startswith('PhysEightA')}
        w = {k: x for k, (_, x) in m1.items()}
        assert (w['PhysEightASmsValid'], w['PhysEightAMtimeSame'], w['PhysEightAClockTsTransientStale'], w['PhysEightACostContactsStamp'], w['PhysEightADozeTrials']) == ('0/1', '0/1', '1/1', '4.0', '1/1'), w
        assert 'Pitfall & Pixel~8 & Pixel~8a' in tab('tab_phys_pitfalls.tex') and '& failed (0/1 valid)' in tab('tab_phys_pitfalls.tex') and '\\PhysEightAtrue' in tab('physical_macros.tex')
        assert 'answers \\Unknown (no stamp) in 0.1' in tab('tab_phys_eighta.tex') and 'Late decision & missed: event-only 1/1, restart-aware 1/1, \\stamp 0/1' in tab('tab_phys_eighta.tex')
    print('analyze_phys self-check ok')


if __name__ == '__main__':
    if '--self-check' in sys.argv:
        self_check()
    else:
        res = ROOT / 'artifact/results'
        emu = [dict(json.loads(l), _file=p.name) for p in sorted((res / 'revision-20261115').glob('supplement-final-emulator-*.jsonl'))
               for l in p.read_text(encoding='utf-8').splitlines() if '"contacts_reset"' in l]     # same rule on the emulators
        emu_files = lambda d, pat: [dict(json.loads(l), _file=p.name) for p in sorted((res / d).glob(pat)) for l in p.read_text(encoding='utf-8').splitlines() if l.strip()]
        D = dict({k: load(res, p) for k, p in FILES.items()}, runlog=runlog_freezer(res / 'RUNLOG.md'), reset_emu=emu,
                 stock_emu=emu_files('revision-20261115', 'stock-emulator-*.jsonl'),           # emulator race, same rules
                 deploy_emu=emu_files('followup-20261116', 'deploy-emulator-*.jsonl'),        # emulator callbacks, same rules
                 **{'s25_' + k: load(res, MODELS['s25'] + p) for k, p in S25_FILES.items()},
                 **{'p9_' + k: load(res, MODELS['p9'] + p) for k, p in P9_FILES.items()},
                 **{'p8a_' + k: load(res, p) for k, p in P8A_FILES.items()})
        m, P = write(D, ROOT / 'manuscript/generated')
        print(json.dumps({'macros': len(m), 'tbd': sum(v is None for _, v in m.values()), 'runs': len({r.get('run_arn') for r in D['all']} - {None}),
                          'pilot_records': P['records'], 'pilot_deploy': summary(P['deploy'])}))
