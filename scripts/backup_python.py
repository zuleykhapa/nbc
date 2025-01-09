########################
# PYTHON BUILD TESTING #
########################
def get_python_versions_from_run():
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

def verify_and_test_python(file_name, counter):
    python_versions = get_python_versions_from_run()
    client = docker.from_env() # to use docker installed on GH Actions machine by the workflow
    full_sha = get_full_sha(run_id)
    
    # for version in python_versions:
    version = "3.13"
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
        print("📌", container.exec_run("python --version", stdout=True, stderr=True).output.decode())
        container.exec_run("pip install -v duckdb --pre --upgrade", stdout=True, stderr=True)
        result = container.exec_run(
            "python -c \"import duckdb; print(duckdb.sql('SELECT source_id FROM pragma_version()').fetchone()[0])\"",
            stdout=True, stderr=True
        )
        print(f"Result: { result.output.decode() }")
        
        short_sha = result.output.decode().strip()
        if not full_sha.startswith(short_sha):
            print(f"The version of { nightly_build} build ({ short_sha }) doesn't match to the version triggered the build ({ full_sha }).\n")
            with open(file_name, 'a') as f:
                f.write(f"The version of { nightly_build} build ({ short_sha }) doesn't match to the version triggered the build ({ full_sha }).\n")
        else:
            print(f"TESTING EXTENSIONS ON python{ version }")
            extensions = ["delta"]
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

def main():
    file_name = "list_failed_ext_{}_{}.md".format(nightly_build, architecture.replace("/", "_"))
    counter = 0 # to write only one header per table
    if nightly_build == 'Python':
        verify_and_test_python(file_name, counter)
    else:
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