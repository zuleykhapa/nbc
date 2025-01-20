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
        "new_sha": "0024e5d4beba0185733df68642775e3f38e089cb"
        "old_name": "v1.2-histrionicus",
        "old_sha": "c4f1a4e9fa5ba021c2f3fb72afa30c1d3c5ee7b0",
    }
]
'''

import subprocess
import json
import os
import re
from collections import defaultdict

def main():
    pairs = []
    old_highest_version_sha = None
    # find a file on runner duckdb_curr_version_main.txt or pairs.json to get previous run SHA
    parent_dir = os.path.dirname(os.getcwd())
    pair_file_path = os.path.join(parent_dir, "duckdb_previous_version_pairs.json")
    txt_file_path = os.path.join(parent_dir, "duckdb_curr_version_main.txt")
    if os.path.isfile(txt_file_path):
        with open(txt_file_path, "r") as f:
            old_main_sha = f.read()
    if os.path.isfile(pair_file_path):
        print("HERE")
        with open(pair_file_path, "r") as f:
            data = f.read()
            parsed_data = json.loads(data)
            old_main_sha = parsed_data[1]["new_sha"]
            old_highest_version_sha = parsed_data[1]["old_sha"]   
    else:
        print("`duckdb_curr_version_main.txt` or `duckdb_previous_version_pairs.json` not found")
    # fetch current versions and names
    command = [ "git", "ls-remote", "--heads" ]
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
    # first pair - `curr-main` & `old-main`
    if main_sha and old_main_sha:
        print(f"Main branch: { main_name } with SHA { main_sha }")
        pairs.append({
            "new_name": f"curr-{ main_name }",
            "new_sha": f"{ main_sha }",
            "old_name": f"old-{ main_name }",
            "old_sha": f"{ old_main_sha }"
        })

    if highest_version_sha:
        # second pair - `curr-main` & `curr-vx.y`
        pairs.append({
            "new_name": f"curr-{ main_name }",
            "new_sha": f"{ main_sha }",
            "old_name": f"curr-{ highest_version_name }",
            "old_sha": f"{ highest_version_sha }"
        })
        if old_highest_version_sha:
            # third pair - `curr-vx.y` & `old-vx.y`
            pairs.append({
                "new_name": f"curr-{ highest_version_name }",
                "new_sha": f"{ highest_version_sha }",
                "old_name": f"old-{ highest_version_name }",
                "old_sha": f"{ old_highest_version_sha }"
            })

    # write to `pairs.json` file
    with open("pairs.json", "w") as f:
        json.dump(pairs, f, indent=4)

if __name__ == "__main__":
    main()