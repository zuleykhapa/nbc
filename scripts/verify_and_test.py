import argparse
import docker
import glob
import os
import pandas
import random
import re
import subprocess
import sys
import tabulate
from shared_functions import fetch_data

GH_REPO = os.environ.get('GH_REPO', 'duckdb/duckdb')
ACTION = ["INSTALL", "LOAD"]

parser = argparse.ArgumentParser()
parser.add_argument("--nightly_build")
parser.add_argument("--platform")
parser.add_argument("--architecture")
parser.add_argument("--run_id")
parser.add_argument("--runs_on")
parser.add_argument("--config")

args = parser.parse_args()

nightly_build = args.nightly_build
platform = args.platform # linux
architecture = args.architecture if nightly_build == 'Python' else args.architecture.replace("-", "/") # linux-aarch64 => linux/aarch64 for docker
run_id = args.run_id
runs_on = args.runs_on # linux-latest
config = args.config # ext/config/out_of_tree_extensions.cmake

def list_extensions(config) :
    with open(config, "r") as file:
        content = file.read()
    # Adjusted regex for matching after `load(`
    pattern = r"duckdb_extension_load\(\s*([^\s,)]+)"
    matches = re.findall(pattern, content)
    return matches

def get_full_sha(run_id):
    gh_headSha_command = [
        "gh", "run", "view",
        run_id,
        "--repo", GH_REPO,
        "--json", "headSha",
        "-q", ".headSha"
    ]
    full_sha = subprocess.run(gh_headSha_command, check=True, text=True, capture_output=True).stdout.strip()
    return full_sha

def verify_version(tested_binary, file_name):
    full_sha = get_full_sha(run_id)
    tested_binary_path = f"{ tested_binary }:/duckdb"
    if architecture.count("aarch64") or architecture.count("arm64"):
        pragma_version = [
            "docker", "run", "--rm",
            "--platform", architecture,
            "-v", tested_binary_path,
            "ubuntu",
            "/bin/bash", "-c", f"/duckdb --version"
        ]
    else:
        pragma_version = [ tested_binary, "--version" ]
    try:
        result = subprocess.run(pragma_version, check=True, text=True, capture_output=True)
        short_sha = result.stdout.strip().split()[-1]
    except subprocess.CalledProcessError as e:
        print(f"Error: Command failed with exit code {e.returncode}")
        print(f"Command: {e.cmd}")
        print(f"Output: {e.output}")
        print(f"Error Output: {e.stderr}")
        raise

    if not full_sha.startswith(short_sha):
        print(f"""
        Version of { nightly_build } tested binary doesn't match to the version that triggered the build.\n
        - Version triggered the build: { full_sha }\n - Downloaded build version: { short_sha }\n
        """)
        with open(file_name, 'w') as f:
            f.write(f"""
            Version of { nightly_build } tested binary doesn't match to the version that triggered the build.\n
            - Version triggered the build: { full_sha }\n - Downloaded build version: { short_sha }\n
            """)
        return False
    print(f"""
    Versions of { nightly_build } build match: ({ short_sha }) and ({ full_sha }).\n
    - Version triggered the build: { full_sha }\n - Downloaded build version: { short_sha }\n
    """)
    return True

def test_extensions(tested_binary, file_name):
    extensions = list_extensions(config)
    counter = 0 # to add a header to list_failed_ext_nightly_build_architecture.csv only once
    tested_binary_path = f"{ tested_binary }:/duckdb"

    for ext in extensions:
        if architecture.count("aarch64") or architecture.count("arm64"):
            select_installed = [
                "docker", "run", "--rm",
                "--platform", architecture,
                "-v", tested_binary_path,
                "-e", f"ext={ ext }",
                "ubuntu:latest",
                "/bin/bash", "-c", 
                f"/duckdb -csv -noheader -c \"SELECT installed FROM duckdb_extensions() WHERE extension_name='{ ext }';\""
            ]
        else:
            select_installed = [
                tested_binary,
                "-csv",
                "-noheader",
                "-c",
                f"SELECT installed FROM duckdb_extensions() WHERE extension_name='{ ext }';"
            ]
        result=subprocess.run(select_installed, check=True, text=True, capture_output=True)

        is_installed = result.stdout.strip()
        tested_binary_path = f"{ tested_binary }:/duckdb"
        if is_installed == 'false':
            for act in ACTION:
                print(f"{ act }ing { ext }...")
                if architecture.count("aarch64"):
                    install_ext = [
                        "docker", "run", "--rm",
                        "--platform", architecture,
                        "-v", tested_binary_path,
                        "-e", f"ext={ ext }",
                        "ubuntu:latest",
                        "/bin/bash", "-c",
                        f"/duckdb -c \"{ act } '{ ext }';\""
                    ]
                else:
                    install_ext = [
                        tested_binary,
                        "-c",
                        f"{ act } '{ ext }';"
                    ]
                try:
                    result = subprocess.run(install_ext, check=True, text=True, capture_output=True)
                    print(result.stdout)
                    if result.stdout.strip() == 'false':
                        if counter == 0:
                            f.write(f"nightly_build,architecture,runs_on,version,extension,failed_statement\n")
                            counter += 1
                        f.write(f"{ nightly_build },{ architecture },{ runs_on },,{ ext },{ act }\n")

                except subprocess.CalledProcessError as e:
                    with open(file_name, 'a') as f:
                        if counter == 0:
                            f.write(f"nightly_build,architecture,runs_on,version,extension,failed_statement\n")
                            counter += 1
                        f.write(f"{ nightly_build },{ architecture },{ runs_on },,{ ext },{ act }\n")
                    print(f"Error running command for extesion { ext }: { e }")
                    print(f"stderr: { e.stderr }")
    if not os.path.exists(file_name):
        with open(file_name, 'w') as f:
            f.write(f"All extensions are installed and loaded successfully.\nList of tested extensions:\n{ extensions }")

def main():
    file_name = "list_failed_ext_{}_{}.csv".format(nightly_build, architecture.replace("/", "-"))
    counter = 0 # to write only one header per table
    if nightly_build == 'Python':
        verify_and_test_python(file_name, counter, run_id, architecture)
    else:
        path_pattern = os.path.join("duckdb_path", "duckdb*")
        matches = glob.glob(path_pattern)
        if matches:
            tested_binary = os.path.abspath(matches[0])
            print(f"Found binary: { tested_binary }")
        else:
            raise FileNotFoundError(f"No binary matching { path_pattern } found in duckdb_path dir.")
        print(f"VERIFY BUILD SHA")
        if verify_version(tested_binary, file_name):
            print(f"TEST EXTENSIONS")
            test_extensions(tested_binary, file_name)
        print(f"FINISH")

if __name__ == "__main__":
    main()