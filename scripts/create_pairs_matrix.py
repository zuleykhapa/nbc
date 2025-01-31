'''
We would like to run benchmarks comparing 
    - `current main` with `a week ago main`, (1)
    - `current version of the highest release` with `a week ago version of the highest release` (2),
    - `current main` with 
        `current version of the highest release` and (3)
        `current version of the previous release` (4)

The script finds highest and previous versions in current heads (`git ls-remote --heads`) and create last pairs (3), (4) from it.
It takes "new_sha" for `main` and for `highest release` in previous version of json file and creates pairs (1), (2).
It doesn't create pair (2), when there is no "new_sha" for `highest release` in previous version of json file.
In the end it writes pairs to `duckdb_previous_version_pairs.json` file. The file is used to create a matrix for regression tests run.

Contents of the `duckdb_previous_version_pairs.json` look like this:
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
    },
    {
        "new_name": "main",
        "new_sha": "latest main SHA",
        "old_name": "v1.1-eatoni",
        "old_sha": "latest v1.1-eatoni SHA"
    }
]
Names in pairs are starting with "old" and "new" because we use `--old` and `--new` to pass values to the `regression_runner`
'''

import subprocess
import json
import os
import re
from collections import defaultdict

PAIR_FILE = "duckdb_previous_version_pairs.json"
TXT_FILE = "duckdb_curr_version_main.txt"
PARENT_DIR = os.path.dirname(os.getcwd())
PAIRS_FILE_PATH = os.path.join(PARENT_DIR, PAIR_FILE)

def maybe_remove_txt_file():
    txt_file_path = os.path.join(PARENT_DIR, TXT_FILE)
    if os.path.isfile(txt_file_path):
        with open(txt_file_path, "r") as f:
            old_main_sha = f.read()
        os.remove(txt_file_path)
        return old_main_sha

def get_pairs_from_file():
    if os.path.isfile(PAIRS_FILE_PATH):
        with open(PAIRS_FILE_PATH, "r") as f:
            data = f.read()
            if len(data):
                parsed_data = json.loads(data)
                return parsed_data
            else:
                print(f"""
                `duckdb_previous_version_pairs.json` file found in { PARENT_DIR } but it's empty.
                """)
                return None        
    else:
        print(f"""
        `duckdb_previous_version_pairs.json` not found in { PARENT_DIR }.
        A new duckdb_previous_version_pairs.json will be created in a parent directory.
        """)
        return None

def get_branches():
    command = [ "git", "ls-remote", "--heads", "https://github.com/duckdb/duckdb.git" ]
    try:
        branches = subprocess.run(command, capture_output=True).stdout
    except subprocess.CalledProcessError as e:
        print(f"Command failed with error: { e.stderr }")
    return branches.decode().splitlines()

def get_highest_and_previous(branches):
    branches_parsed = {}
    main_sha, main_name = None, None
    previous_version_sha, previous_version_name = None, None
    highest_version_sha, highest_version_name = None, None
    highest_version = ''
    for branch in branches:
        sha, name = branch.split()
        name = name.split("/")[-1]
        if name == 'main':
            main_sha, main_name = sha, name
            branches_parsed["main"] = (name, sha)
        else:
            match = re.match(r'v(.*)-', name)
            if match:
                version_number = match.group(1)
                if version_number > highest_version:
                    previous_version_sha, previous_version_name = highest_version_sha, highest_version_name
                    previous_version = highest_version
                    highest_version_sha, highest_version_name = sha, name
            branches_parsed["highest_version"] = (highest_version_name, highest_version_sha)
            branches_parsed["previous_version"] = (previous_version_name, previous_version_sha)
            
    return branches_parsed

def get_pairs():
    pairs = []
    branches = get_branches()
    if len(branches):
        branches_parsed = get_highest_and_previous(branches)
        main_name, main_sha = branches_parsed["main"]
        for key in ["highest_version", "previous_version"]:
            old_name, old_sha = branches_parsed[key]
            pairs.append({
                "new_name": main_name,
                "new_sha": main_sha,
                "old_name": old_name,
                "old_sha": old_sha
            })
    pairs_data = get_pairs_from_file()
    if pairs_data:
        for pair in pairs_data:
            name, sha = branches_parsed["main"]
            pairs.append({
                    "new_name": name,
                    "new_sha": sha,
                    "old_name": name,
                    "old_sha": pair["new_sha"]
                })
            break
        for pair in pairs_data:
            highest_name, highest_sha = branches_parsed["highest_version"]
            if highest_name == pair["old_name"]:
                pairs.append({
                        "new_name": highest_name,
                        "new_sha": highest_sha,
                        "old_name": highest_name,
                        "old_sha": pair["old_sha"]
                    })
            break
    else:
        old_main_sha = maybe_remove_txt_file()
        if old_main_sha:
            name, sha = branches_parsed["main"]
            pairs.append({
                    "new_name": name,
                    "new_sha": sha,
                    "old_name": name,
                    "old_sha": old_main_sha
                })
    return pairs

def main():
    pairs = get_pairs()
    with open(PAIRS_FILE_PATH, "w") as f:
        json.dump(pairs, f, indent=4)

if __name__ == "__main__":
    main()