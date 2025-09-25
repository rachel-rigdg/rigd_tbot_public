#!/usr/bin/env python3
import io, os, re, sys
FUTURE_LINE = "from __future__ import annotations\n"
SHEBANG_RE = re.compile(r'^#!')
ENCODING_RE = re.compile(r'coding[:=]\s*([-\w.]+)')
TRIPLE_Q_RE = re.compile(r'^(?P<q>["\']{3})')
def already_has_future(lines):
    for line in lines[:15]:
        if line.strip().startswith("from __future__ import annotations"):
            return True
    return False
def find_docstring_end(lines, start_idx):
    opener = lines[start_idx].lstrip()[:3]
    q = opener
    if lines[start_idx].count(q) >= 2:
        return start_idx + 1
    i = start_idx + 1
    while i < len(lines):
        if q in lines[i]:
            return i + 1
        i += 1
    return start_idx + 1
def insert_future(text):
    lines = text.splitlines(keepends=True)
    if already_has_future(lines):
        return None
    i = 0
    if i < len(lines) and SHEBANG_RE.match(lines[i]):
        i += 1
    if i < len(lines) and ENCODING_RE.search(lines[i]):
        i += 1
    elif i == 0 and len(lines) > 1 and ENCODING_RE.search(lines[0]):
        i = 1
    while i < len(lines) and (lines[i].strip() == "" or lines[i].lstrip().startswith("#")):
        i += 1
    if i < len(lines):
        stripped = lines[i].lstrip()
        if TRIPLE_Q_RE.match(stripped):
            i = find_docstring_end(lines, i)
    new_lines = lines[:i] + [FUTURE_LINE] + lines[i:]
    if not new_lines[-1].endswith("\n"):
        new_lines[-1] = new_lines[-1] + "\n"
    return "".join(new_lines)
def patch_file(path):
    try:
        with io.open(path, "r", encoding="utf-8") as f:
            original = f.read()
    except Exception:
        with io.open(path, "r", encoding="latin-1") as f:
            original = f.read()
    updated = insert_future(original)
    if updated is None:
        return False
    bak = path + ".bak"
    with io.open(bak, "w", encoding="utf-8") as f:
        f.write(original)
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(updated)
    return True
def main(paths):
    changed = 0
    for p in paths:
        if not p.endswith(".py"):
            continue
        if not os.path.isfile(p):
            continue
        if patch_file(p):
            print(f"patched: {p}")
            changed += 1
    print(f"\nDone. Files changed: {changed}")
    return 0
if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
