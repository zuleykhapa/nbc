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

GH_REPO = 'duckdb/duckdb'

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
extensions = list_extensions(config)

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

##############
### PYTHON ###
##############

def get_python_versions_from_run(run_id):
    file_name = "python_run_info.md"
    command = [
        "gh", "run", "view",
        "--repo", "duckdb/duckdb",
        run_id, "-v"
    ]
    fetch_data(command, file_name)
    with open(file_name, "r") as file:
        content = file.read()
        pattern = r"cp([0-9]+)-.*"
        matches = sorted(set(re.findall(pattern, content)))
        # puts a '.' after the first character: '310' => '3.10'
        result = [word[0] + '.' + word[1:] if len(word) > 1 else word + '.' for word in matches]
        return result

def verify_and_test_python(file_name, counter, run_id, architecture):
    python_versions = get_python_versions_from_run(run_id)
    client = docker.from_env() # to use docker installed on GH Actions machine by the workflow
    full_sha = get_full_sha(run_id)
    
    version = "3.13"
    for version in python_versions:
    # architecture = "arm64"
        verify_python_build_and_test_extensions(client, version, full_sha, file_name, architecture, counter)

def verify_python_build_and_test_extensions(client, version, full_sha, file_name, architecture, counter):
    if runs_on == 'macos-latest':
        # install proper version of python
        # run tests
        print("macos")
    elif runs_on == 'windows-2019':
        docker_image = "mcr.microsoft.com/windows/servercore:ltsc2022-arm64"
        command = f"""
                powershell -Command "python --version; if (-not $?) {{ Write-Host 'Install Python'; }} "
            """
    elif runs_on == 'ubuntu-latest':
        docker_image = f"python:{ version }"
        architecture = f"linux/{ architecture }"
    else:
        raise ValueError(f"Unsupported OS: { runs_on }")
    # if runs_on == 'ubuntu-latest':
    #     docker_image = f"python:{ version }"
    # else:
    #     return
    arch = architecture.replace("/", "-")
    container_name = f"python-test-{ runs_on }-{ arch }-python-{ version.replace('.', '-') }"
    print(container_name)
    container = create_container(client, container_name, docker_image, architecture, None)
    print(f"VERIFYING BUILD SHA FOR python{ version }")
    try:
        print("🦑", container.exec_run("cat /etc/os-release", stdout=True, stderr=True).output.decode())
        print("🦑", container.exec_run("arch", stdout=True, stderr=True).output.decode())
        print("📌", container.exec_run("python --version"), stdout=True, stderr=True).output.decode()
        container.exec_run("pip install -v duckdb --pre --upgrade", stdout=True, stderr=True)
        result = container.exec_run(
            "python -c \"import duckdb; print(duckdb.sql('SELECT source_id FROM pragma_version()').fetchone()[0])\"",
            stdout=True, stderr=True
        )
        print(f"Result: { result.output.decode() }")
        
        short_sha = result.output.decode().strip()
        if not full_sha.startswith(short_sha):
            print(f"""
            Version of { nightly_build } tested binary doesn't match to the version that triggered the build.
            - Version triggered the build: { full_sha }\n - Downloaded build version: { short_sha }\n
            """)
            with open(file_name, 'a') as f:
                f.write(f"""
                Version of { nightly_build } tested binary doesn't match to the version that triggered the build.
                - Version triggered the build: { full_sha }\n - Downloaded build version: { short_sha }\n
                """)
        else:
            print(f"""
            Versions of { nightly_build } build match: ({ short_sha }) and ({ full_sha }).
            - Version triggered the build: { full_sha }\n - Downloaded build version: { short_sha }\n
            """)
            print(f"TESTING EXTENSIONS ON python{ version }")
            extensions = list_extensions(config)
            action=["INSTALL", "LOAD"]
            for ext in extensions:
                installed = container.exec_run(f"""
                    python -c "import duckdb; res = duckdb.sql('SELECT installed FROM duckdb_extensions() WHERE extension_name=\\'{ ext }\\'').fetchone(); print(res[0] if res else None)"
                    """, stdout=True, stderr=True)
                print( f"Is { ext } already installed: { installed.output.decode() }")
                if installed.output.decode().strip() == "False":
                    for act in action:
                        print(f"{ act }ing { ext }...")
                        result = container.exec_run(f"""
                            python -c "import duckdb; print(duckdb.sql('{ act } \\'{ ext }\\''))"
                        """,
                        stdout=True, stderr=True).output.decode().strip()
                        print(f"STDOUT: {result}")
                        installed = container.exec_run(f"""
                            python -c "import duckdb; res = duckdb.sql('SELECT installed FROM duckdb_extensions() WHERE extension_name=\\'{ ext }\\'').fetchone(); print(res[0] if res else None)"
                            """, stdout=True, stderr=True)
                        print( f"Is { ext } already installed: { installed.output.decode() }")
                        if result != "None":
                            with open(file_name, 'a') as f:
                                if counter == 0:
                                    f.write(f"nightly_build,architecture,runs_on,version,extension,failed_statement\n")
                                    counter += 1
                                f.write(f"{ nightly_build },{ architecture },{ runs_on },{ version },{ ext },{ act }\n")
    finally:
        stop_container(container, container_name)

##############
### OTHERS ###
##############


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