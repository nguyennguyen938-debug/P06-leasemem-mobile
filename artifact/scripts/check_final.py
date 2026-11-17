#!/usr/bin/env python3
"""Final gate before submission: fail while manuscript/main.pdf still shows a TBD placeholder (red \\PhysTBD).

Reads the PDF text with pypdf, or pdftotext when pypdf is missing. Usage: python scripts/check_final.py [file.pdf]
Exit 1 lists every page that contains TBD.
"""
import re, shutil, subprocess, sys
from pathlib import Path

PDF = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2] / 'manuscript/main.pdf'


def pages(pdf):
    try:
        from pypdf import PdfReader
        return [p.extract_text() or '' for p in PdfReader(str(pdf)).pages]
    except ImportError:
        if not shutil.which('pdftotext'):
            sys.exit('check_final: need pypdf or pdftotext')
        return subprocess.run(['pdftotext', '-layout', '-enc', 'UTF-8', str(pdf), '-'], capture_output=True, text=True, encoding='utf-8', check=True).stdout.split('\f')


def main():
    hits = [(i + 1, len(re.findall(r'\bTBD\b', t))) for i, t in enumerate(pages(PDF))]
    hits = [(p, n) for p, n in hits if n]
    if hits:
        print('FAIL: %s shows TBD %d times on pages %s' % (PDF.name, sum(n for _, n in hits), ', '.join(str(p) for p, _ in hits)))
        sys.exit(1)
    print('OK: no TBD in %s' % PDF.name)


if __name__ == '__main__':
    main()
