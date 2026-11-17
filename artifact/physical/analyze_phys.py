#!/usr/bin/env python3
"""Physical-phone results (plan C3) -> manuscript/generated/physical_macros.tex and tab_phys_*.tex.

Reads only top-level artifact/results/physical-*/*.jsonl (append-only raw data from the experiment role); schema and
file names: PHYS-PROTOCOL.md sections 6, 7 and 10. Every macro or table without data renders \\PhysTBD{<what>}, a red
TBD; scripts/check_final.py fails while the PDF shows one. Trials are classified with the emulator rules of
scripts/analyze.py (valid, classify, gap_effects, coverage, e9_row), so phone and emulator numbers are comparable.
Files whose name contains "pilot" (S2 pipeline check) are summarized on stdout and never enter macros or tables.
B6 (host-*) and B7 (continuous-*) have no macro yet. Run `python physical/analyze_phys.py --self-check`.
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
         'statelog': 'statelog-*.jsonl', 'battery': 'battery-night*-samples.jsonl', 'b0': 'b0-probe-*.jsonl', 'host': 'host-*.jsonl', 'all': '*.jsonl'}
# Sources never touched on this phone print NR instead of TBD. SMS always (its store is shared with the owner's user);
# the call log, and with it B9 (whose effect is a call-log row), when the latest B0 record lists it in excluded_sources.
ALWAYS_OUT = {'sms'}
NR = 'not run on phone'


def not_run(b0):
    """Sources not run: ALWAYS_OUT plus excluded_sources of the latest B0 record (files sort by date and time)."""
    recs = [r for r in b0 if 'excluded_sources' in r]
    return ALWAYS_OUT | set(recs[-1]['excluded_sources'] if recs else ())


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
    same = lambda did: did.split('->')[0] == did.split('->')[1]
    if not (reuse or mt):
        return {}
    return {'sms': (sum(same(r['res']['did']) for r in reuse), len(reuse)), 'mtime': (sum(same(r['res'][1]['did']) for r in mt), len(mt)),
            'clock': sum(r.get('exp') == 'clock' for r in rows)}


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


def statelog(rows):
    """B11: share of samples per state, process deaths per hour; charging time separated."""
    start = next((r for r in rows if r.get('kind') == 'start'), {})
    period = start.get('period_s', 5)
    S = sorted((r for r in rows if r.get('kind') == 'sample'), key=lambda r: r['t'])
    if not S:
        return {}
    out = {}
    for plugged in (False, True):
        G = [r for r in S if bool(r.get('plugged')) == plugged and 'error' not in r]
        n_all = sum(bool(r.get('plugged')) == plugged for r in S)   # failed samples count as unplugged time
        out[plugged] = {'samples': len(G), 'all': n_all, 'hours': n_all * period / 3600,
                        'alive': sum(bool(r['alive']) for r in G), 'frozen': sum(str(r.get('frozen')) in ('1', 'True', 'true') for r in G),
                        'deep': sum(r.get('doze_deep') == 'IDLE' for r in G), 'deaths': 0}
    prev = None
    for r in S:
        if 'error' in r:
            continue
        if prev and prev['alive'] and (not r['alive'] or r['pid'] != prev['pid']):
            out[bool(r.get('plugged'))]['deaths'] += 1
        prev = r
    out['hours'] = len(S) * period / 3600
    return out


def battery(rows):
    """B12: drain per hour over complete blocks; arm on = FGS running, off = plain background client."""
    out = {}
    for arm in ('on', 'off'):
        B = [r for r in rows if r.get('kind') == 'block' and r.get('arm') == arm]
        C = [b for b in B if b.get('complete') and b.get('duration_s')]
        mah = [(b['charge_start_uAh'] - b['charge_end_uAh']) / 1000 / (b['duration_s'] / 3600) for b in C
               if b.get('charge_start_uAh') is not None and b.get('charge_end_uAh') is not None]
        lvl = [(b['level_start'] - b['level_end']) / (b['duration_s'] / 3600) for b in C if b.get('level_start') is not None and b.get('level_end') is not None]
        if B:
            out[arm] = {'blocks': len(B), 'complete': len(C), 'hours': sum(b['duration_s'] for b in C) / 3600, 'mah': mah, 'lvl': lvl}
    return out


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
         'statelog': statelog(M['statelog']), 'battery': battery(M['battery']), 'not_run': not_run(D['b0'])}
    X = R['not_run']
    nr = lambda src, val: NR if src in X else val       # a source not run prints NR, not TBD
    P = {'deploy': deploy([r for r in D['deploy'] if pilot(r)]),
         'records': dict(Counter(k for k, v in D.items() if k != 'all' for r in v if pilot(r)))}
    B1, G, BD, F, SL, BT = R['deploy'], R['gaps'], R['boundary'], R['frozen'], R['statelog'], R['battery']
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
    unpl = SL.get(False, {})
    batt = lambda arm: f"{st.mean(BT[arm]['mah']):.1f}" if arm in BT and BT[arm]['mah'] else None
    macros = {
        'PhysDevice': ('device model', tex(device(D['all'], 'device'))),
        'PhysFingerprint': ('build fingerprint', (lambda f: f and '\\path{%s}' % f)(device(D['all'], 'fingerprint'))),
        'PhysAndroid': ('Android release and SDK level', android(D['b0'])),
        'PhysRooted': ('root status', {'True': 'rooted', 'False': 'not rooted'}.get(device(D['all'], 'rooted') or '', None)),
        'PhysSdk': ('API level', device(D['all'], 'sdk')),
        'PhysDeployTrials': ('B1 valid/attempted trials, all sources', kn(sum(z['valid'] for z in B1.values()), sum(z['attempted'] for z in B1.values())) if B1 else None),
        'PhysDeployBgMedian': ('B1 Contacts background unfrozen median callback delay', med('contacts', 'bg_unfrozen')),
        'PhysDeployFgMedian': ('B1 Contacts FGS median callback delay', med('contacts', 'fg')),
        'PhysDeployAssistMedian': ('B1 Contacts bound assistant median callback delay', med('contacts', 'assistant')),
        'PhysDeployFrozenBeforeThaw': ('B1 Contacts frozen trials with a callback before thaw', kn(frz['before_thaw'], frz['valid']) if frz else None),
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
        'PhysSmsReuse': ('B10 SMS id reuse trials', nr('sms', kn(*R['pitfalls']['sms']) if R['pitfalls'] else None)),
        'PhysMtimeSame': ('B10 same-second mtime trials', kn(*R['pitfalls']['mtime']) if R['pitfalls'] else None),
        'PhysFrozenHolds': ('B5 valid frozen holds', F.get('valid')),
        'PhysFrozenStayed': ('B5 holds that stayed frozen', F.get('stayed')),
        'PhysFrozenKilled': ('B5 holds ended by a kill', kn(F['died'], F['valid']) if F else None),
        'PhysFrozenLastUnseen': ('B5 sources whose last change had no later callback', kn(F['unseen'], F['src']) if F else None),
        'PhysStateHours': ('B11 logged hours', f"{SL['hours']:.1f}" if SL else None),
        'PhysStateAlivePct': ('B11 unplugged share of samples alive', pct(unpl['alive'], unpl['samples']) if unpl.get('samples') else None),
        'PhysStateFrozenPct': ('B11 unplugged share of samples frozen', pct(unpl['frozen'], unpl['samples']) if unpl.get('samples') else None),
        'PhysStateDozePct': ('B11 unplugged share of samples in deep Doze', pct(unpl['deep'], unpl['samples']) if unpl.get('samples') else None),
        'PhysStateKillsPerHour': ('B11 unplugged process deaths per hour', f"{unpl['deaths'] / unpl['hours']:.2f}" if unpl.get('hours') else None),
        'PhysBatteryFgsMahPerHour': ('B12 mAh per hour, FGS on', batt('on')),
        'PhysBatteryBgMahPerHour': ('B12 mAh per hour, FGS off', batt('off')),
        'PhysBatteryFgsBlocks': ('B12 complete/all blocks, FGS on', kn(BT['on']['complete'], BT['on']['blocks']) if 'on' in BT else None),
        'PhysBatteryBgBlocks': ('B12 complete/all blocks, FGS off', kn(BT['off']['complete'], BT['off']['blocks']) if 'off' in BT else None),
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
        rows.append(f"{NAMES[mode]} & {z['valid']}/{z['attempted']} & {dur(st.median(d)) if d else 'held' if mode == 'bg_freezer' else 'n/a'} & "
                    f"{'[%s, %s]' % (dur(min(d)), dur(max(d))) if d else 'n/a'} & {z['before_thaw']}/{z['valid']}\\\\")
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
        rows = [f"SMS \\texttt{{\\_id}} reused after delete and insert & {NR if 'sms' in NOT_RUN else wil(*PF['sms'])}\\\\", f"second append in the same second leaves mtime & {wil(*PF['mtime'])}\\\\",
                'wall-clock rollback & ' + (f"{PF['clock']} records" if PF['clock'] else 'not run on this phone') + r'\\']
    table(gen, 'tab_phys_pitfalls.tex', 'Phone (B10): evidence pitfalls, trials affected out of trials (Wilson 95\\% interval). Clock changes are not allowed on this phone.',
          'lr', 'Pitfall & Trials affected', rows, 'B10 pitfall trials',
          extra=[r'SMS \texttt{\_id} reuse & %s\\' % NR] if 'sms' in NOT_RUN and not PF else [])

    F, rows = R['frozen'], []
    if F:
        rows = [f'Holds valid/run & {F["valid"]}/{F["run"]}\\\\', f'Stayed frozen & {F["stayed"]}\\\\', f'Killed & {F["died"]}\\\\', f'Changes & {F["changes"]}\\\\',
                f'Hold $\\geq$ (min) & {F["hold_min"]:.1f}\\\\', f'Lost sources & {F["lost"]}/{F["src"]}\\\\', f'Unseen last & {F["unseen"]}/{F["src"]}\\\\',
                f'Callbacks & {F["callbacks"]}\\\\', 'Restart-aware miss & %d/%d/%d\\\\' % tuple(F['evr'])]
    table(gen, 'tab_phys_frozen.tex', 'Phone (B5): long frozen holds, same metrics as Table~\\ref{tab:frozen}; lost and unseen sources count holds that stayed frozen; last row: changed uses missed by restart-aware event-only at +2/+14/+120\\,s.',
          'lr', 'Metric & Phone', rows, 'B5 frozen holds')

    SL, rows = R['statelog'], []
    for plugged, lab in ((False, 'Unplugged'), (True, 'Charging')):
        z = SL.get(plugged)
        if z and z['all']:
            rows.append(f"{lab} & {z['hours']:.1f} & {z['samples']}/{z['all']} & {pct(z['alive'], z['samples'])} & {pct(z['frozen'], z['samples'])} & "
                        f"{pct(z['deep'], z['samples'])} & {z['deaths'] / z['hours']:.2f}\\\\")
    table(gen, 'tab_phys_statelog.tex', 'Phone (B11): client state over one day, one sample every 5\\,s; hours, readable/all samples, share of readable samples alive, frozen and in deep Doze, process deaths per hour. Charging time is separated.',
          'lrrrrrr', r'Power & Hours & Samples & Alive\,\% & Frozen\,\% & Deep idle\,\% & Deaths/h', rows, 'B11 state log')

    BT, rows = R['battery'], []
    for arm, lab in (('on', 'FGS running'), ('off', 'Background only')):
        z = BT.get(arm)
        if z:
            m = '%.1f [%.1f, %.1f]' % (st.mean(z['mah']), min(z['mah']), max(z['mah'])) if z['mah'] else 'n/a'
            rows.append(f"{lab} & {z['complete']}/{z['blocks']} & {z['hours']:.1f} & {m} & {'%.2f' % st.mean(z['lvl']) if z['lvl'] else 'n/a'}\\\\")
    table(gen, 'tab_phys_battery.tex', 'Phone (B12): screen-off drain over complete blocks (unplugged, wireless debugging), FGS running versus a plain background client; mean [min, max] mAh per hour from the charge counter and battery level points per hour.',
          'lrrrr', r'Arm & Blocks & Hours & mAh/h & Level/h', rows, 'B12 battery blocks')


def write(D, gen):
    macros, R, P = analyze(D)
    lines = ['% AUTO-GENERATED by artifact/physical/analyze_phys.py; do not edit',
             r'\providecommand{\PhysTBD}[1]{}\renewcommand{\PhysTBD}[1]{\textcolor{red}{TBD}}']
    lines.append(r'\newif\ifPhysCalllog\PhysCalllog%s' % ('false' if 'calllog' in R['not_run'] else 'true'))
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
        m, _ = write(empty, gen)
        tex = (gen / 'physical_macros.tex').read_text(encoding='utf-8')
        assert all(v is None for k, (_, v) in m.items() if k != 'PhysSmsReuse') and m['PhysSmsReuse'][1] == NR, 'no data: TBD everywhere, SMS not run'
        assert tex.count('\\PhysTBD{') == len(m) - 1 and '\\PhysCalllogtrue' in tex
        assert '\\renewcommand{\\PhysTBD}' in tex
        assert '%' not in tex.split('\n', 1)[1], 'a % in a macro would comment out the rest of its line'
        tabs = sorted(p.name for p in gen.glob('tab_phys_*.tex'))
        assert '(\\PhysTBD{B3 trials} trials)' in (gen / 'tab_phys_coverage.tex').read_text(encoding='utf-8')
        assert len(tabs) == 9 and all('\\PhysTBD{' in (gen / t).read_text(encoding='utf-8') for t in tabs), tabs

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
        # B2: two no-gap trials (callback 10 s after the change), one force-stop trial; a pilot trial stays out
        def gap(g, pid_late, ev_t, mem, evr):
            f = {'src': 'contacts', 'ev': 'KEEP', 'te': 'KEEP', 'lm': 'CHANGED', 'lme': 'CHANGED', 'evr': evr, 'mem': mem, 'truth': 'B', 'refresh_ns': 2000000}
            dec = lambda t, ev: {'t_dec': t, 'fg': False, 'pid': pid_late, 'facts': {'c.dana': f}, 'events': ev, 'last_start': {},
                                 'lm_cost': {'contacts': {'ns': 2000000}, 'probe_contacts': 1000000}}
            ev = [{'src': 'contacts', 't': ev_t}] if ev_t else []
            return {'gap': g, 'protocol': 'v3', 'fg': False, 'trial': 0, 't_obs': 0, 't_gap_start': 100, 'hold': 5, 'pid_obs': 7,
                    'muts': [{'src': 'contacts', 'kind': 'update', 't_pre': 1000, 't_dev': 1000}], 'early': dec(7000, []), 'late': dec(19000, ev)}
        add('gaps', 'gaps-none-1100.jsonl', gap('none', 7, 11000, 'A', 'KEEP'), gap('none', 7, 11040, 'A', 'KEEP'))
        add('gaps', 'gaps-forcestop-1130.jsonl', gap('forcestop', 8, None, 'A', 'REFRESH'))
        add('gaps', 'gaps-pilot-none-0800.jsonl', gap('none', 7, 30000, 'A', 'KEEP'))
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
        add('b0', 'b0-probe-0600.jsonl', {'probe': 'identity', 'ok': True, 'detail': {'ro.build.version.release': '15', 'ro.build.version.sdk': '35'}})
        # B11: 4 unplugged samples (one frozen, one death then restart), 1 charging sample
        smp = lambda i, alive, pid, frozen, plugged=False: {'kind': 'sample', 'i': i, 't': i * 5.0, 'alive': alive, 'pid': pid, 'frozen': frozen,
                                                            'doze_deep': 'IDLE' if i == 1 else 'ACTIVE', 'plugged': plugged}
        add('statelog', 'statelog-0700.jsonl', {'kind': 'start', 'period_s': 5}, smp(0, True, '1', '0'), smp(1, True, '1', '1'), smp(2, False, None, None),
            smp(3, True, '2', '0'), smp(4, True, '2', '0', True))
        # B12: FGS on 4 mAh/h over two complete blocks, off 2 mAh/h; an incomplete block is ignored
        blk = lambda arm, drop, complete=True: {'kind': 'block', 'arm': arm, 'complete': complete, 'duration_s': 3600, 'charge_start_uAh': 3000000,
                                                'charge_end_uAh': 3000000 - drop, 'level_start': 90, 'level_end': 89}
        add('battery', 'battery-night1-2300-samples.jsonl', blk('on', 4000), blk('on', 4000), blk('off', 2000), blk('off', 9000, False))

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
        assert v['PhysSmsReuse'] == NR and v['PhysMtimeSame'] == '0/1'
        assert v['PhysFrozenHolds'] == 2 and v['PhysFrozenKilled'] == '1/2' and v['PhysFrozenLastUnseen'] == '0/2'
        assert v['PhysStateHours'] == '0.0' and v['PhysStateFrozenPct'] == '25' and v['PhysStateAlivePct'] == '75', (v['PhysStateFrozenPct'], v['PhysStateAlivePct'])
        assert v['PhysStateDozePct'] == '25' and v['PhysStateKillsPerHour'] == '180.00', v['PhysStateKillsPerHour']
        assert v['PhysBatteryFgsMahPerHour'] == '4.0' and v['PhysBatteryBgMahPerHour'] == '2.0' and v['PhysBatteryBgBlocks'] == '1/2'
        assert P['deploy'][('contacts', 'fg')]['valid'] == 1 and P['records'] == {'deploy': 1, 'gaps': 1}
        assert v['PhysEvidBound'] == 'phone' and v['PhysEvidWeak'] == 'phone' and v['PhysEvidCheap'] == 'phone' and v['PhysHostTrials'] is None   # B2 without B6 suffices
        assert v['PhysCostGl'] == '2' and v['PhysCostLm'] == '5' and v['PhysCostN'] == 3 and v['PhysCostLmCi'] == '[5, 5]', (v['PhysCostGl'], v['PhysCostLm'])
        nocost = dict(D, gaps=[dict(r, late={k: x for k, x in r['late'].items() if k != 'lm_cost'}) for r in D['gaps']])
        m, _ = write(nocost, gen); w = {k: x for k, (_, x) in m.items()}
        assert w['PhysEvidCheap'] is None and w['PhysCostGl'] is None and w['PhysGapTrials'] == '3/3', 'B2 without cost numbers must not claim phone evidence'
        add('host', 'host-X-1400.jsonl', {'case': 'none', 'arms': {}}, {'case': 'one', 'error': 'adb lost'})
        m, _ = write(D, gen); v = {k: x for k, (_, x) in m.items()}
        assert v['PhysEvidCheap'] == 'phone' and v['PhysHostTrials'] == 1
        tab = lambda n: (gen / n).read_text(encoding='utf-8')
        assert '\\mgroup{5}{MediaStore}' in tab('tab_phys_deploy.tex') and tab('tab_phys_deploy.tex').count('Foreground service') == 2
        assert 'Force-stop & 1/1' in tab('tab_phys_gaps.tex') and '1/1 & 0/1 & 0/1 & 1/1 & 0/1 & 0/1' in tab('tab_phys_gaps.tex') and 'not run on this phone' in tab('tab_phys_pitfalls.tex') and NR in tab('tab_phys_pitfalls.tex')
        assert not any('\\PhysTBD{' in tab(t) for t in tabs), [t for t in tabs if '\\PhysTBD{' in tab(t)]
        # B0 says the call log runs: call-log macros and B9 are computed (latest B0 record wins)
        add('b0', 'b0-probe-0600.jsonl', {'probe': 'user_info', 'ok': True, 'excluded_sources': ['sms', 'calllog'], 'detail': {}})
        add('b0', 'b0-probe-0700.jsonl', {'probe': 'user_info', 'ok': True, 'excluded_sources': ['sms'], 'detail': {}})
        m, _ = write(D, gen); v = {k: x for k, (_, x) in m.items()}
        assert v['PhysDeployCalllogFgMedian'] == '6\\,ms' and v['PhysBoundaryTrials'] == 3 and v['PhysSmsReuse'] == NR
        assert '\\PhysCalllogtrue' in tab('physical_macros.tex') and 'Call log' in tab('tab_phys_deploy.tex') and NR not in tab('tab_phys_boundary.tex')
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
    print('analyze_phys self-check ok')


if __name__ == '__main__':
    if '--self-check' in sys.argv:
        self_check()
    else:
        res = ROOT / 'artifact/results'
        m, P = write({k: load(res, p) for k, p in FILES.items()}, ROOT / 'manuscript/generated')
        print(json.dumps({'macros': len(m), 'tbd': sum(v is None for _, v in m.values()), 'pilot_records': P['records'], 'pilot_deploy': summary(P['deploy'])}))
