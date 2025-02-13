'''
We would like to know if extensions can be installed and loaded on nightly-builds.
Nightly-builds for platforms Windows, OSX, Linux, WASM, Android, R upload artifacts, but we test only
Windows, OSX, Linux platforms binaries.
There are nightly-builds which don't upload artifacts on GitHub: Python, Julia, Swift, SwiftRelease.
Python builds are uploaded to Pypy so Python builds can be tested as well.

This script makes sure that tested version and nightly-build version are the same by comparing their SHA.
Then it runs INSTALL and LOAD statements for each extension. In case of `stderr` in an output, it collects failure
information to a .csv file (later the file will be used to create a report).

A list of extensions comes from the `ext/.github/config/out_of_tree_extensions.cmake` file from `duckdb/duckdb` repo.
Also this script tries to INSTALL a non-existing extension to make sure the whole test results are not false-positive.
'''
import argparse
import docker
import duckdb
import glob
import os
import random
import re
import sys
import subprocess
import textwrap
from shared_functions import fetch_data

GH_REPO = os.environ.get('GH_REPO', 'duckdb/duckdb')
ACTIONS = ["INSTALL", "LOAD"]
EXT_WHICH_DOESNT_EXIST = "EXT_WHICH_DOESNT_EXIST"
SHOULD_BE_TESTED = ('python', 'osx', 'linux', 'windows')

parser = argparse.ArgumentParser()
parser.add_argument("--nightly_build")
parser.add_argument("--architecture")
parser.add_argument("--run_id")
parser.add_argument("--runs_on")
parser.add_argument("--config")

args = parser.parse_args()

nightly_build = args.nightly_build
architecture = args.architecture
run_id = args.run_id
runs_on = args.runs_on # linux-latest
config = args.config # ext/config/out_of_tree_extensions.cmake

def list_extensions(config) :
    with open(config, "r") as file:
        content = file.read()
    # matching each word after `load(`
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

##########
# DOCKER #
##########
def create_container(client, container_name, image, architecture, tested_binary_path):
    platform = architecture.split("_")[1]
    container = client.containers.run(
        image=image,
        name=container_name,
        command="/bin/bash -c 'sleep infinity'",
        platform=platform,
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

def list_builds_for_python_versions(run_id):
    file_name = "python_run_info.md"
    command = [
        "gh", "run", "view",
        "--repo", GH_REPO,
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

def sha_matching(short_sha, full_sha, file_name, nightly_build):
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
            return False
    else:
        print(f"Versions of { nightly_build } build matches:- Version triggered the build: { full_sha }\n - Downloaded build version: { short_sha }\n")
        return True

def verify_and_test_python_linux(version, full_sha, file_name, architecture, config, nightly_build, runs_on):
    global COUNTER
    client = docker.from_env() # to use docker installed on GH Actions machine by the workflow
    arch = f"linux/{ architecture }"
    docker_image = f"python:{ version }"
    container_name = f"python-test-{ runs_on }-{ architecture }-python-{ version.replace('.', '-') }"
    
    print(docker_image, architecture, container_name)
    
    container = create_container(client, container_name, docker_image, architecture, None)
    print(f"VERIFYING BUILD SHA FOR python{ version }")
    try:
        container.exec_run("pip install -v duckdb --pre --upgrade", stdout=True, stderr=True)
        result = container.exec_run(
            "python -c \"import duckdb; print(duckdb.sql('SELECT source_id FROM pragma_version()').fetchone()[0])\"",
            stdout=True, stderr=True
        )
        print(f"Result: { subprocess_result.output.decode() }")
        
        short_sha = subprocess_result.output.decode().strip()
        if sha_matching(short_sha, full_sha, file_name, nightly_build):
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
                        action_result_ouput = container.exec_run(f"""
                            python -c "import duckdb; print(duckdb.sql('{ act } \\'{ ext }\\''))"
                        """,
                        stdout=True, stderr=True).output.decode().strip()
                        print(f"STDOUT: {action_result_ouput}")
                        installed = container.exec_run(f"""
                            python -c "import duckdb; res = duckdb.sql('SELECT installed FROM duckdb_extensions() WHERE extension_name=\\'{ ext }\\'').fetchone(); print(res[0] if res else None)"
                            """, stdout=True, stderr=True)
                        print( f"Is { ext } { act }ed: { installed.output.decode() }")
                        if action_result_ouput != "None":
                            with open(file_name, 'a') as f:
                                if COUNTER == 0:
                                    f.write(f"nightly_build,architecture,runs_on,version,extension,failed_statement\n")
                                    COUNTER += 1
                                f.write(f"{ nightly_build },{ architecture },{ runs_on },{ version },{ ext },{ act }\n")
    finally:
        print("FINISH")
        stop_container(container, container_name)
        
##############
### OTHERS ###
##############
def verify_version(tested_binary, file_name):
    full_sha = get_full_sha(run_id)
    # full_sha = "5f5512b827df6397afd31daedb4bbdee76520019"
    pragma_version = [ tested_binary, "--version" ]
    short_sha = subprocess.run(pragma_version, text=True, capture_output=True).stdout.strip().split()[-1]
    if not full_sha.startswith(short_sha):
        print(f"""
        Version of { nightly_build } tested binary doesn't match to the version that triggered the build.
        - Version triggered the build: { full_sha }
        - Downloaded build version: { short_sha }
        """)
        with open(file_name, 'w') as f:
            f.write(f"""
            Version of { nightly_build } tested binary doesn't match to the version that triggered the build.
            - Version triggered the build: { full_sha }
            - Downloaded build version: { short_sha }
            """)
        return False
    print(f"""
    Versions of { nightly_build } build match:
    - Version triggered the build: { full_sha }
    - Downloaded build version: { short_sha }
    """)
    return True

def test_extensions(tested_binary, file_name):
    extensions = list_extensions(config)
    print(extensions)
    counter = 0 # to add a header to list_failed_ext_nightly_build_architecture.csv only once

    for ext in extensions:
        select_installed = [
            tested_binary,
            "-csv",
            "-noheader",
            "-c",
            f"SELECT installed FROM duckdb_extensions() WHERE extension_name='{ ext }';"
        ]
        subprocess_result = subprocess.run(select_installed, text=True, capture_output=True)

        is_installed = subprocess_result.stdout.strip()
        if is_installed == 'false':
            for action in ACTIONS:
                print(f"{ action }ing { ext }...")
                install_ext = [
                    tested_binary,
                    "-c",
                    f"{ action } '{ ext }';"
                ]
                try:
                    subprocess_result = subprocess.run(install_ext, text=True, capture_output=True)
                    if subprocess_result.stderr:
                        print(f"{ action } '{ ext }' had failed with following error:\n{ subprocess_result.stderr.strip() }")
                        actual_result = 'failed'
                    else:
                        actual_result = 'passed'
                    with open(file_name, "a") as f:
                        if counter == 0:
                            f.write("nightly_build,architecture,runs_on,version,extension,statement,result\n")
                            counter += 1
                        f.write(f"{ nightly_build },{ architecture },{ runs_on },,{ ext },{ action },{ actual_result }\n")

                except subprocess.CalledProcessError as e:
                    print(f"Error running command for extesion { ext }: { e }")
                    print(f"stderr: { e.stderr }")
    print(f"Trying to install a non-existing extension in {nightly_build}...")
    subprocess_result = subprocess.run([ tested_binary, "-c", "INSTALL", f"'{ EXT_WHICH_DOESNT_EXIST }'"], text=True, capture_output=True)
    if subprocess_result.stderr:
        print(f"Attempt to install a non-existing extension resulted with error, as expected: { subprocess_result.stderr }")
    else:
        print(f"Unexpected extension with name { EXT_WHICH_DOESNT_EXIST } had been installed.")
        f.write(f"Unexpected extension with name { EXT_WHICH_DOESNT_EXIST } had been installed.")

def init_pyenv():
    pyenv_root = os.path.expanduser("~/.pyenv")
    env = os.environ.copy()
    env["PYENV_ROOT"] = pyenv_root
    env["PATH"] = f"{pyenv_root}/bin:{env['PATH']}"

    subprocess.run("eval \"$(pyenv init --path)\"", shell=True, check=True, executable="/bin/bash", env=env)
    print("INSTALLED")
    # subprocess.run(["bash", "-c", "eval \"$(pyenv init --path)\""], check=True)

# Install pyenv and specific Python versions dynamically (if necessary)
def install_python_with_pyenv():
    print(f"Installing pyenv...")
    subprocess.run(f"curl https://pyenv.run | bash", shell=True, check=True)


def main():
    file_name = "list_failed_ext_{}_{}.csv".format(nightly_build, architecture.replace("/", "-"))
    print(nightly_build)
    if nightly_build in SHOULD_BE_TESTED:
        if nightly_build == 'python':
            python_versions = list_builds_for_python_versions(run_id)
            full_sha = get_full_sha(run_id)
            
            if runs_on.startswith("ubuntu"):
                for version in python_versions:
                    verify_and_test_python_linux(version, full_sha, file_name, architecture, config, nightly_build, runs_on)
            else:
                # init_pyenv()
                install_python_with_pyenv()
                for version in python_versions:
                    print(f"Setting up Python {version}...")
                    subprocess.run(f"pyenv install {version}", shell=True, check=True)
                    subprocess.run(f"pyenv global {version}", shell=True, check=True)
                    print(f"Installing Duckdb on Python version { version }...")
                    subprocess.run([
                        f"python{ version }", "-m",
                        "pip", "install",
                        "-v", "duckdb",
                        "--pre", "--upgrade"
                    ])
                    # verify
                    print("VERIFY BUILD SHA")
                    py_version_command = [
                        f"python{ version }", "-c",
                        "import duckdb; print(duckdb.sql('SELECT source_id FROM pragma_version()').fetchone()[0])"
                    ]
                    subprocess_result = subprocess.run(py_version_command, text=True, capture_output=True)
                    short_sha = subprocess_result.stdout.strip()
                    if sha_matching(short_sha, full_sha, file_name, nightly_build):
                        print(f"Testing extensions on python{ version }...")
                        extensions = list_extensions(config)
                        for ext in extensions:
                            for action in ACTIONS:
                                is_installed_command = [
                                    f"python{ version }", "-c",
                                    textwrap.dedent(f"""
                                        import duckdb
                                        is_installed = duckdb.sql("SELECT install_mode FROM duckdb_extensions() WHERE extension_name='{ ext }'").fetchone()[0]
                                        print(install_mode)
                                    """)
                                ]
                                is_installed = subprocess.run(is_installed_command, text=True, capture_output=True).stdout.strip()
                                print("📌", ext, len(is_installed))
                                if not is_installed:
                                    action_command = [
                                        f"python{ version }", "-c",
                                        textwrap.dedent(f"""
                                            import duckdb
                                            print(duckdb.sql("{ action } '{ ext }'"))
                                        """)
                                    ]
                                    print(f"{ action }ing { ext }...")
                                    subprocess.run(action_command, text=True, capture_output=True).stdout.strip()
                                    # verify action result
                                    if action == 'INSTALL':
                                        is_installed = subprocess.run(is_installed_command, text=True, capture_output=True).stdout.strip()
                                        
                                        print("TEST RESULT FOR", action, ext, ":", is_installed)
                                        if is_installed == 'None':
                                            actual_result = 'failed'
                                        else:
                                            actual_result = 'passed'
                                        with open(file_name, 'a') as f:
                                            if COUNTER == 0:
                                                f.write("nightly_build,architecture,runs_on,version,extension,statement,result\n")
                                                COUNTER += 1
                                            f.write(f"{ nightly_build },{ architecture },{ runs_on },,{ ext },{ action },{ actual_result }\n")
                                    else:
                                        is_loaded_command =[
                                            f"python{ version }", "-c",
                                            textwrap.dedent(f"""
                                                import duckdb
                                                is_loded = duckdb.sql("SELECT loaded FROM duckdb_extensions() WHERE extension_name='{ ext }'").fetchone()[0]
                                                print(is_loded)
                                            """)
                                        ]
                                        is_loaded = subprocess.run(is_loaded_command, text=True, capture_output=True).stdout.strip()

                                        print("TEST RESULT FOR", action, ext, ":", is_loaded)
                                        if is_loaded == 'False':
                                            actual_result = 'failed'
                                        else:
                                            actual_result = 'passed'
                                        with open(file_name, 'a') as f:
                                            if COUNTER == 0:
                                                f.write("nightly_build,architecture,runs_on,version,extension,statement,result\n")
                                                COUNTER += 1
                                            f.write(f"{ nightly_build },{ architecture },{ runs_on },,{ ext },{ action },{ actual_result }\n")
                print("FINISH")
        else:
            path_pattern = os.path.join("duckdb_path", "duckdb*")
            matches = glob.glob(path_pattern)
            if matches:
                tested_binary = os.path.abspath(matches[0])
                print(f"Found binary: { tested_binary }")
            else:
                raise FileNotFoundError(f"No binary matching { path_pattern } found in duckdb_path dir.")
            print("VERIFY BUILD SHA")
            if verify_version(tested_binary, file_name):
                print("TEST EXTENSIONS")
                test_extensions(tested_binary, file_name)
            print("FINISH")

if __name__ == "__main__":
    main()