#!/usr/bin/env python3
"""Physical-phone results (plan C3) -> manuscript/generated/physical_macros.tex (+ tab_phys_*.tex when data exist).

Reads only artifact/results/physical-*/*.jsonl (append-only raw data from the experiment role). Every macro whose
data are missing renders \\PhysTBD{<what is missing>}, a red TBD; scripts/check_final.py fails while the PDF shows one.
Schema: PHYS-PROTOCOL.md sections 7 and 10 (emulator schema plus device, fingerprint, rooted, plugged). Only B1
(deploy*.jsonl, record shape of followup/deployment.py plus `source`) is computed so far; other macros stay TBD.
B1 pilot files (deploy-pilot-*) are summarized on stdout to check the pipeline and never enter macros or tables.
Run `python physical/analyze_phys.py --self-check` for the built-in check.
"""
import json, statistics as st, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NAMES = {'bg_unfrozen': 'Background, unfrozen', 'bg_freezer': 'Background, frozen', 'fg': 'Foreground service',
         'assistant': 'Bound assistant'}
SOURCES = {'contacts': 'Contacts', 'media': 'MediaStore', 'calllog': 'Call log'}


def load(res, pattern):
    """All records of one experiment, with the file name; nothing is rewritten."""
    return [dict(json.loads(l), _file=p.name) for p in sorted(res.glob('physical-*/' + pattern))
            for l in p.read_text(encoding='utf-8').splitlines() if l.strip()]


def dur(ms):
    return f'{ms / 1000:.1f}\\,s' if ms >= 1000 else f'{ms:.0f}\\,ms'


def deploy(rows):
    """B1: callback delay per (source, deployment); same validity rule as followup/analyze.py.
    A callback counts only for the trial's own `source` (records without it are emulator-schema Contacts trials)."""
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


def device(rows, key):
    vals = sorted({str(r[key]) for r in rows if r.get(key) is not None})
    return ', '.join(vals) if vals else None


# name -> (experiment file pattern, what the number is, function of the records or None until S1)
def pilot(name):
    return name.startswith('deploy-pilot-')


def registry(res):
    rows = load(res, 'deploy*.jsonl')
    B1 = deploy([r for r in rows if not pilot(r['_file'])])
    P1 = deploy([r for r in rows if pilot(r['_file'])])
    allrows = load(res, '*.jsonl')
    med = lambda s, m: dur(st.median(B1[s, m]['delays_ms'])) if (s, m) in B1 and B1[s, m]['delays_ms'] else None
    frozen = B1.get(('contacts', 'bg_freezer'))
    return {
        'PhysDevice': ('device model', device(allrows, 'device')),
        'PhysFingerprint': ('build fingerprint', device(allrows, 'fingerprint')),
        'PhysRooted': ('root status', {'True': 'rooted', 'False': 'not rooted'}.get(device(allrows, 'rooted') or '', None)),
        'PhysDeployTrials': ('B1 valid/attempted trials, all sources', f"{sum(z['valid'] for z in B1.values())}/{sum(z['attempted'] for z in B1.values())}" if B1 else None),
        'PhysDeployBgMedian': ('B1 Contacts background unfrozen median callback delay', med('contacts', 'bg_unfrozen')),
        'PhysDeployFgMedian': ('B1 Contacts FGS median callback delay', med('contacts', 'fg')),
        'PhysDeployAssistMedian': ('B1 Contacts bound assistant median callback delay', med('contacts', 'assistant')),
        'PhysDeployFrozenBeforeThaw': ('B1 Contacts frozen trials with a callback before thaw', f"{frozen['before_thaw']}/{frozen['valid']}" if frozen else None),
        'PhysDeployMediaBgMedian': ('B1 MediaStore background unfrozen median callback delay', med('media', 'bg_unfrozen')),
        'PhysDeployMediaFgMedian': ('B1 MediaStore FGS median callback delay', med('media', 'fg')),
        'PhysDeployCalllogBgMedian': ('B1 call log background unfrozen median callback delay', med('calllog', 'bg_unfrozen')),
        'PhysDeployCalllogFgMedian': ('B1 call log FGS median callback delay', med('calllog', 'fg')),
        'PhysCoverageTrials': ('B3 candidate-stamp trials', None),
        'PhysGapTrials': ('B2 gap trials', None),
        'PhysGapNoneFcl': ('B2 no-gap median first callback', None),
        'PhysRaceTrials': ('B4 anchoring-race trials', None),
        'PhysRaceStale': ('B4 stale anchors', None),
        'PhysBoundaryTrials': ('B9 boundary trials', None),
        'PhysCteMs': ('B9 median check-to-effect interval', None),
        'PhysSmsReuse': ('B10 SMS id reuse trials', None),
        'PhysMtimeSame': ('B10 same-second mtime trials', None),
        'PhysFrozenHolds': ('B5 frozen holds', None),
        'PhysFrozenKilled': ('B5 holds ended by a kill', None),
        'PhysStateHours': ('B11 logged hours', None),
        'PhysStateFrozenPct': ('B11 share of time frozen', None),
        'PhysStateKillsPerHour': ('B11 kills per hour', None),
        'PhysBatteryFgsMahPerHour': ('B12 mAh per hour, FGS on', None),
        'PhysBatteryBgMahPerHour': ('B12 mAh per hour, FGS off', None),
    }, B1, P1


def summary(B):
    """One line per (source, mode): valid/attempted, median delay; used for the pilot check on stdout."""
    return {f'{s}/{m}': f"{z['valid']}/{z['attempted']} valid, median {st.median(z['delays_ms']) if z['delays_ms'] else None} ms"
            for (s, m), z in B.items()}


def write(res, gen):
    macros, B1, P1 = registry(res)
    lines = ['% AUTO-GENERATED by artifact/physical/analyze_phys.py; do not edit',
             r'\providecommand{\PhysTBD}[1]{}\renewcommand{\PhysTBD}[1]{\textcolor{red}{TBD}}']
    for name, (what, val) in macros.items():
        lines.append('\\newcommand{\\%s}{%s\\xspace}' % (name, val if val is not None else '\\PhysTBD{%s}' % what))
    (gen / 'physical_macros.tex').write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
    tab = gen / 'tab_phys_deploy.tex'
    if B1:
        rows, last = [], None
        for (src, mode), z in B1.items():
            if src != last:
                rows.append(r'\mgroup{5}{%s}' % SOURCES[src]); last = src
            d = z['delays_ms']
            rows.append(f"{NAMES[mode]} & {z['valid']}/{z['attempted']} & {dur(st.median(d)) if d else 'held' if mode == 'bg_freezer' else 'n/a'} & "
                        f"{'[%s, %s]' % (dur(min(d)), dur(max(d))) if d else 'n/a'} & {z['before_thaw']}/{z['valid']}\\\\")
        tab.write_text('\n'.join([r'\begin{table}[t]', r'\centering\mtab',
            r"\caption{Physical phone (B1): callbacks per source and deployment, counted only for the trial's own source; valid/attempted trials, median and range of the delay, trials with a callback before thaw. Pilot trials are excluded.}",
            r'\label{tab:phys-deploy}', r'\begin{tabular}{lrrrr}\toprule', r'\mhead Deployment & Trials & Median & Range & Before thaw\\\midrule',
            *rows, r'\bottomrule\end{tabular}', r'\end{table}']) + '\n', encoding='utf-8', newline='\n')
    elif tab.exists():
        tab.unlink()
    return macros, P1


def self_check():
    with tempfile.TemporaryDirectory() as d:
        res, gen = Path(d) / 'results', Path(d) / 'gen'; res.mkdir(); gen.mkdir()
        m, _ = write(res, gen)
        tex = (gen / 'physical_macros.tex').read_text(encoding='utf-8')
        assert all(v is None for _, v in m.values()) and tex.count('\\PhysTBD{') == len(m), 'no data must give TBD everywhere'
        assert '\\renewcommand{\\PhysTBD}' in tex and not (gen / 'tab_phys_deploy.tex').exists()
        day = res / 'physical-20261120'; day.mkdir()
        def ok(mode, frozen, t, src=None, ev=None):
            r = {'mode': mode, 'device': 'Pixel X', 'rooted': False, 'before': {'frozen': frozen}, 'states': [{'frozen': frozen}],
                 'mutation': {'t_pre': 1000}, 'memory_before_thaw': {'events': [{'src': ev or src or 'contacts', 't': t}] if t else []}}
            return dict(r, source=src) if src else r   # no `source`: emulator-schema Contacts trial
        recs = [ok('bg_unfrozen', '0', 11000), ok('bg_unfrozen', '0', 11040), ok('bg_unfrozen', '1', 11000),  # 3rd: wrong state, excluded
                ok('bg_freezer', '1', None), {'mode': 'fg', 'error': 'adb lost'}]
        (day / 'deploy-contacts-0900.jsonl').write_text('\n'.join(map(json.dumps, recs)) + '\n')
        # Media and call-log trials with fast callbacks of their own source, plus a stray Contacts event: none may reach Contacts.
        other = [ok('bg_unfrozen', '0', 1500, 'media'), ok('bg_unfrozen', '0', 1200, 'media', ev='contacts'),
                 ok('fg', '0', 1005, 'calllog'), ok('fg', '0', 1007, 'calllog')]
        (day / 'deploy-media-0930.jsonl').write_text('\n'.join(map(json.dumps, other[:2])) + '\n')
        (day / 'deploy-calllog-1000.jsonl').write_text('\n'.join(map(json.dumps, other[2:])) + '\n')
        # Pilot: a fast Contacts FGS trial that must stay out of every macro and the table.
        (day / 'deploy-pilot-contacts-0800.jsonl').write_text(json.dumps(ok('fg', '0', 1006, 'contacts')) + '\n')
        m, P = write(res, gen)
        assert m['PhysDeployBgMedian'][1] == '10.0\\,s', m['PhysDeployBgMedian']
        assert m['PhysDeployTrials'][1] == '7/9' and m['PhysDeployFrozenBeforeThaw'][1] == '0/1', m['PhysDeployTrials']
        assert m['PhysDevice'][1] == 'Pixel X' and m['PhysRooted'][1] == 'not rooted'
        assert m['PhysDeployFgMedian'][1] is None, 'pilot or call-log trials leaked into Contacts FGS'
        assert m['PhysDeployMediaBgMedian'][1] == '500\\,ms' and m['PhysDeployCalllogFgMedian'][1] == '6\\,ms'
        assert m['PhysDeployMediaFgMedian'][1] is None and m['PhysDeployCalllogBgMedian'][1] is None
        assert P[('contacts', 'fg')]['valid'] == 1 and ('contacts', 'fg') in P and len(P) == 1
        tab = (gen / 'tab_phys_deploy.tex').read_text(encoding='utf-8')
        assert '\\mgroup{5}{MediaStore}' in tab and '\\mgroup{5}{Call log}' in tab and tab.count('Foreground service') == 2
    print('analyze_phys self-check ok')


if __name__ == '__main__':
    if '--self-check' in sys.argv:
        self_check()
    else:
        m, P = write(ROOT / 'artifact/results', ROOT / 'manuscript/generated')
        print(json.dumps({'macros': len(m), 'tbd': sum(v is None for _, v in m.values()), 'pilot_deploy': summary(P)}))
