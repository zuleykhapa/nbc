import duckdb
import argparse
import pandas
import tabulate
import sys
import re
import random
import os
# import string
import subprocess
import docker

parser = argparse.ArgumentParser()
# parser.add_argument("file_name")
parser.add_argument("--nightly_build")
parser.add_argument("--platform")
parser.add_argument("--architecture")
parser.add_argument("--run_id")
parser.add_argument("--runs_on")
parser.add_argument("--config")

# parser.add_argument("--url")
args = parser.parse_args()

# file_name = args.file_name
nightly_build = args.nightly_build
platform = args.platform # linux
architecture = args.architecture # linux-amd64
run_id = args.run_id
runs_on = args.runs_on
# url = args.url
config = args.config

def list_extensions(config) :
    with open(config, "r") as file:
        content = file.read()

    # Adjusted regex for matching after `load(`
    pattern = r"duckdb_extension_load\(\s*([^\s,)]+)"
    matches = re.findall(pattern, content)
    return matches

# VERIFY VERSION
# repo = "duckdb/duckdb"

# if architecture.count("aarch64"):
#     name=architecture
# else:
#     name=platform

# gh_command = [
#     "gh", "run", "download",
#     run_id,
#     "--repo", repo,
#     "--name", f"duckdb-binaries-{ name }"
# ]
# result = subprocess.run(gh_command, check=True, text=True, capture_output=True)

# # subprocess.run()

# print(result)

# TEST ISTANLLING AND LOADING EXTENSIONS
if nightly_build == 'Windows':
    duckdb='./duckdb.exe'
else:
    duckdb='./duckdb'

action=["INSTALL", "LOAD"]
extensions=list_extensions(config)
print(extensions)
file_name = "issue_ext_{}.txt".format(nightly_build)
counter = 0

for ext in extensions:
    # try:
    print(architecture)
    if architecture.count("aarch64"):
        select_installed = [
            "docker", "run", "--rm", "--platform", "linux/aarch64",
            "-v", f"{ os.getcwd() }/duckdb:/duckdb",
            "-e", f"ext={ ext }"
            "ubuntu:22.04", "/bin/bash", "-c", 
            f"./duckdb -c 'SELECT installed FROM duckdb_extensions() WHERE extension_name={ ext }';"
        ]
    else:
        select_installed = [
            duckdb,
            "-csv",
            "-noheader",
            "-c",
            f"SELECT installed FROM duckdb_extensions() WHERE extension_name='{ ext }';"
        ]

    result=subprocess.run(select_installed, check=True, text=True, capture_output=True)
    is_installed = result.stdout.strip()
    if is_installed == 'false':
        for act in action:
            print(f"{ act }ing { ext }...")
            if architecture.count("aarch64"):
                install_ext = [
                    "docker", "run", "--rm", "--platform", "linux/aarch64",
                    "-v", f"{ os.getcwd() }/duckdb:/duckdb",
                    "-e", f"ext={ ext }"
                    "ubuntu:22.04", "/bin/bash", "-c", f"./duckdb -c '{ act } { ext };'"
                ]
            else:
                install_ext = [
                    duckdb,
                    "-c",
                    f"{ act } '{ ext }';"
                ]
            try:
                subprocess.run(install_ext, check=True, text=True, capture_output=True)

                print(act, ext, ": ", is_installed)
            except subprocess.CalledProcessError as e:
                with open(file_name, 'a') as f:
                    if counter == 0:
                        f.write(f"nightly_build,architecture,runs_on,version,extension,failed_statement\n")
                        counter += 1
                    f.write(f"{nightly_build },{ architecture },{ runs_on },,{ ext },{ act }\n")
                print(f"Error running command for extesion { ext }: { e }")
                print(f"stderr: { e.stderr }")


# create a Markdown report file
import prepare_report
prepare_report.report(file_name, platform, "url")