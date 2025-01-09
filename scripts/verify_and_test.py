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

GH_REPO = 'duckdb/duckdb'

parser = argparse.ArgumentParser()
parser.add_argument("--nightly_build")
parser.add_argument("--platform")
parser.add_argument("--architecture")
parser.add_argument("--run_id")
parser.add_argument("--runs_on")
parser.add_argument("--config")

# parser.add_argument("--url")
args = parser.parse_args()

# duckdb_path = args.duckdb_path # duckdb_path/ducldb or duckdb_path/duckdb.exe
nightly_build = args.nightly_build
platform = args.platform # linux
architecture = args.architecture if nightly_build == 'Python' else args.architecture.replace("-", "/") # linux-aarch64 => linux/aarch64 for docker
run_id = args.run_id
runs_on = args.runs_on # linux-latest
config = args.config # ext/config/out_of_tree_extensions.cmake

print("INPUTS:", nightly_build, platform, architecture, run_id, runs_on)


##########
# DOCKER #
##########
def create_container(client, container_name, image, architecture, tested_binary_path):
    container = client.containers.run(
        image=image,
        name=container_name,
        command="/bin/bash -c 'sleep infinity'",
        platform=architecture,
        volumes=tested_binary_path if tested_binary_path else None,
        detach=True
    )
    print(f"Container '{ container_name }' created.")
    return container

def execute_in_container(container, command):
    exec_result = container.exec_run(command, stdout=True, stderr=True)
    print(f"Container '{ container_name }': Command '{ command } execution output:\n{ exec_result .output.decode() }")

def stop_container(container, container_name):
    container.stop()
    container.remove()
    print(f"Container '{ container_name } has stopped.")

##########
# COMMON #
##########
def list_extensions(config) :
    with open(config, "r") as file:
        content = file.read()
    # Adjusted regex for matching after `load(`
    pattern = r"duckdb_extension_load\(\s*([^\s,)]+)"
    matches = re.findall(pattern, content)
    return matches
extensions = list_extensions(config)

def fetch_data(command, f_output): # saves command execution results into a file
    data = open(f_output, "w")
    try:
        subprocess.run(command, stdout=data, stderr=True, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Command failed with error: {e.stderr}")

def get_full_sha(run_id):
    gh_headSha_command = [
        "gh", "run", "view",
        run_id,
        "--repo", "duckdb/duckdb",
        "--json", "headSha",
        "-q", ".headSha"
    ]
    full_sha = subprocess.run(gh_headSha_command, check=True, text=True, capture_output=True).stdout.strip()
    return full_sha



################
# OTHER BUILDS #
################
def verify_version(tested_binary, file_name):
    full_sha = get_full_sha(run_id)
    if architecture.count("aarch64") or architecture.count("arm64"):
        pragma_version = [
            "docker", "run", "--rm",
            "--platform", architecture,
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
    print(extensions)
    counter = 0 # to add a header to list_failed_ext_nightly_build_architecture.csv only once

    for ext in extensions:
        if architecture.count("aarch64") or architecture.count("arm64"):
            select_installed = [
                "docker", "run", "--rm",
                "--platform", architecture,
                "-v", f"{ tested_binary }:/duckdb",
                "-e", f"ext={ ext }",
                "ubuntu:22.04",
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
        print(is_installed)
        if is_installed == 'false':
            for act in action:
                print(f"{ act }ing { ext }...")
                if architecture.count("aarch64"):
                    install_ext = [
                        "docker", "run", "--rm",
                        "--platform", f"{ architecture }",
                        "-v", f"{ tested_binary }:/duckdb",
                        "-e", f"ext={ ext }",
                        "ubuntu:22.04",
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

def main():
    file_name = "list_failed_ext_{}_{}.csv".format(nightly_build, architecture.replace("/", "_"))
    counter = 0 # to write only one header per table
    path_pattern = os.path.join("duckdb_path", "duckdb*")
    matches = glob.glob(path_pattern)
    if matches:
        tested_binary = os.path.abspath(matches[0])
        print(f"Found binary: { tested_binary }")
    else:
        raise FileNotFoundError(f"No binary matching { path_pattern } found in duckdb_path dir.")
    print(f"VERIFY BUILD SHA")
    # verify_and_test_python(file_name,counter)
    if verify_version(tested_binary, file_name):
        print(f"TEST EXTENSIONS")
        test_extensions(tested_binary, file_name)
    print(f"FINISH")

if __name__ == "__main__":
    main()