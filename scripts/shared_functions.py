'''
the whole list of nightly-build names:
"--jq", (
    '.[] | select(.name == ("Android", "Julia", "LinuxRelease", "OSX", "Pyodide", '
    '"Python", "R", "Swift", "SwiftRelease", "DuckDB-Wasm extensions", "Windows")) '
    )
'''
import subprocess
import duckdb
import datetime
import os
import re

#GH_REPO = 'duckdb/duckdb'
#CURR_DATE = datetime.datetime.now().strftime('%Y-%m-%d')
GH_REPO = os.environ.get('GH_REPO')
CURR_DATE = os.environ.get('CURR_DATE')

def fetch_data(command, f_output): # saves command execution results into a file
    data = open(f_output, "w")
    try:
        subprocess.run(command, stdout=data, stderr=True, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Command failed with error: {e.stderr}")

def list_extensions(config) :
    with open(config, "r") as file:
        content = file.read()
    # Adjusted regex for matching after `load(`
    pattern = r"duckdb_extension_load\(\s*([^\s,)]+)"
    matches = re.findall(pattern, content)
    return matches

def list_all_runs(con):
    gh_run_list_file = f"GH_run_list.json"
    gh_run_list_command = [
        "gh", "run", "list",
        "--repo", GH_REPO,
        "--event", "repository_dispatch",
        "--created", CURR_DATE,
        "--limit", "50",
        "--json", "status,conclusion,url,name,createdAt,databaseId,headSha",
        "--jq", (
            '.[] | select(.name == ("OSX", "LinuxRelease", "Windows", "Python")) '
        )
    ]
    fetch_data(gh_run_list_command, gh_run_list_file)
    result = duckdb.sql(f"SELECT name FROM read_json('{ gh_run_list_file }')").fetchall()
    return result

def count_consecutive_failures(nightly_build, con):
    latest_success_rowid = con.execute(f"""
        SELECT rowid
        FROM 'gh_run_list_{ nightly_build }'
        WHERE conclusion = 'success'
        ORDER BY createdAt DESC
    """).fetchone()
    consecutive_failures = latest_success_rowid[0] if latest_success_rowid else -1 # when -1 then all runs in the json file have conclusion 'failure'
    return consecutive_failures

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

def verify_and_test_python_macos(version, full_sha, file_name, architecture, counter, config, nightly_build, runs_on):
    # install passed version of python and pull duckdb
    print(version)
    # if version != '3.10':
    subprocess.run([
        "pyenv", "install", version
    ], check=True)
    subprocess.run([
        "pyenv", "global", version
    ], check=True)
    py_version = subprocess.run([
        f"python{ version }", "--version"
    ], capture_output=True, text=True)
    print(f"Installed Python version: { py_version.stdout }")
    # else:
    #     subprocess.run([
    #         "pyenv", "global", version
    #     ], check=True)
    #     print(subprocess.run(["python --version"], capture_output=True, text=True).stdout)
    # subprocess.run([
    #     "pip", "install",
    #     "-v", "duckdb",
    #     "--pre", "--upgrade"
    # ])
    # verify
    short_sha = duckdb.sql('SELECT source_id FROM pragma_version()').fetchone()[0]
    if sha_matching(short_sha, full_sha, file_name, "Python"):
    # test
        print(f"TESTING EXTENSIONS ON python{ version }")
        extensions = list_extensions(config)
        action=["INSTALL", "LOAD"]
        for ext in extensions:
            res = duckdb.sql(f"SELECT installed FROM duckdb_extensions() WHERE extension_name='{ ext }'").fetchone()
            installed = res[0] if res else None
            print( f"Is { ext } already installed: { installed }")

            if installed == False:
                for act in action:
                    print(f"{ act }ing { ext }...")
                    try:
                        action_result_ouput = duckdb.sql(f"{ act } '{ ext }'")
                        res = duckdb.sql(f"SELECT installed FROM duckdb_extensions() WHERE extension_name='{ ext }'").fetchone()
                        installed = res[0] if res else None
                        if installed != "None":
                            with open(file_name, 'a') as f:
                                if counter == 0:
                                    f.write(f"nightly_build,architecture,runs_on,version,extension,failed_statement\n")
                                    counter += 1
                                f.write(f"{ nightly_build },{ architecture },{ runs_on },{ version },{ ext },{ act }\n")
                    except subprocess.CalledProcessError as e:
                        with open(file_name, 'a') as f:
                            if counter == 0:
                                f.write(f"nightly_build,architecture,runs_on,version,extension,failed_statement\n")
                                counter += 1
                            f.write(f"{ nightly_build },{ architecture },{ runs_on },,{ ext },{ act }\n")
                        print(f"Error running command for extesion { ext }: { e }")
                        print(f"stderr: { e.stderr }")