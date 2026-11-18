#!/usr/bin/env python3
"""Physical-phone results (plan C3) -> manuscript/generated/physical_macros.tex and tab_phys_*.tex.

Reads only top-level artifact/results/physical-*/*.jsonl (append-only raw data from the experiment role); schema and
file names: PHYS-PROTOCOL.md sections 6, 7 and 10. Every macro or table without data renders \\PhysTBD{<what>}, a red
TBD; scripts/check_final.py fails while the PDF shows one. Trials are classified with the emulator rules of
scripts/analyze.py (valid, classify, gap_effects, coverage, e9_row), so phone and emulator numbers are comparable.
Files whose name contains "pilot" (S2 pipeline check) are summarized on stdout and never enter macros or tables.
Optional per-record fields of the AWS runs: `device_instance` (counted by \\PhysInstances) and `run_arn` (counted on
stdout); records without them still load. B6 (host-*) has one macro, B7 (continuous-*) none; B11 and B12 are dropped.
Run `python physical/analyze_phys.py --self-check`.
"""
import json, statistics as st, sys, tempfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'artifact/scripts'))
import analyze as ea                      # noqa: E402  emulator analysis rules
from render import GAPNAME, SRCNAME       # noqa: E402

NAMES = {'bg_unfrozen': 'Background, unfrozen', 'bg_freezer': 'Background, frozen', 'fg': 'Foreground service',
         'assistant': 'Bound assistant'}
SOURCES = {'contacts': 'Contacts', 'media': 'MediaStore', 'calllog': 'Call log'}
GAPS = ['none', 'freeze', 'dozeidle', 'bucket', 'unregister', 'kill', 'forcestop', 'perm', 'reboot']   # B2, campaign.py
LOST, INEPOCH = ['unregister', 'kill', 'forcestop', 'perm', 'reboot'], ['none', 'freeze', 'dozeidle', 'bucket']
FILES = {'deploy': 'deploy*.jsonl', 'gaps': 'gaps-*.jsonl', 'coverage': 'coverage-*.jsonl', 'stock': 'stock-*.jsonl',
         'boundary': 'boundary*.jsonl', 'pitfalls': 'pitfalls-*.jsonl', 'frozen': 'frozen-*.jsonl',
         'b0': 'b0-probe-*.jsonl', 'host': 'host-*.jsonl', 'all': '*.jsonl'}
# Sources never touched on this phone print NR instead of TBD: those the latest B0 record lists in excluded_sources.
# SMS and the call log (and with it B9, whose effect is a call-log row) each have an \if switch for the prose.
NR = 'not run on phone'
# B11 (24-hour state log) and B12 (battery) are dropped: rented Device Farm phones are always charging and a run lasts
# at most 150 min. Their macros stay defined and print NR; their tables carry one row that says why.
DROPPED = ['PhysStateHours', 'PhysStateAlivePct', 'PhysStateFrozenPct', 'PhysStateDozePct', 'PhysStateKillsPerHour',
           'PhysBatteryFgsMahPerHour', 'PhysBatteryBgMahPerHour', 'PhysBatteryFgsBlocks', 'PhysBatteryBgBlocks']
WHY = 'dropped: rented Device Farm phones are always charging and a run lasts at most 150\\,min'


def not_run(b0):
    """Sources not run: excluded_sources of the latest B0 record (files sort by date and time); none before B0."""
    recs = [r for r in b0 if 'excluded_sources' in r]
    return set(recs[-1]['excluded_sources'] if recs else ())


def load(res, pattern):
    """All records of one experiment, with the file name; nothing is rewritten."""
    return [dict(json.loads(l), _file=p.name) for p in sorted(res.glob('physical-*/' + pattern))
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


# ------------------------------------------------------------------ per experiment: dict of results, or {} without data
def deploy(rows):
    """B1: callback delay per (source, deployment); a callback counts only for the trial's own `source`
    (records without it are emulator-schema Contacts trials)."""
    out = {}
    for src in SOURCES:
        for mode in NAMES:
            rs = [r for r in rows if r.get('source', 'contacts') == src and r.get('mode') == mode]
            if not rs:
                continue
            target = '1' if mode == 'bg_freezer' else '0'
            valid, delays, before = [], [], 0
            for r in rs:
                if 'error' in r or r.get('invalid') or r['before'].get('frozen') != target or any(x.get('frozen') != target for x in r['states']):
                    continue
                valid.append(r); t = r['mutation']['t_pre']
                ev = [e['t'] - t for e in r['memory_before_thaw'].get('events', []) if e['src'] == src and e['t'] >= t]
                before += bool(ev)
                if ev:
                    delays.append(min(ev))
            out[src, mode] = {'attempted': len(rs), 'valid': len(valid), 'before_thaw': before, 'delays_ms': delays}
    return out


def gaps(rows):
    """B2: gap taxonomy and missed changed uses (event-only, restart-aware, StampCheck), emulator validity rules."""
    att, V = Counter(r['gap'] for r in rows), defaultdict(list)
    for t in rows:
        if ea.valid(t)[0]:
            V[t['gap']].append(t)
    out = {}
    for g in [g for g in GAPS if att[g]] + sorted(set(att) - set(GAPS)):
        T = V[g]; z = {'att': att[g], 'n': len(T), 'miss': {}}
        if T:
            z['survived'], z['nsrc'], z['ev_e'], z['ev_l'], _, z['exit'], _, z['fcl'] = ea.gap_effects(T)
        for phase in ('early', 'late'):
            C = [ea.classify(t, phase) for t in T]
            for p in ('ev', 'evr', 'lm'):
                ch = [x for c in C for x in c.values() if x['changed']]
                z['miss'][phase, p] = (sum(not x['refresh'][p] for x in ch), len(ch))
        z['cost'] = [ea.decision_cost(t, 'late', ea.classify(t, 'late')) for t in T if 'lm_cost' in t['late']]
        out[g] = z
    return out


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
    """B9: stale effects by where the change landed (scripts/analyze.py e3 rules)."""
    rows = [r for r in rows if r.get('res')]
    if not rows:
        return {}
    cls, cte, bins = Counter(), [], {'near': [0, 0], 'late': [0, 0]}
    for r in rows:
        res, stale = r['res'], bool(r['res'].get('stale'))
        if r['mode'] == 'bnd':
            cte.append(res['effect_end'] - res['check2_start'])
        if not (r['change'] and r.get('mut')):
            where = 'none'
        else:
            ms, me = r['mut']['mut_start'], r['mut']['mut_end']
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
    return {'n': len(rows), 'cte': cte, 'k': k, 'bins': bins}


def pitfalls(rows):
    reuse = [r for r in rows if r.get('exp') == 'sms_reuse' and r['res'].get('ok')]
    mt = [r for r in rows if r.get('exp') == 'mtime' and all(x.get('ok') for x in r['res'])]
    # clock set-back (driver/e6_pitfalls.py): valid only if the clock really went back (about 1 h; 50 min suffices);
    # affected = the client's Contacts stamp (lm) kept FRESH although the cached number was stale (scripts/analyze.py e6)
    ck = [r for r in rows if r.get('exp') == 'clock' and 'error' not in r and r.get('clock_moved_back_ms', 0) >= 3000000]
    same = lambda did: did.split('->')[0] == did.split('->')[1]
    if not (reuse or mt or ck):
        return {}
    return {'sms': (sum(same(r['res']['did']) for r in reuse), len(reuse)), 'mtime': (sum(same(r['res'][1]['did']) for r in mt), len(mt)),
            'clock': (sum(r['lm'] == 'FRESH' and bool(r['stale_if_used']) for r in ck), len(ck))}


def frozen(rows):
    """B5: long frozen holds, one e9_row per hold."""
    out = [ea.e9_row(r, 'phone') for r in rows]
    V = [o for o in out if o['valid']]
    if not V:
        return {}
    S = [o for o in V if o['stayed_frozen']]
    return {'run': len(out), 'valid': len(V), 'stayed': len(S), 'died': sum(o['died'] for o in V), 'changes': sum(o['n_mut'] for o in V),
            'hold_min': min(o['frozen_with_pending_s'] for o in V) / 60, 'src': sum(o['sources_mutated'] for o in S),
            'lost': sum(o['sources_no_callback'] for o in S), 'unseen': sum(o['sources_last_change_unseen'] for o in S),
            'callbacks': sum(o['callbacks_vlate'] for o in V), 'evr': [sum(o['evr_miss_' + p] for o in V) for p in ('early', 'late', 'vlate')]}


def device(rows, key):
    vals = sorted({str(r[key]) for r in rows if r.get(key) is not None})
    return ', '.join(vals) if vals else None


def tex(s):
    """Plain device strings into LaTeX text."""
    return None if s is None else ''.join('\\' + c if c in '_&%#$' else c for c in s)


def android(b0):
    """'Android <release>, SDK <level>' from the B0 identity probe."""
    ids = [r['detail'] for r in b0 if r.get('probe') == 'identity' and r.get('ok') and isinstance(r.get('detail'), dict)]
    v = sorted({'Android %s, SDK %s' % (x.get('ro.build.version.release'), x.get('ro.build.version.sdk')) for x in ids})
    return '; '.join(v) if v else None


def analyze(D):
    """D: experiment key -> records (with _file). Returns (macros, results of main runs, results of pilot runs)."""
    M = {k: [r for r in v if not pilot(r)] for k, v in D.items()}
    R = {'deploy': deploy(M['deploy']), 'gaps': gaps(M['gaps']), 'coverage': coverage(M['coverage']), 'race': race(M['stock']),
         'boundary': boundary(M['boundary']), 'pitfalls': pitfalls(M['pitfalls']), 'frozen': frozen(M['frozen']),
         'not_run': not_run(D['b0'])}
    X = R['not_run']
    nr = lambda src, val: NR if src in X else val       # a source not run prints NR, not TBD
    P = {'deploy': deploy([r for r in D['deploy'] if pilot(r)]),
         'records': dict(Counter(k for k, v in D.items() if k != 'all' for r in v if pilot(r)))}
    B1, G, BD, F, PF = R['deploy'], R['gaps'], R['boundary'], R['frozen'], R['pitfalls']
    med = lambda s, m: dur(st.median(B1[s, m]['delays_ms'])) if (s, m) in B1 and B1[s, m]['delays_ms'] else None
    fcl = lambda g: sec(st.median(G[g]['fcl'])) if g in G and G[g].get('fcl') else None
    def gmiss(gs, phase, p):
        k = [G[g]['miss'][phase, p] for g in gs if g in G]
        return kn(sum(a for a, _ in k), sum(b for _, b in k)) if k and sum(b for _, b in k) else None
    frz = B1.get(('contacts', 'bg_freezer'))
    race_n, race_k = sum(z['n'] for z in R['race'].values()), sum(z['stale'] for z in R['race'].values())
    host = [r for r in M['host'] if 'error' not in r]                      # B6 matched host trials
    has = {'B1': any(z['valid'] for z in B1.values()), 'B2': any(z['n'] for z in G.values()), 'B4': race_n > 0,
           'B6': bool(host), 'B10': bool(R['pitfalls'])}
    evid = lambda *ex: 'phone' if all(has[e] for e in ex) else None   # guidance-table evidence: measured on the phone
    cost = [c for z in G.values() for c in z.get('cost', [])]       # B2 late decisions with the client's lm_cost
    has['cost'] = bool(cost)
    cmed = lambda k: '%.0f' % st.median(c[k] for c in cost) if cost else None
    cci = lambda k: (lambda m: '[%.0f, %.0f]' % (m[1], m[2]))(ea.boot_ci([c[k] for c in cost])) if cost else None
    pf = lambda k: kn(*PF[k]) if PF and PF[k][1] else None          # B10 cell; no trials of that kind: TBD, not 0/0
    inst = {r.get('device_instance') for k, v in M.items() if k not in ('all', 'b0') for r in v} - {None}
    macros = {
        'PhysDevice': ('device model', tex(device(D['all'], 'device'))),
        'PhysFingerprint': ('build fingerprint', (lambda f: f and '\\path{%s}' % f)(device(D['all'], 'fingerprint'))),
        'PhysAndroid': ('Android release and SDK level', android(D['b0'])),
        'PhysRooted': ('root status', {'True': 'rooted', 'False': 'not rooted'}.get(device(D['all'], 'rooted') or '', None)),
        'PhysSdk': ('API level', device(D['all'], 'sdk')),
        'PhysInstances': ('distinct physical units', len(inst) or None),
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
        'PhysBoundaryTrials': ('B9 boundary trials', nr('calllog', BD.get('n'))),
        'PhysCteMs': ('B9 median check-to-effect interval, ms', nr('calllog', f"{st.median(BD['cte']):.1f}" if BD.get('cte') else None)),
        'PhysBndObsStale': ('B9 observation check, change before the action: stale/n', nr('calllog', kn(*BD['k']('obs', 'before_action')) if BD else None)),
        'PhysBndBeforeCheckStale': ('B9 boundary check, change before the check: stale/n', nr('calllog', kn(*BD['k']('bnd', 'before_check')) if BD else None)),
        'PhysBndOverlapStale': ('B9 boundary check, change overlaps check or residual: stale/n', nr('calllog', kn(*BD['k']('bnd', 'overlaps')) if BD else None)),
        'PhysSmsReuse': ('B10 SMS id reuse trials', nr('sms', pf('sms'))),
        'PhysMtimeSame': ('B10 same-second mtime trials', pf('mtime')),
        'PhysClockTrials': ('B10 valid clock set-back trials', PF['clock'][1] if PF and PF['clock'][1] else None),
        'PhysClockStale': ('B10 clock set-back: stale number accepted/trials', pf('clock')),
        'PhysFrozenHolds': ('B5 valid frozen holds', F.get('valid')),
        'PhysFrozenStayed': ('B5 holds that stayed frozen', F.get('stayed')),
        'PhysFrozenKilled': ('B5 holds ended by a kill', kn(F['died'], F['valid']) if F else None),
        'PhysFrozenLastUnseen': ('B5 sources whose last change had no later callback', kn(F['unseen'], F['src']) if F else None),
        **{k: ('B11/B12 dropped', NR) for k in DROPPED},
        'PhysHostTrials': ('B6 matched host trials', len(host) or None),
        'PhysCostGl': ('B2 median provider ms per late decision, global refresh', cmed('gl_ms')),
        'PhysCostGlCi': ('B2 bootstrap CI of that median', cci('gl_ms')),
        'PhysCostLm': ('B2 median provider ms per late decision, StampCheck', cmed('lm_ms')),
        'PhysCostLmCi': ('B2 bootstrap CI of that median', cci('lm_ms')),
        'PhysCostN': ('B2 late decisions with cost', len(cost) or None),
        'PhysEvidCheap': ('phone B2 refresh cost', evid('cost')),   # B6 is optional (may be cut); it only adds
        'PhysEvidBound': ('phone B1 and B2', evid('B1', 'B2')),
        'PhysEvidWeak': ('phone B4 and B10', evid('B4', 'B10')),
    }
    return macros, R, P


# ------------------------------------------------------------------ tables (no data: one red TBD row)
def table(gen, name, caption, cols, header, rows, what, star=False, extra=(), tbd=True):
    env = 'table*' if star else 'table'
    body = (rows if rows or not tbd else [r'\multicolumn{%d}{c}{\PhysTBD{%s}}\\' % (len(cols), what)]) + list(extra)
    (gen / name).write_text('\n'.join(['%% AUTO-GENERATED by artifact/physical/analyze_phys.py; do not edit', r'\begin{%s}[tp]' % env, r'\centering\mtab',
        r'\caption{%s}' % caption, r'\label{tab:%s}' % name[4:-4].replace('_', '-'), r'\begin{tabular}{%s}\toprule' % cols,
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
    table(gen, 'tab_phys_deploy.tex', "Phone (B1): callbacks per source and deployment, counted only for the trial's own source; valid/attempted trials, median and range of the delay, trials with a callback before thaw.",
          'lrrrr', 'Deployment & Trials & Median & Range & Before thaw', rows, 'B1 deployment trials',
          extra=[r'\mgroup{5}{%s: %s}' % (SOURCES[x], NR) for x in SOURCES if x in NOT_RUN])

    rows = []
    cov = R['coverage']
    for c in cov.get('cells', []):
        if c['main'] and c['source'] not in NOT_RUN:
            cell = lambda k: kn(c[k + '_k'], c[k + '_n']) + ('$^{\\downarrow}$' if c.get(k + '_down') else '') if c.get(k + '_n') else 'n/a'
            rows.append(f"{SRCNAME[c['source']]} & {c['label']} & " + ' & '.join(cell(k) for k in ('insert', 'update', 'delete', 'none')) + r'\\')
    table(gen, 'tab_phys_coverage.tex', 'Phone (B3): trials in which a candidate stamp moved after one mutation of each kind by another app (%s trials); None = source untouched; $\\downarrow$: moved downward in some trials.' % cov.get('n', r'\PhysTBD{B3 trials}'),
          'llrrrr', 'Source & Candidate & Insert & Update & Delete & None', rows, 'B3 coverage trials',
          extra=[r'%s & \multicolumn{5}{l}{%s}\\' % (SRCNAME[x], NR) for x in sorted(NOT_RUN)])

    rows = []
    for g, z in R['gaps'].items():
        m = lambda ph, p: kn(*z['miss'][ph, p])
        fc = '%s / %s' % (sec(st.median(z['fcl'])), sec(max(z['fcl']))) if z.get('fcl') else 'none'
        rows.append(f"{GAPNAME.get(g, g)} & {z['n']}/{z['att']} & {pct(z.get('survived', 0), z['n'])} & {fc} & {pct(z.get('ev_e', 0), z.get('nsrc', 0))} & "
                    f"{pct(z.get('ev_l', 0), z.get('nsrc', 0))} & {z.get('exit', 0)}/{z['n']} & " + ' & '.join(m(ph, p) for ph in ('early', 'late') for p in ('ev', 'evr', 'lm')) + r'\\')
    table(gen, 'tab_phys_gaps.tex', 'Phone (B2), background client: valid/attempted trials, process survival, first callback (median / max, s), changed provider sources notified by the early (+2\\,s) and late (+14\\,s) decision, new \\texttt{ApplicationExitInfo} records, and changed uses missed by event-only (Ev), restart-aware (Evr) and \\stamp at the early (+2\\,s) and late (+14\\,s) decision (missed/changed).',
          'lrrrrrrrrrrrr', r' & & & & \multicolumn{2}{c}{Notified} & & \multicolumn{3}{c}{Missed at +2\,s} & \multicolumn{3}{c}{Missed at +14\,s}\\ \mhead '
          r'Gap & Trials & Surv.\,\% & First cb. & +2\,s\,\% & +14\,s\,\% & Exit & Ev & Evr & \stamp & Ev & Evr & \stamp', rows, 'B2 gap trials', star=True)

    rows = [f"{SRCNAME.get(c, c)} & {z['n']} & {wil(z['stale'], z['n'])} & {z['unknown']}/{z['n']}\\\\" for c, z in sorted(R['race'].items()) if z['n'] and c not in NOT_RUN]
    table(gen, 'tab_phys_race.tex', 'Phone (B4): a writer races the optimistic anchor; trials whose anchor certified a value that had changed (Wilson 95\\% interval) and trials in which strict \\sys returned \\Unknown.',
          'lrrr', r'Source & Trials & Stale \Fresh & \Unknown', rows, 'B4 race trials',
          extra=[r'%s & \multicolumn{3}{l}{%s}\\' % (SRCNAME[x], NR) for x in sorted(NOT_RUN)])

    BD, rows = R['boundary'], []
    if BD and 'calllog' not in NOT_RUN:
        for lab, m, w in [('check at observation; change before the action', 'obs', 'before_action'), ('boundary check; change before the check', 'bnd', 'before_check'),
                          ('boundary check; change overlaps check or residual', 'bnd', 'overlaps'), ('boundary check; change after the effect', 'bnd', 'after_effect'),
                          ('boundary check, no change (control)', 'bnd', 'none'), ('observation check, no change (control)', 'obs', 'none')]:
            rows.append(f"{lab} & {kn(*BD['k'](m, w))}\\\\")
        rows += [f"change starts within 10\\,ms of the check & {kn(*BD['bins']['near'])}\\\\", f"change starts 10 to 60\\,ms after it & {kn(*BD['bins']['late'])}\\\\"]
    table(gen, 'tab_phys_boundary.tex', 'Phone (B9): stale effects by where the change landed relative to the boundary check and the effect (stale/trials); median check-to-effect interval \\PhysCteMs\\,ms.',
          'lr', 'Placement of the change & Stale effects', rows, 'B9 boundary trials', tbd='calllog' not in NOT_RUN,
          extra=[r'\multicolumn{2}{c}{the effect is a call-log row: %s}\\' % NR] if 'calllog' in NOT_RUN else [])

    PF, rows = R['pitfalls'], []
    if PF:
        cell = lambda k: wil(*PF[k]) if PF[k][1] else r'\PhysTBD{B10 %s trials}' % k     # no trials of that kind yet
        rows = [f"SMS \\texttt{{\\_id}} reused after delete and insert & {NR if 'sms' in NOT_RUN else cell('sms')}\\\\", f"second append in the same second leaves mtime & {cell('mtime')}\\\\",
                'clock set back 1\\,h, \\stamp keeps a stale number & ' + (wil(*PF['clock']) if PF['clock'][1] else 'not run on this phone') + r'\\']
    table(gen, 'tab_phys_pitfalls.tex', 'Phone (B10): evidence pitfalls, trials affected out of trials (Wilson 95\\% interval).',
          'lr', 'Pitfall & Trials affected', rows, 'B10 pitfall trials',
          extra=[r'SMS \texttt{\_id} reuse & %s\\' % NR] if 'sms' in NOT_RUN and not PF else [])

    F, rows = R['frozen'], []
    if F:
        rows = [f'Holds valid/run & {F["valid"]}/{F["run"]}\\\\', f'Stayed frozen & {F["stayed"]}\\\\', f'Killed & {F["died"]}\\\\', f'Changes & {F["changes"]}\\\\',
                f'Hold $\\geq$ (min) & {F["hold_min"]:.1f}\\\\', f'Lost sources & {F["lost"]}/{F["src"]}\\\\', f'Unseen last & {F["unseen"]}/{F["src"]}\\\\',
                f'Callbacks & {F["callbacks"]}\\\\', 'Restart-aware miss & %d/%d/%d\\\\' % tuple(F['evr'])]
    table(gen, 'tab_phys_frozen.tex', 'Phone (B5): long frozen holds, same metrics as Table~\\ref{tab:frozen}; lost and unseen sources count holds that stayed frozen; last row: changed uses missed by restart-aware event-only at +2/+14/+120\\,s.',
          'lr', 'Metric & Phone', rows, 'B5 frozen holds')

    for name, what in (('tab_phys_statelog.tex', 'B11, 24-hour state log'), ('tab_phys_battery.tex', 'B12, battery drain')):
        table(gen, name, 'Phone (%s): not run.' % what, 'l', 'Status', [], what, tbd=False, extra=[WHY + r'\\'])


def write(D, gen):
    macros, R, P = analyze(D)
    lines = ['% AUTO-GENERATED by artifact/physical/analyze_phys.py; do not edit',
             r'\providecommand{\PhysTBD}[1]{}\renewcommand{\PhysTBD}[1]{\textcolor{red}{TBD}}']
    for src, sw in (('calllog', 'Calllog'), ('sms', 'Sms')):      # true unless the latest B0 excludes the source
        lines.append(r'\newif\ifPhys%s\Phys%s%s' % (sw, sw, 'false' if src in R['not_run'] else 'true'))
    lines.append(r'\newif\ifPhysReboot\PhysReboot%s' % ('true' if R['gaps'].get('reboot', {}).get('n') else 'false'))   # valid B2 reboot trials
    lines.append(r'\newif\ifPhysClock\PhysClock%s' % ('true' if R['pitfalls'].get('clock', (0, 0))[1] else 'false'))   # valid B10 clock trials
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
        assert all(s in tex for s in ('\\PhysCalllogtrue', '\\PhysSmstrue', '\\PhysRebootfalse', '\\PhysClockfalse')), 'before B0: SMS and call log run, no reboot or clock'
        assert '\\renewcommand{\\PhysTBD}' in tex
        assert '%' not in tex.split('\n', 1)[1], 'a % in a macro would comment out the rest of its line'
        tabs = sorted(p.name for p in gen.glob('tab_phys_*.tex'))
        dropped = {'tab_phys_statelog.tex', 'tab_phys_battery.tex'}
        assert '(\\PhysTBD{B3 trials} trials)' in tab('tab_phys_coverage.tex')
        assert len(tabs) == 9 and all(('\\PhysTBD{' in tab(t)) == (t not in dropped) for t in tabs), tabs
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
            dep('bg_freezer', '1', None), {'mode': 'fg', 'error': 'adb lost'})
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
        add('frozen', 'frozen-0100.jsonl', hold(5), hold(6))
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
        assert v['PhysEvidBound'] == 'phone' and v['PhysEvidWeak'] == 'phone' and v['PhysEvidCheap'] == 'phone' and v['PhysHostTrials'] is None   # B2 without B6 suffices
        assert v['PhysCostGl'] == '2' and v['PhysCostLm'] == '5' and v['PhysCostN'] == 3 and v['PhysCostLmCi'] == '[5, 5]', (v['PhysCostGl'], v['PhysCostLm'])
        nocost = dict(D, gaps=[dict(r, late={k: x for k, x in r['late'].items() if k != 'lm_cost'}) for r in D['gaps']])
        m, _ = write(nocost, gen); w = {k: x for k, (_, x) in m.items()}
        assert w['PhysEvidCheap'] is None and w['PhysCostGl'] is None and w['PhysGapTrials'] == '3/3', 'B2 without cost numbers must not claim phone evidence'
        add('host', 'host-X-1400.jsonl', {'case': 'none', 'arms': {}}, {'case': 'one', 'error': 'adb lost'})
        m, _ = write(D, gen); v = {k: x for k, (_, x) in m.items()}
        assert v['PhysEvidCheap'] == 'phone' and v['PhysHostTrials'] == 1
        assert '\\mgroup{5}{MediaStore}' in tab('tab_phys_deploy.tex') and tab('tab_phys_deploy.tex').count('Foreground service') == 2
        assert 'Force-stop & 1/1' in tab('tab_phys_gaps.tex') and '1/1 & 0/1 & 0/1 & 1/1 & 0/1 & 0/1' in tab('tab_phys_gaps.tex')
        assert 'not run on this phone' in tab('tab_phys_pitfalls.tex') and 'insert & 1/1 [' in tab('tab_phys_pitfalls.tex')
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
        assert '\\PhysClocktrue' in tab('physical_macros.tex') and 'stale number & 1/3 [' in tab('tab_phys_pitfalls.tex')
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
        # B0 excludes the call log: call-log cells and all of B9 print NR, never TBD; other sources are unaffected
        add('b0', 'b0-probe-0800.jsonl', {'probe': 'user_info', 'ok': True, 'excluded_sources': ['sms', 'calllog'], 'detail': {}})
        m, _ = write(D, gen); v = {k: x for k, (_, x) in m.items()}
        assert v['PhysDeployCalllogBgMedian'] == NR and v['PhysDeployCalllogFgMedian'] == NR and v['PhysSmsReuse'] == NR
        assert all(v[k] == NR for k in ('PhysBoundaryTrials', 'PhysCteMs', 'PhysBndObsStale', 'PhysBndBeforeCheckStale', 'PhysBndOverlapStale'))
        assert v['PhysDeployMediaBgMedian'] == '500\\,ms' and v['PhysMtimeSame'] == '0/1' and '\\PhysCalllogfalse' in tab('physical_macros.tex')
        assert 'Call log: ' + NR in tab('tab_phys_deploy.tex') and tab('tab_phys_deploy.tex').count('Foreground service') == 1
        assert all(NR in tab(t) for t in ('tab_phys_coverage.tex', 'tab_phys_race.tex', 'tab_phys_pitfalls.tex', 'tab_phys_boundary.tex'))
        assert '\\PhysTBD{' not in tab('tab_phys_boundary.tex')
        # same exclusion without any data: B9 is NR, not TBD; other tables stay TBD
        bare = dict(empty, b0=D['b0'][-1:])
        m, _ = write(bare, gen); v = {k: x for k, (_, x) in m.items()}
        assert v['PhysBoundaryTrials'] == NR and v['PhysDeployBgMedian'] is None and '\\PhysTBD{' not in tab('tab_phys_boundary.tex')
        assert '\\PhysTBD{' in tab('tab_phys_deploy.tex') and 'Call log: ' + NR in tab('tab_phys_deploy.tex')
        # a later B0 runs every source: SMS and call log are computed again
        add('b0', 'b0-probe-0900.jsonl', {'probe': 'user_info', 'ok': True, 'excluded_sources': [], 'detail': {}})
        m, _ = write(D, gen); v = {k: x for k, (_, x) in m.items()}
        assert v['PhysSmsReuse'] == '1/1' and v['PhysBoundaryTrials'] == 3 and '\\PhysSmstrue' in tab('physical_macros.tex') and '\\PhysCalllogtrue' in tab('physical_macros.tex')
        # the real AWS sequence: an older partial B0 lists nothing, the valid later one lists calllog and sms
        b0 = lambda f, ex: {'probe': 'identity', 'ok': True, 'excluded_sources': ex, 'detail': {}, '_file': f}
        write(dict(empty, b0=[b0('b0-probe-1533.jsonl', []), b0('b0-probe-1551.jsonl', ['calllog', 'sms'])]), gen)
        assert '\\PhysSmsfalse' in tab('physical_macros.tex') and '\\PhysCalllogfalse' in tab('physical_macros.tex')
    print('analyze_phys self-check ok')


if __name__ == '__main__':
    if '--self-check' in sys.argv:
        self_check()
    else:
        res = ROOT / 'artifact/results'
        D = {k: load(res, p) for k, p in FILES.items()}
        m, P = write(D, ROOT / 'manuscript/generated')
        print(json.dumps({'macros': len(m), 'tbd': sum(v is None for _, v in m.values()), 'runs': len({r.get('run_arn') for r in D['all']} - {None}),
                          'pilot_records': P['records'], 'pilot_deploy': summary(P['deploy'])}))
