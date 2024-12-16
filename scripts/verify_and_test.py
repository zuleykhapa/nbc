import argparse
import pandas
import tabulate
import sys
import re
import random
import os
import subprocess
import docker
# import prepare_report

parser = argparse.ArgumentParser()
# parser.add_argument("file_name")
parser.add_argument("duckdb_path")
parser.add_argument("--nightly_build")
parser.add_argument("--platform")
parser.add_argument("--architecture")
parser.add_argument("--run_id")
parser.add_argument("--runs_on")
parser.add_argument("--config")

# parser.add_argument("--url")
args = parser.parse_args()

duckdb_path = args.duckdb_path # duckdb_path/ducldb or duckdb_path/duckdb.exe
nightly_build = args.nightly_build
platform = args.platform # linux
architecture = args.architecture # linux-amd64
run_id = args.run_id
runs_on = args.runs_on # linux-latest
# url = args.url
config = args.config # ext/config/out_of_tree_extensions.cmake

def list_extensions(config) :
    with open(config, "r") as file:
        content = file.read()
    # Adjusted regex for matching after `load(`
    pattern = r"duckdb_extension_load\(\s*([^\s,)]+)"
    matches = re.findall(pattern, content)
    return matches

def verify_version(duckdb, repo, name):
    gh_headSha_command = [
        "gh", "run", "view",
        run_id,
        "--repo", repo,
        "--json", "headSha",
        "-q", ".headSha"
    ]
    full_sha = subprocess.run(gh_headSha_command, check=True, text=True, capture_output=True).stdout.strip()
    if architecture.count("aarch64"):
        pragma_version = [
            "docker", "run", "--rm", "--platform", "linux/aarch64",
            "-v", f"{ os.getcwd() }/duckdb:/duckdb",
            "-e", f"full_sha={ full_sha }"
            "ubuntu:22.04", "/bin/bash", "-c", 
            f"{ duckdb } --version"
        ]
    else:
        pragma_version = [
            f"{ duckdb }", "--version"
        ]
    short_sha = subprocess.run(pragma_version, check=True, text=True, capture_output=True).stdout.strip().split()[-1]
    if not full_sha.startswith(short_sha):
        print(f"The version of { nightly_build} build ({ short_sha }) doesn't match to the version triggered the build ({ full_sha }).\n")
        with open("res_{}.md".format(platform), 'w') as f:
            f.write(f"- The version of { nightly_build} build ({ short_sha }) doesn't match to the version triggered the build ({ full_sha }).\n")
        return
    print(f"The versions of { nightly_build} build match: ({ short_sha }) and ({ full_sha }).\n")

def test_extensions(duckdb, name):
    action=["INSTALL", "LOAD"]
    extensions=list_extensions(config)
    print(extensions)
    file_name = "issue_ext_{}.txt".format(nightly_build)
    counter = 0

    for ext in extensions:
        if architecture.count("aarch64"):
            select_installed = [
                "docker", "run", "--rm", "--platform", "linux/aarch64",
                "-v", f"{ os.getcwd() }/duckdb:/duckdb",
                "-e", f"ext={ ext }"
                "ubuntu:22.04", "/bin/bash", "-c", 
                f"{ duckdb } -c 'SELECT installed FROM duckdb_extensions() WHERE extension_name={ ext }';"
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
                        "ubuntu:22.04", "/bin/bash", "-c", f"./{ duckdb } -c '{ act } { ext };'"
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
                        f.write(f"{ nightly_build },{ architecture },{ runs_on },,{ ext },{ act }\n")
                    print(f"Error running command for extesion { ext }: { e }")
                    print(f"stderr: { e.stderr }")

def main():
    print(duckdb_path)
    if nightly_build == 'Windows':
        duckdb = duckdb_path
    else:
        ls_duckdb_path = os.listdir(duckdb_path)
        if ls_duckdb_path:
            duckdb = f"{ duckdb_path }/{ ls_duckdb_path[0] }"
            print(duckdb)
        else:
            print(f"No files found in the unzipped binaries.")
    repo = "duckdb/duckdb"
    if architecture.count("aarch64"):
        name=architecture
    else:
        name=platform

    verify_version(duckdb, repo, name)
    test_extensions(duckdb, name)

if __name__ == "__main__":
    main()