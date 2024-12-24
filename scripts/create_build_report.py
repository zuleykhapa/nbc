import duckdb
import argparse
import pandas as pd
import tabulate
import subprocess
import json
import datetime
import os
import glob
import re
from collections import defaultdict

GH_REPO = 'duckdb/duckdb'
CURR_DATE = datetime.datetime.now().strftime('%Y-%m-%d')
REPORT_FILE = f"{ CURR_DATE }_REPORT_FILE.md"

def get_value_for_key(key, nightly_build):
    value = duckdb.sql(f"""
        SELECT { key } 
        FROM read_json('{ nightly_build }.json') 
        WHERE status = 'completed' 
        ORDER BY createdAt 
        DESC LIMIT 1;
        """).fetchone()[0]
    return value
    
def fetch_data(command, f_output): # saves command execution results into a file
    data = open(f_output, "w")
    try:
        subprocess.run(command, stdout=data, stderr=True, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Command failed with error: {e.stderr}")

# count consecutive failures
def count_consecutive_failures(nightly_build, input_file, url, con):
    con.execute(f"""
        CREATE OR REPLACE TABLE gh_run_list_{ nightly_build } AS (
            SELECT *
            FROM '{ input_file }')
            ORDER BY createdAt DESC
    """)
    latest_success_rowid = con.execute(f"""
        SELECT rowid
        FROM gh_run_list_{ nightly_build }
        WHERE conclusion = 'success'
        ORDER BY createdAt DESC
    """).fetchone()
    count_consecutive_failures = latest_success_rowid[0] if latest_success_rowid else -1 # when -1 then all runs in the json file have conclusion 'failure'

    tmp_url = con.execute(f"""
                SELECT
                    url
                FROM gh_run_list_{ nightly_build }
                WHERE conclusion = 'success'
                ORDER BY createdAt DESC
            """).fetchone()
    url = tmp_url[0] if tmp_url else ''

    if count_consecutive_failures == 0:
        with open(REPORT_FILE, 'a') as f:
            f.write(f"\n## { nightly_build }\n")            
            f.write(f"\n\n### { nightly_build } nightly-build has succeeded.\n")            
            f.write(f"Latest run: [ Run Link ]({ url })\n")
            return count_consecutive_failures
    # since all runs in the json file have conclusion = 'failure', we count them all 
    # and don't include the link to the last successfull run in a report
    if count_consecutive_failures == -1:
        count_consecutive_failures = con.execute(f"""
            SELECT
                count(*)
            FROM gh_run_list_{ nightly_build }
            WHERE conclusion = 'failure'
        """).fetchone()[0]
    
    total_count = con.execute(f"""
        SELECT
            count(*)
        FROM gh_run_list_{ nightly_build }
    """).fetchone()[0]
    
    with open(REPORT_FILE, 'a') as f:
        f.write(f"\n## { nightly_build }\n")            
        f.write(f"\n\n### { nightly_build } nightly-build has not succeeded the previous **{ count_consecutive_failures }** times.\n")
        if count_consecutive_failures < total_count:
            f.write(f"Latest successfull run: [ Run Link ]({ url })\n")

    with open(REPORT_FILE, 'a') as f:
        f.write(f"\n#### Failure Details\n")
        f.write(con.execute(f"""
                    CREATE OR REPLACE TABLE failure_details_{ nightly_build } AS (
                        SELECT
                            conclusion as "Conclusion",
                            createdAt as "Created at",
                            url as "URL"
                        FROM gh_run_list_{ nightly_build }
                        WHERE conclusion = 'failure'
                        ORDER BY createdAt DESC
                        LIMIT { count_consecutive_failures }
                    )
            """).df().to_markdown(index=False))
    return count_consecutive_failures

def create_build_report(nightly_build, con):
    input_file = f"{ nightly_build }.json"
    url= con.execute(f"SELECT url FROM '{ input_file }'").fetchone()[0]

    failures_count = count_consecutive_failures(nightly_build, input_file, url, con)

    if nightly_build not in ('Python', 'Julia'):
        
        con.execute(f"""
            CREATE OR REPLACE TABLE steps_{ nightly_build } AS (
                SELECT * FROM read_json('{ nightly_build }_jobs.json')
            )
        """)
        con.execute(f"""
                CREATE OR REPLACE TABLE artifacts_{ nightly_build } AS (
                    SELECT * FROM read_json('{ nightly_build }_artifacts.json')
                );
            """)
        with open(REPORT_FILE, 'a') as f:
            f.write(f"\n#### Workflow Artifacts \n")
            # check if the artifatcs table is not empty
            artifacts_count = con.execute(f"SELECT list_count(artifacts) FROM artifacts_{ nightly_build };").fetchone()[0]
            if artifacts_count > 0:
                f.write(con.execute(f"""
                    CREATE OR REPLACE TABLE artifacts_per_jobs_{ nightly_build } AS (
                        SELECT
                            t1.job_name AS "Build (Architecture)",
                            t1.conclusion AS "Conclusion",
                            t2.name AS "Artifact",
                            t2.updated_at AS "Uploaded at"
                        FROM (
                            SELECT
                                job_name,
                                steps.conclusion conclusion,
                                steps.startedAt startedAt
                            FROM (
                                SELECT
                                    unnest(steps) steps,
                                    job_name 
                                FROM (
                                    SELECT
                                        unnest(jobs)['steps'] steps,
                                        unnest(jobs)['name'] job_name 
                                    FROM steps_{ nightly_build }
                                    )
                                )
                            WHERE steps['name'] LIKE '%upload%'
                            ORDER BY 
                                conclusion DESC,
                                startedAt
                            ) t1
                        POSITIONAL JOIN (
                            SELECT
                                art.name,
                                art.expires_at expires_at,
                                art.updated_at updated_at
                            FROM (
                                SELECT
                                    unnest(artifacts) art
                                FROM artifacts_{ nightly_build }
                                )
                            ORDER BY expires_at
                            ) as t2
                        );
                    """).df().to_markdown(index=False)
                )
            else:
                f.write(duckdb.query(f"""
                    SELECT job_name, conclusion 
                    FROM (
                        SELECT unnest(j['steps']) steps, j['name'] job_name, j['conclusion'] conclusion 
                        FROM (
                            SELECT unnest(jobs) j 
                            FROM steps_{ nightly_build }
                            )
                        ) 
                        WHERE steps['name'] LIKE '%upload-artifact%'
                    """).to_df().to_markdown(index=False)
                )
    else:
        with open(REPORT_FILE, 'a') as f:
            f.write(f"**{ nightly_build }** run doesn't upload artifacts.\n\n")
    return { 
        "failures_count": failures_count,
        "url": url
        }

def get_python_versions_from_run(run_info_file):
    with open(run_info_file, "r") as file:
        content = file.read()
        pattern = r"cp([0-9]+)-.*"
        matches = sorted(set(re.findall(pattern, content)))
        # puts a '.' after the first character: '310' => '3.10'
        result = [word[0] + '.' + word[1:] if len(word) > 1 else word + '.' for word in matches]
        return result

def verify_python_build(run_id):
    run_info_file = "python_run_info.md"
    run_info_command = [
        "gh", "run", "view",
        "--repo", GH_REPO,
        run_id,
        "-v"
        ]
    fetch_data(run_info_command, run_info_file)
    python_versions = get_python_versions_from_run(run_info_file)
    install_command = "pip install duckdb"
    version_commad = "duckdb --version"
    for version in python_versions:
        print(version)

def verify_version(nightly_build, tested_binary, file_name, run_id, architecture):
    # print("3️⃣", nightly_build, tested_binary, architecture)
    gh_headSha_command = [
        "gh", "run", "view",
        f"{ run_id }",
        "--repo", GH_REPO,
        "--json", "headSha",
        "-q", ".headSha"
    ]
    full_sha = subprocess.run(gh_headSha_command, check=True, text=True, capture_output=True).stdout.strip()
    if architecture.count("aarch64") | architecture.count("arm64"):
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
        with open(file_name, 'a') as f:
            f.write(f"- The version of { nightly_build } build ({ short_sha }) doesn't match to the version triggered the build ({ full_sha }).\n")
        return False
    print(f"The versions of { nightly_build} build match: ({ short_sha }) and ({ full_sha }).\n")
    return True

def get_info_from_artifact_name(nightly_build, con):
    if nightly_build in ('Python', 'Julia'):
        platform = str(nightly_build).lower()
        architectures = ['x86_64', 'aarch64'] if nightly_build == 'Python' else 'x64'
    else:    
        result = con.execute(f"SELECT Artifact FROM artifacts_per_jobs_{ nightly_build }").fetchall()
        items = [row[0] for row in result if row[0] is not None]
        # artifact names are usually look like this duckdb-binaries-linux-aarch64
        # looking up the platform name (linux) and the architecture (linux-aarch64)
        pattern = r"duckdb-binaries-(\w+)(?:[-_](\w+))?"
        platform = None
        architectures = []
        if items:
            for item in items:
                match = re.match(pattern, item)
                if match:
                    platform = match.group(1)
                    arch_suffix = match.group(2)
                    if arch_suffix:
                        architectures.append(f"{ platform }-{ arch_suffix }")
    return platform, architectures

    
def main():
    output_data = []
    # build_info = {}
    con = duckdb.connect('run_info_tables.duckdb')
    # list all nightly-build runs on current date
    gh_run_list_file = f"GH_run_list.json"
    gh_run_list_command = [
        "gh", "run", "list",
        "--repo", GH_REPO,
        "--event", "repository_dispatch",
        "--created", CURR_DATE,
        "-L", "50",
        "--json", "status,conclusion,url,name,createdAt,databaseId,headSha",
        "--jq", '.[] | select(.name == "Windows" or .name == "Python" or .name == "LinuxRelease" or .name == "OSX")'
        # "--jq", '.[] | select(.name == "Android" or .name == "Julia" or .name == "LinuxRelease" or .name == "OSX" or .name == "Pyodide" or .name == "Python" or .name == "R" or .name == "Swift" or .name == "SwiftRelease" or .name == "DuckDB-Wasm extensions" or .name == "Windows")'
    ]
    fetch_data(gh_run_list_command, gh_run_list_file)
    result = con.execute(f"SELECT name FROM '{ gh_run_list_file }';").fetchall()
    nightly_builds = [row[0] for row in result]
    print("✅", nightly_builds)
    # create complete report
    for nightly_build in nightly_builds:
        gh_run_list_file = f"{ nightly_build }.json"
        runs_command = [
                "gh", "run", "list",
                "--repo", GH_REPO,
                "--event", "repository_dispatch",
                "--workflow", nightly_build,
                "--json", "status,conclusion,url,name,createdAt,databaseId,headSha"
            ]
        fetch_data(runs_command, gh_run_list_file)
        run_id = get_value_for_key('databaseId', nightly_build)
        jobs_file = f"{ nightly_build }_jobs.json"
        jobs_command = [
                "gh", "run", "view",
                "--repo", GH_REPO,
                f"{ run_id }",
                "--json", "jobs"
            ]
        fetch_data(jobs_command, jobs_file)
        artifacts_file = f"{ nightly_build }_artifacts.json"
        artifacts_command = [
                "gh", "api",
                f"repos/{ GH_REPO }/actions/runs/{ run_id }/artifacts"
            ]
        fetch_data(artifacts_command, artifacts_file)

        build_info = create_build_report(nightly_build, con)
        ###########
        # create_build_report(nightly_build, gh_run_list_file, jobs_file, artifacts_file)
        ###########
        
        if build_info["failures_count"] == 0:
            # build_info["failures_count"] = result["failures_count"]
            # build_info["run_url"] = result["url"]
            build_info["run_id"] = run_id
            build_info["nightly_build"] = nightly_build
            info = get_info_from_artifact_name(nightly_build, con)
            build_info["platform"] = info[0]
            # print("1️⃣", nightly_build, ": ", info)
            build_info["architectures"] = info[1] if len(info[1]) > 0 else info[0]
            ###########
            # print("2️⃣", build_info["failures_count"], "🦑")
            # if nightly_build == 'Python':
            #     verify_python_build(run_id)
            # else:
            #     path_pattern = os.path.join("duckdb_path", "duckdb*")
            #     matches = glob.glob(path_pattern)
            #     if matches:
            #         tested_binary = os.path.abspath(matches[0])
            #         print(f"Found binary: { tested_binary }")
            #     else:
            #         raise FileNotFoundError(f"No binary matching { path_pattern } found in duckdb_path dir.")
            #     print(f"{ nightly_build }: VERIFY BUILD SHA")
            #     architectures = build_info["architectures"]
            #     if architectures:
            #         for architecture in architectures:
            #             if verify_version(nightly_build, tested_binary, REPORT_FILE, run_id, architecture):
            #                 print(f"{ nightly_build }: TEST EXTENSIONS")    
            #                 # test_extensions(tested_binary, REPORT_FILE)
            # print(f"{ nightly_build }: FINISH")
        
        output_data.append(build_info)

    con.close()
    print(json.dumps(output_data, indent=4))
    
if __name__ == "__main__":
    main()