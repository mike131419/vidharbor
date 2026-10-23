"""Turn a failed Gradle build log into one GitHub Actions error annotation.

Annotations are visible on the workflow run (and through the public API),
so build problems can be read without downloading logs.
"""
import re
import sys

PATTERNS = [
    re.compile(r'^e: '),                       # Kotlin compiler errors
    re.compile(r'error:', re.I),               # javac / AAPT / resource errors
    re.compile(r'^\s*> '),                      # Gradle "What went wrong" details
    re.compile(r'What went wrong'),
    re.compile(r'^FAILURE:'),
    re.compile(r'Unresolved reference|Type mismatch|Duplicate resources|Could not resolve'),
]


def main(path: str) -> None:
    try:
        lines = open(path, encoding='utf-8', errors='replace').read().splitlines()
    except OSError:
        print('::error title=Build failed::(no build log)')
        return
    picked, seen = [], set()
    for line in lines:
        if any(p.search(line) for p in PATTERNS):
            text = line.strip()[:400]
            if text and text not in seen:
                seen.add(text)
                picked.append(text)
    if not picked:
        picked = [l.strip()[:400] for l in lines[-40:] if l.strip()]
    msg = '%0A'.join(t.replace('%', '%25').replace('\r', '') for t in picked[:80])
    print(f'::error title=Build failed::{msg}')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'build.log')
