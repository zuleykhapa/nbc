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
import duckdb
import argparse
import docker
import glob
import os
import random
import re
import subprocess
import textwrap
import sys
from shared_functions import fetch_data

GH_REPO = os.environ.get('GH_REPO', 'duckdb/duckdb')
ACTIONS = ["INSTALL", "LOAD"]
EXT_WHICH_DOESNT_EXIST = "EXT_WHICH_DOESNT_EXIST"

parser = argparse.ArgumentParser()
parser.add_argument("--nightly_build")
parser.add_argument("--architecture")
parser.add_argument("--run_id")
parser.add_argument("--runs_on")
parser.add_argument("--config")

args = parser.parse_args()

nightly_build = args.nightly_build
architecture = args.architecture if nightly_build == 'Python' else args.architecture.replace("-", "/") # linux-aarch64 => linux/aarch64 for docker
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
        print(f"""
Versions of { nightly_build } build match: ({ short_sha }) and ({ full_sha }).
- Version triggered the build: { full_sha }\n - Downloaded build version: { short_sha }\n
        """)
        return True

def verify_and_test_python_linux(counter, version, full_sha, file_name, architecture, config, nightly_build, runs_on):
    client = docker.from_env() # to use docker installed on GH Actions machine by the workflow
    architecture = architecture.replace("/", "-")
    arch = f"linux/{ architecture }"
    docker_image = f"python:{ version }"
    container_name = f"python-test-{ runs_on }-{ architecture }-python-{ version.replace('.', '-') }"
    
    print(docker_image, architecture, container_name)
    
    container = create_container(client, container_name, docker_image, architecture, None)
    print(f"VERIFYING BUILD SHA FOR python{ version }")
    try:
        print("🦑", container.exec_run("cat /etc/os-release", stdout=True, stderr=True).output.decode())
        print("🫡", container.exec_run("uname -m", stdout=True, stderr=True).output.decode())
        print("📌", container.exec_run("python --version", stdout=True, stderr=True).output.decode())
        container.exec_run("pip install -v duckdb --pre --upgrade", stdout=True, stderr=True)
        result = container.exec_run(
            "python -c \"import duckdb; print(duckdb.sql('SELECT source_id FROM pragma_version()').fetchone()[0])\"",
            stdout=True, stderr=True
        )
        print(f"Result: { result.output.decode() }")
        
        short_sha = result.output.decode().strip()
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
                                if counter == 0:
                                    f.write(f"nightly_build,architecture,runs_on,version,extension,failed_statement\n")
                                    counter += 1
                                f.write(f"{ nightly_build },{ architecture },{ runs_on },{ version },{ ext },{ act }\n")
    finally:
        print("FINISH")
        stop_container(container, container_name)

# def verify_and_test_python(file_name, COUNTER, run_id, architecture, nightly_build, runs_on):
#     python_versions = list_builds_for_python_versions(run_id)
#     full_sha = get_full_sha(run_id)
    
#     version = "3.13"
#     for version in python_versions:
#     # architecture = "arm64" #  (architecture == 'arm64' and runs_on == 'windows-2019')
#         if runs_on == 'macos-latest':
#             verify_and_test_python_macos(version, full_sha, file_name, architecture, COUNTER, config, nightly_build, runs_on)
#             return
#         elif runs_on == 'ubuntu-latest':
#             docker_image = f"python:{ version }"
#             architecture = f"linux/{ architecture }"
#             verify_and_test_python_linux(version, full_sha, file_name, architecture, COUNTER, config, nightly_build, runs_on)
#         else:
#             raise ValueError(f"Unsupported OS: { runs_on }")
        

##############
### OTHERS ###
##############
def verify_version(tested_binary, file_name):
    full_sha = get_full_sha(run_id)
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

def test_extensions(tested_binary, counter, file_name):
    extensions = list_extensions(config)
    for ext in extensions:
        select_installed = [
            tested_binary,
            "-csv",
            "-noheader",
            "-c",
            f"SELECT installed FROM duckdb_extensions() WHERE extension_name='{ ext }';"
        ]
        result=subprocess.run(select_installed, text=True, capture_output=True)
        is_installed = result.stdout.strip()
        if is_installed == 'false':
            for action in ACTIONS:
                print(f"{ action }ing { ext }...")
                install_ext = [
                    tested_binary, "-c",
                    f"{ action } '{ ext }';"
                ]
                try:
                    result = subprocess.run(install_ext, text=True, capture_output=True)
                    if result.stderr:
                        print(f"{ action } '{ ext }' had failed with following error:\n{ result.stderr.strip() }")
                        with open(file_name, "a") as f:
                            if counter == 0:
                                f.write("nightly_build,architecture,runs_on,version,extension,failed_statement\n")
                                counter += 1
                            f.write(f"{ nightly_build },{ architecture },{ runs_on },,{ ext },{ action }\n")

                except subprocess.CalledProcessError as e:
                    print(f"Error running command for extesion { ext }: { e }")
                    print(f"stderr: { e.stderr }")
    print(f"Trying to install a non-ecisting extension in {nightly_build}...")
    result = subprocess.run([ tested_binary, "-c", "INSTALL", f"'{ EXT_WHICH_DOESNT_EXIST }'"], text=True, capture_output=True)
    if result.stderr:
        print(f"Attempted to install a non-existing extension resulted with error, as expected: { result.stderr }")
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
    COUNTER = 0 # to write only one header per table
    if nightly_build == 'Python':
        python_versions = list_builds_for_python_versions(run_id)
        full_sha = get_full_sha(run_id)
        
        if runs_on.startswith("ubuntu"):
            for version in python_versions:
                verify_and_test_python_linux(COUNTER, version, full_sha, file_name, architecture, config, nightly_build, runs_on)
        else:
            # init_pyenv()
            install_python_with_pyenv()
            for version in python_versions:
                print(f"Setting up Python {version}...")
                subprocess.run(f"pyenv install {version}", shell=True, check=True)
                subprocess.run(f"pyenv global {version}", shell=True, check=True)
                # print(f"Installing Python version { version }...")
                # try: 
                #     subprocess.check_call([
                #         sys.executable, "-m", "pip", "install", "-s", f"python{ version }"
                #     ])
                # except subprocess.CalledProcessError as e:
                #     print(f"Error installing Python version { version }: { e }")
                #     print(f"stderr: { e.stderr }")
                
                # print(f"Setting Python version { version } global.")
                # subprocess.run(
                #     f"pyenv local { version }", shell=True, check=True, executable="/bin/bash", env=env)
                # # py_version - debug output
                # py_version = subprocess.run(f"python{ version } --version", capture_output=True, text=True)
                # print(f"Installed Python version: { py_version.stdout }")
                
                print(f"Ensuring pip is installed to the Python version { version }...")
                subprocess.run([f"python{ version }", "-m", "ensurepip", "--upgrade"])
                # install duckdb
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
                result = subprocess.run(py_version_command, text=True, capture_output=True)
                short_sha = result.stdout.strip()
                if sha_matching(short_sha, full_sha, file_name, nightly_build):
                    print(f"Testing extensions on python{ version }...")
                    extensions = list_extensions(config)
                    # extensions = ["aws"]
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
                                        with open(file_name, 'a') as f:
                                            if COUNTER == 0:
                                                f.write(f"nightly_build,architecture,runs_on,version,extension,failed_statement\n")
                                                COUNTER += 1
                                            f.write(f"{ nightly_build },{ architecture },{ runs_on },{ version },{ ext },{ action }\n")
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
                                        with open(file_name, 'a') as f:
                                            if COUNTER == 0:
                                                f.write(f"nightly_build,architecture,runs_on,version,extension,failed_statement\n")
                                                COUNTER += 1
                                            f.write(f"{ nightly_build },{ architecture },{ runs_on },{ version },{ ext },{ action }\n")
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
            test_extensions(tested_binary, COUNTER, file_name)
        print("FINISH")

if __name__ == "__main__":
    main()