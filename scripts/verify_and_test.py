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


parser = argparse.ArgumentParser()
# parser.add_argument("file_name")
# parser.add_argument("duckdb_path")
parser.add_argument("--nightly_build")
parser.add_argument("--architecture")
parser.add_argument("--run_id")
parser.add_argument("--runs_on")
parser.add_argument("--config")

# parser.add_argument("--url")
args = parser.parse_args()

# duckdb_path = args.duckdb_path # duckdb_path/ducldb or duckdb_path/duckdb.exe
nightly_build = args.nightly_build
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

def get_python_versions_from_run():
    with open("python_run_info.md", "r") as file:
        content = file.read()
        pattern = r"cp([0-9]+)-.*"
        matches = sorted(set(re.findall(pattern, content)))
        # puts a '.' after the first character: '310' => '3.10'
        result = [word[0] + '.' + word[1:] if len(word) > 1 else word + '.' for word in matches]
        return result

def verify_python():
    python_versions = get_python_versions_from_run()
    install_command = "pip install duckdb"
    version_commad = "duckdb --version"

    for version in python_versions:
        print(version)
        
def teest_python_extensions():
    return

def verify_version(tested_binary, file_name):
    gh_headSha_command = [
        "gh", "run", "view",
        run_id,
        "--repo", "duckdb/duckdb",
        "--json", "headSha",
        "-q", ".headSha"
    ]
    full_sha = subprocess.run(gh_headSha_command, check=True, text=True, capture_output=True).stdout.strip()
    if architecture.count("aarch64"):
        pragma_version = [
            "docker", "run", "--rm", "--platform", "linux/aarch64",
            "-v", f"{ tested_binary }:/duckdb",
            "ubuntu:22.04",
            "/bin/bash", "-c", f"/duckdb --version"
        ]
    else:
        pragma_version = [ tested_binary, "--version" ]
    short_sha = subprocess.run(pragma_version, check=True, text=True, capture_output=True).stdout.strip().split()[-1]
    if not full_sha.startswith(short_sha):
        print(f"The version of { nightly_build} build ({ short_sha }) doesn't match to the version triggered the build ({ full_sha }).\n")
        with open(file_name, 'w') as f:
            f.write(f"- The version of { nightly_build } build ({ short_sha }) doesn't match to the version triggered the build ({ full_sha }).\n")
        return False
    print(f"The versions of { nightly_build} build match: ({ short_sha }) and ({ full_sha }).\n")
    return True

def test_extensions(tested_binary, file_name):
    action=["INSTALL", "LOAD"]
    extensions=list_extensions(config)
    print(extensions)
    counter = 0 # to add a header to list_failed_ext_nightly_build_architecture.md only once

    for ext in extensions:
        if architecture.count("aarch64"):
            select_installed = [
                "docker", "run", "--rm", "--platform", "linux/aarch64",
                "-v", f"{ tested_binary }:/duckdb",
                "-e", f"ext={ ext }",
                "ubuntu:22.04",
                "/bin/bash", "-c", 
                f"/duckdb -c \"SELECT installed FROM duckdb_extensions() WHERE extension_name='\$ext';\""
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
        if is_installed == 'false':
            for act in action:
                print(f"{ act }ing { ext }...")
                if architecture.count("aarch64"):
                    install_ext = [
                        "docker", "run", "--rm", "--platform", "linux/aarch64",
                        "-v", f"{ tested_binary }:/duckdb",
                        "-e", f"ext={ ext }",
                        "ubuntu:22.04",
                        "/bin/bash", "-c", f"/duckdb -c \"\$act '\$ext';\""
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
                except subprocess.CalledProcessError as e:
                    with open(file_name, 'a') as f:
                        if counter == 0:
                            f.write(f"nightly_build,architecture,runs_on,version,extension,failed_statement\n")
                            counter += 1
                        f.write(f"{ nightly_build },{ architecture },{ runs_on },,{ ext },{ act }\n")
                    print(f"Error running command for extesion { ext }: { e }")
                    print(f"stderr: { e.stderr }")

def main():
    if nightly_build == 'Python':
        verify_python()
    else:
        path_pattern = os.path.join("duckdb_path", "duckdb*")
        matches = glob.glob(path_pattern)
        if matches:
            tested_binary = os.path.abspath(matches[0])
            print(f"Found binary: { tested_binary }")
        else:
            raise FileNotFoundError(f"No binary matching { path_pattern } found in duckdb_path dir.")
        file_name = "list_failed_ext_{}_{}.md".format(nightly_build, architecture)
        print(f"VERIFY BUILD SHA")
        if verify_version(tested_binary, file_name):
            print(f"TEST EXTENSIONS")
            test_extensions(tested_binary, file_name)
        print(f"FINISH")

if __name__ == "__main__":
    main()