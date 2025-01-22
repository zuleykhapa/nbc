'''
We would like to run benchmarks in comparison of `current main` with `a week ago main`, 
`current main` with `current v1.2-histrionicus`,
`current v1.2-histrionicus` with `a week ago v1.2-histrionicus`.

This script creates a `pairs.json` file containing the values we need to run regression tests
in pairs of `--old` and `--new` passing respectful values to the `regression_runner`.

Contents of the `pairs.json` should look like this:
[
    {
        "new_name": "main",
        "new_sha": "latest main SHA",
        "old_name": "main",
        "old_sha": "a week ago main SHA"
    },
    {
        "new_name": "main",
        "new_sha": "latest main SHA",
        "old_name": "v1.2-histrionicus",
        "old_sha": "latest v1.2-histrionicus SHA"
    },
    {
        "new_name": "v1.2-histrionicus",
        "new_sha": "latest v1.2-histrionicus SHA",
        "old_name": "v1.2-histrionicus",
        "old_sha": "a week ago v1.2-histrionicus SHA"
    }
]
'''

import subprocess
import json
import os
import re
from collections import defaultdict

PAIR_FILE = "pairs.json"
TXT_FILE = "duckdb_curr_version_main.txt"

def main():
    pairs = []
    no_files = False
    old_highest_version_sha = None
    # find a file on runner duckdb_curr_version_main.txt or pairs.json to get previous run SHA
    parent_dir = os.path.dirname(os.getcwd())
    pairs_file_path = os.path.join(parent_dir, PAIR_FILE)
    txt_file_path = os.path.join(parent_dir, TXT_FILE)
    if os.path.isfile(txt_file_path):
        with open(txt_file_path, "r") as f:
            old_main_sha = f.read()
        subprocess.run(["bash", "rm", txt_file_path])
    if os.path.isfile(pairs_file_path):
        with open(pairs_file_path, "r") as f:
            data = f.read()
            parsed_data = json.loads(data)
            # there could be from 1 to 3 json objects
            visited = -1
            for data in parsed_data:
                if data["new_name"] == "main" and visited != 0:
                    visited = 0
                    old_main_sha = data["new_sha"]
                if data["new_name"].startswith("v") and visited != 1:
                    visited = 1
                    old_highest_version_sha = data["new_sha"]
    else:
        print(f"`duckdb_curr_version_main.txt` or `pairs.json` not found in { parent_dir }")
        no_files = True
    # fetch current versions and names
    command = [ "git", "ls-remote", "--heads", "https://github.com/duckdb/duckdb.git" ]
    try:
        branches = subprocess.run(command, capture_output=True).stdout
    except subprocess.CalledProcessError as e:
        print(f"Command failed with error: { e.stderr }")
    branches = branches.decode().splitlines()

    main_sha, main_name = None, None
    highest_version_sha, highest_version_name = None, None
    highest_version = -1
    for branch in branches:
        sha, name = branch.split()
        name = name.split("/")[2] # get only the last word of 'refs/heads/main'
        if name == 'main':
            main_sha, main_name = sha, name
        # finding the version name with highest version number
        match = re.match(r'v(\d+)\.(\d+)-', name)
        if match:
            version_number = int(match.group(1)) * 100 + int(match.group(2)) # in case there is a version like 1.12
            if version_number > highest_version:
                highest_version = version_number
                highest_version_sha, highest_version_name = sha, name

    if main_sha and no_files:
        # a very first pair - if the new machine `curr-main` & `curr-main`
        pairs.append({
            "new_name": f"{ main_name }",
            "new_sha": f"{ main_sha }",
            "old_name": f"{ main_name }",
            "old_sha": f"{ main_sha }"
        })
    else:
        if main_sha and old_main_sha:
            # first pair - `curr-main` & `old-main`
            pairs.append({
                "new_name": f"{ main_name }",
                "new_sha": f"{ main_sha }",
                "old_name": f"{ main_name }",
                "old_sha": f"{ old_main_sha }"
            })
        if highest_version_sha:
            # second pair - `curr-main` & `curr-vx.y`
            pairs.append({
                "new_name": f"{ main_name }",
                "new_sha": f"{ main_sha }",
                "old_name": f"{ highest_version_name }",
                "old_sha": f"{ highest_version_sha }"
            })
            if old_highest_version_sha:
                # third pair - `curr-vx.y` & `old-vx.y`
                pairs.append({
                    "new_name": f"{ highest_version_name }",
                    "new_sha": f"{ highest_version_sha }",
                    "old_name": f"{ highest_version_name }",
                    "old_sha": f"{ old_highest_version_sha }"
                })

    # write to json file
    with open(pairs_file_path, "w") as f:
        json.dump(pairs, f, indent=4)

if __name__ == "__main__":
    main()