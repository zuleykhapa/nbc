import argparse
import json
import os
import glob
import sys
import string
import re
from pathlib import Path

VERSIONS = json.loads(sys.argv[1])
ISSUE_FILE = Path("issue_body.txt")

def construct_header(version):
    return f"""### Regression detected between {version['new_name']} and {version['old_name']}
Hash info:
|  | Branch | SHA |
|:-|:-------|:----|
| **NEW** | {version['new_name']} | {version['new_sha']} |
| **OLD** | {version['old_name']} | {version['old_sha']} |
#### List of regressed tests
"""



def extract_regressions(path):

    text = Path(path).read_text(encoding='utf-8', errors='ignore')
    pattern = re.compile(r"""
        ^=+\s*\n=+\s*REGRESSIONS\ DETECTED\s*=+\n=+\s*\n   # REGRESSIONS DETECTED header with separators
        (.*?)                                              # capture group
        (?=^=+\s*OTHER(?:\s+TIMINGS)?\s*=+)                # OTHER TIMINGS header with separators
    """, re.MULTILINE | re.DOTALL | re.VERBOSE | re.IGNORECASE)

    m = pattern.search(text)
    section_regressions = m.group(1).strip() if m else ""
    return section_regressions

def extract_benchmarks(version):
    pattern = f"regression_output_*_{version['new_name']}_{version['old_name']}.txt"
    files = Path('.').glob(pattern)
    new = re.escape(version['new_name'])
    old = re.escape(version['old_name'])
    rx = re.compile(rf"^regression_output_(?P<set>.+)_{new}_{old}\.txt$")
    found = set()
    for p in files:
        m = rx.match(p.name)
        if m:
            found.add(m.group("set"))
    return sorted(found)

regressions_found = False

for version in VERSIONS:
    SETS = extract_benchmarks(version)
    header_written = False
    for benchmark in SETS:
        path = f"regression_output_{benchmark}_{version['new_name']}_{version['old_name']}.txt"
        # find regressions in corresponding version
        regressions = extract_regressions(path)
        if not regressions:
            continue
        # if regressions detected add it under the header
        if not header_written:
            header = construct_header(version)
            with open("issue_body.txt", 'a') as f:
                f.write(header)
            header_written = True
        with open("issue_body.txt", 'a') as f:
            f.write(f"In **{benchmark}**:\n")
            f.write(regressions + '\n')
        regressions_found = True

gh_output = os.getenv("GITHUB_OUTPUT")
if gh_output:
    print(gh_output)
    with open(gh_output, 'a', encoding="utf-8") as f:
        f.write(f"regressions={'true' if regressions_found else 'false'}\n")
else:
    # local debug output
    print(f"regressions={'true' if regressions_found else 'false'}")
