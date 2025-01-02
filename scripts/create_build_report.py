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
parser = argparse.ArgumentParser()
parser.add_argument("GH_TOKEN")
args = parser.parse_args()
GH_TOKEN = args.GH_TOKEN
has_no_artifacts = ('Python', 'Julia', 'Swift', 'SwiftRelease')

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

def count_consecutive_failures(nightly_build, input_file, url, con):
    input_file = f"{ nightly_build }.json"
    con.execute(f"""
        CREATE OR REPLACE TABLE 'gh_run_list_{ nightly_build }' AS (
            SELECT *
            FROM '{ input_file }')
            ORDER BY createdAt DESC
    """)
    latest_success_rowid = con.execute(f"""
        SELECT rowid
        FROM 'gh_run_list_{ nightly_build }'
        WHERE conclusion = 'success'
        ORDER BY createdAt DESC
    """).fetchone()
    count_consecutive_failures = latest_success_rowid[0] if latest_success_rowid else -1 # when -1 then all runs in the json file have conclusion 'failure'
    return count_consecutive_failures

def list_all_runs(con):
    gh_run_list_file = f"GH_run_list.json"
    gh_run_list_command = [
        "gh", "run", "list",
        "--repo", GH_REPO,
        "--event", "repository_dispatch",
        "--created", CURR_DATE,
        "-L", "50",
        "--json", "status,conclusion,url,name,createdAt,databaseId,headSha",
        "--jq", (
            '.[] | select(.name == "Android" or .name == "Julia" or .name == "LinuxRelease" '
            'or .name == "OSX" or .name == "Pyodide" or .name == "Python" or .name == "R" or .name == "Swift" '
            'or .name == "SwiftRelease" or .name == "DuckDB-Wasm extensions" or .name == "Windows") '
            )
    ]
    fetch_data(gh_run_list_command, gh_run_list_file)
    result = con.execute(f"SELECT name FROM '{ gh_run_list_file }';").fetchall()
    return result

def prepare_data(nightly_build, con, build_info):
    gh_run_list_file = f"{ nightly_build }.json"
    runs_command = [
            "gh", "run", "list",
            "--repo", GH_REPO,
            "--event", "repository_dispatch",
            "--workflow", f"{ nightly_build }",
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
    build_info["run_id"] = run_id

def create_tables_for_report(nightly_build, con):
    input_file = f"{ nightly_build }.json"

    if nightly_build not in has_no_artifacts:
        con.execute(f"""
            CREATE OR REPLACE TABLE 'steps_{ nightly_build }' AS (
                SELECT * FROM read_json('{ nightly_build }_jobs.json')
            )
        """)
        con.execute(f"""
                CREATE OR REPLACE TABLE 'artifacts_{ nightly_build }' AS (
                    SELECT * FROM read_json('{ nightly_build }_artifacts.json')
                );
            """)
        # check if the artifatcs table is not empty
        artifacts_count = con.execute(f"SELECT list_count(artifacts) FROM 'artifacts_{ nightly_build }';").fetchone()[0]
        if artifacts_count > 0:
            con.execute(f"""
                CREATE OR REPLACE TABLE 'artifacts_per_jobs_{ nightly_build }' AS (
                    SELECT
                        t1.job_name AS "Build (Architecture)",
                        t1.conclusion AS "Conclusion",
                        t2.name AS "Artifact",
                        t2.updated_at AS "Uploaded at"
                    FROM (
                        SELECT
                            job_name,
                            steps.name step_name, 
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
                                FROM 'steps_{ nightly_build }'
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
                            FROM 'artifacts_{ nightly_build }'
                            )
                        ORDER BY expires_at
                        ) as t2
                    );
                """)
        else:
            con.execute(f"""
                CREATE OR REPLACE TABLE 'artifacts_per_jobs_{ nightly_build }' AS (
                    SELECT job_name, conclusion 
                    FROM (
                        SELECT unnest(j['steps']) steps, j['name'] job_name, j['conclusion'] conclusion 
                        FROM (
                            SELECT unnest(jobs) j 
                            FROM 'steps_{ nightly_build }'
                            )
                        ) 
                    WHERE steps['name'] LIKE '%upload-artifact%'
                    )
                """)

def create_build_report(nightly_build, con, build_info):
    input_file = f"{ nightly_build }.json"
    url= con.execute(f"SELECT url FROM '{ input_file }'").fetchone()[0]
    failures_count = count_consecutive_failures(nightly_build, input_file, url, con)

    with open(REPORT_FILE, 'a') as f:
        if failures_count == 0:
            f.write(f"\n## { nightly_build }\n")            
            f.write(f"\n\n### { nightly_build } nightly-build has succeeded.\n")            
            f.write(f"Latest run: [ Run Link ]({ url })\n")

        else:
            # failures count = -1 means all runs in the json file have conclusion = 'failure' so we need to update its value
            # we count all runs and do not add a last successfull run link to the report
            if failures_count == -1:
                failures_count = con.execute(f"""
                    SELECT
                        count(*)
                    FROM 'gh_run_list_{ nightly_build }'
                    WHERE conclusion = 'failure'
                """).fetchone()[0]
        
            total_count = con.execute(f"""
                SELECT
                    count(*)
                FROM 'gh_run_list_{ nightly_build }'
            """).fetchone()[0]

            f.write(f"## { nightly_build }\n")            
            if failures_count == total_count:
                f.write(f"### { nightly_build } nightly-build has not succeeded more than **{ failures_count }** times.\n")
            else:
                f.write(f"### { nightly_build } nightly-build has not succeeded the previous **{ failures_count }** times.\n")
            if failures_count < total_count:
                tmp_url = con.execute(f"""
                    SELECT
                        url
                    FROM 'gh_run_list_{ nightly_build }'
                    WHERE conclusion = 'success'
                    ORDER BY createdAt DESC
                """).fetchone()
                latest_success_url = tmp_url[0] if tmp_url else ''
                f.write(f"Latest successfull run: [ Run Link ]({ latest_success_url })\n")

            f.write(f"\n#### Failure Details\n")
            failure_details = con.execute(f"""
                SELECT
                    conclusion as "Conclusion",
                    createdAt as "Created at",
                    url as "URL"
                FROM 'gh_run_list_{ nightly_build }'
                WHERE conclusion = 'failure'
                ORDER BY createdAt DESC
                LIMIT { failures_count }
            """).df()
            f.write(failure_details.to_markdown(index=False))
            
        # check if the artifatcs table is not empty
        if nightly_build not in has_no_artifacts:
            f.write(f"\n#### Workflow Artifacts\n")
            artifacts_per_job = con.execute(f"""
                SELECT * FROM 'artifacts_per_jobs_{ nightly_build }';
                """).df()
            f.write(artifacts_per_job.to_markdown(index=False))
        else:
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
    if nightly_build in has_no_artifacts:
        platform = str(nightly_build).lower()
        architectures = ['x86_64', 'aarch64'] if nightly_build == 'Python' else 'x64'
    else:    
        result = con.execute(f"SELECT Artifact FROM 'artifacts_per_jobs_{ nightly_build }'").fetchall()
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
    build_info = {}
    con = duckdb.connect('run_info_tables.duckdb')
    # list all nightly-build runs on current date
    result = list_all_runs(con)
    nightly_builds = [row[0] for row in result]
    # create complete report
    for nightly_build in nightly_builds:
        prepare_data(nightly_build, con, build_info)
        create_tables_for_report(nightly_build, con)
        
        build_info = create_build_report(nightly_build, con, build_info)
        ###########
        # create_tables_for_report(nightly_build, gh_run_list_file, jobs_file, artifacts_file)
        ###########
        
        if build_info["failures_count"] == 0:
            build_info["nightly_build"] = nightly_build
            info = get_info_from_artifact_name(nightly_build, con)
            build_info["platform"] = info[0]
            # print("1️⃣", nightly_build, ": ", info)
            build_info["architectures"] = info[1] if len(info[1]) > 0 else [ info[0] ]
            platform = str(build_info.get("platform"))
            # TODO: for Python there are more than one runners
            match platform:
                case 'osx':
                    build_info["runs_on"] = [ "macos-latest" ]
                case 'windows':
                    build_info["runs_on"] = [ "windows-2019" ]
                case _:
                    build_info["runs_on"] = [ f"{ info[0] }-latest" ]
            runs_on = build_info.get("runs_on")
            # build_info["runs_on"] = [ f"{ info[0] }-latest" ] if info[0] not in ('osx', 'windows') elif info[0] == 'windows' [ "macos-latest" ]
            ###################
            # VERIFY AND TEST #
            ###################
            # trigger workflow run
            REPO = 'zuleykhapa/nbc'
            WORKFLOW_FILE = 'Test.yml'
            # it's possible to trigger workflow runs like this only on 'main'
            REF = 'main'
            try:
                print(f"Triggering workflow for {nightly_build} {platform}...")
                trigger_command = [
                    "gh", "workflow", "dispatch",
                    "--repo", REPO,
                    WORKFLOW_FILE,
                    "--ref", REF,
                    "-f", f"nightly_build={nightly_build}",
                    "-f", f"platform={platform}",
                    "-f", f"architectures={architectures}",
                    "-f", f"runs_on={runs_on}",
                    "-f", f"run_id={run_id}"
                ]
                subprocess.run(trigger_command, check=True)
                print(f"Workflow for {nightly_build} {platform} triggered successfully.")
            except subprocess.CalledProcessError as e:
                print(f"Failed to trigger workflow for {nightly_build} {platform}: {e}")

            
        # TODO: create_test_report(nightly_build, con)
        # create_build_report(nightly_build, con)
        
        output_data.append(build_info)

    con.close()

    # write outputs into a file which will be passed into a script triggering the test runs
    # print(json.dumps(output_data, indent=4))
    with open("output_data.json", "w") as file:
        json.dump(output_data, file, indent=4)
    
if __name__ == "__main__":
    main()