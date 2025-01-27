'''
The scripts/create_tables_and_inputs.py script does two jobs:
    1. Creates a `run_info_tables.duckdb` file
    2. Generates `input.json` file
    
`run_info_tables.duckdb` file is uploaded as a job artifact and used on later steps.
It contains the tables:
    'gh_run_list_{ nightly_build }',
    'steps_{ nightly_build }',
    'artifacts_{ nightly_build }',
    'artifacts_per_jobs_{ nightly_build }' - used as it is in `create_build_report.py`

`input.json` file contains an array of json objects which will be used to create next job's matrix
    or, in case all listed nightly-builds had failed, an empty array, then the next job will be skipped. 
Each object has following fields:
{
    "nightly_build": "LinuxRelease",
    "platform": "linux",
    "architectures": "amd64",
    "runs_on": "ubuntu-latest",
    "run_id": "12021416084"
}
If any of nightly-builds uploads builds for different architectures, then
    for each architecture a separate object is being generated.

Currently we're checking only three nightly-build names: OSX, LinuxRelease, Windows.
    It's possible to check more of them if adding more values to the list of "--jq"
    parameters in `list_all_runs()` from shared_functions.py:
        "--jq", (
            '.[] | select(.name == ("OSX", "LinuxRelease", "Windows")) '

Can be tested locally running 'python scripts/create_tables_and_inputs.py'.
'''

import duckdb
import datetime
import argparse
import pandas as pd
import tabulate
import subprocess
import json
import os
import glob
import re
from collections import defaultdict
from shared_functions import fetch_data
from shared_functions import list_all_runs
from shared_functions import count_consecutive_failures

GH_REPO = os.environ.get('GH_REPO', 'duckdb/duckdb')
CURR_DATE = os.environ.get('CURR_DATE', datetime.datetime.now().strftime('%Y-%m-%d'))
REPORT_FILE = f"{ CURR_DATE }_REPORT_FILE.md"
HAS_NO_ARTIFACTS = ('Python', 'Julia', 'Swift', 'SwiftRelease')

def get_value_for_key(key, nightly_build):
    value = duckdb.sql(f"""
        SELECT { key } 
        FROM read_json('{ nightly_build }.json') 
        WHERE status = 'completed' 
        ORDER BY createdAt 
        DESC LIMIT 1;
        """).fetchone()[0]
    return value

def save_run_data_to_json_files(nightly_build, con, build_info):
    '''
    Fetches GH Actions data related to specified nightly-build and saves it into json files,
        populates build_info dict with nightly_build_run_id value.
        As result "{ nightly_build }.json", "{ nightly_build }_jobs.json" and "{ nightly_build }_artifacts.json"
        files are created. They will be used by create_tables_for_report()
    '''
    gh_run_list_file = f"{ nightly_build }.json"
    runs_command = [
            "gh", "run", "list",
            "--repo", GH_REPO,
            "--event", "repository_dispatch",
            "--workflow", f"{ nightly_build }",
            "--json", "status,conclusion,url,name,createdAt,databaseId,headSha"
        ]
    fetch_data(runs_command, gh_run_list_file)
    nightly_build_run_id = get_value_for_key('databaseId', nightly_build)
    jobs_file = f"{ nightly_build }_jobs.json"
    jobs_command = [
            "gh", "run", "view",
            "--repo", GH_REPO,
            f"{ nightly_build_run_id }",
            "--json", "jobs"
        ]
    fetch_data(jobs_command, jobs_file)
    artifacts_file = f"{ nightly_build }_artifacts.json"
    artifacts_command = [
            "gh", "api",
            f"repos/{ GH_REPO }/actions/runs/{ nightly_build_run_id }/artifacts"
        ]
    fetch_data(artifacts_command, artifacts_file)
    build_info["nightly_build_run_id"] = nightly_build_run_id

def create_tables_for_report(nightly_build, con, build_info, url):
    '''
    In 'run_info_tables.duckdb' file creates 'gh_run_list_{ nightly_build }', 'steps_{ nightly_build }'
        and 'artifacts_{ nightly_build }' tables from json files created on save_run_data_to_json_files()
    Using 'steps' and 'artifacts' tables creates 'artifacts_per_jobs_{ nightly_build }' table 
        for the final report.
    '''
    if nightly_build not in HAS_NO_ARTIFACTS:
        con.execute(f"""
            CREATE OR REPLACE TABLE 'gh_run_list_{ nightly_build }' AS (
                SELECT *
                FROM '{ nightly_build }.json')
                ORDER BY createdAt DESC
        """)
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
            # Given a job and its steps, we want to find the artifacts uploaded by the job 
            # and make sure every 'upload artifact' step has indeed uploaded the expected artifact.
            con.execute(f"""
                SET VARIABLE base_url = "{ url }/artifacts/";
                CREATE OR REPLACE TABLE 'artifacts_per_jobs_{ nightly_build }' AS (
                    SELECT
                        t1.job_name AS "Build (Architecture)",
                        t1.conclusion AS "Conclusion",
                        '[' || t2.name || '](' || getvariable('base_url') || t2.artifact_id || ')' AS "Artifact",
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
                            art.updated_at updated_at,
                            art.id artifact_id
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

def get_binaries_count(nightly_build, con):
    binaries_count = [0]
    if nightly_build not in HAS_NO_ARTIFACTS:
        binaries_count = con.execute(f"""
            SELECT count(artifacts['name'])
            FROM (
                SELECT unnest(artifacts) AS artifacts
                FROM artifacts_{ nightly_build }
            )
            WHERE artifacts['name'] LIKE '%binaries%'
        """).fetchone()
    return binaries_count[0] if binaries_count else 0

def get_platform_arch_from_artifact_name(nightly_build, con, build_info):
    if nightly_build in HAS_NO_ARTIFACTS:
        print("nightly_build", nightly_build)
        platform = str(nightly_build).lower()
        print("platform", platform)
        architectures = ['amd64', 'x86_64'] if nightly_build == 'Python' else ['x64']
    else:
        '''
        From artifact names in 'artifacts_per_jobs_{ nightly_build }' table create a list of 'items'.
            Each item is in a format like this: [duckdb-binaries-linux-aarch64](url)
            Create an array of architectures and save it and a platform value to 'build_info'
        '''
        result = con.execute(f"SELECT Artifact FROM 'artifacts_per_jobs_{ nightly_build }'").fetchall()
        items = [row[0] for row in result if row[0] is not None]
        pattern = r"\[duckdb-binaries-(\w+)(?:[-_](\w+))?\]\(.*\)" # (\w+)(?:[-_](\w+))? finds the words separated by - or _; \]\(.*\) handles brackets
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
    build_info["architectures"] = [ 'x86_64', 'arm64' ] if nightly_build == 'OSX' else architectures
    build_info["platform"] = platform

def get_binary_name(nightly_build, platform, architecture):
    if nightly_build == 'OSX':
        return 'osx'
    elif architecture == 'linux-amd64':
        return platform
    else:
        return architecture

def get_runner(platform, architecture):
    match platform:
        case 'osx':
            return "macos-latest" if architecture == 'arm64' else "macos-13"
        case 'windows':
            return "windows-2019"
        case 'linux':
            return "ubuntu-22.04-arm" if architecture == 'linux-aarch64' else "ubuntu-latest"
        case _:
            return "ubuntu-latest"

def main():
    matrix_data = []
    con = duckdb.connect('run_info_tables.duckdb')
    # list all nightly-build runs on current date to get all nightly-build names
    result = list_all_runs(con)
    nightly_builds = [row[0] for row in result]
    for nightly_build in nightly_builds:
        build_info = {}
        save_run_data_to_json_files(nightly_build, con, build_info)
        url = con.execute(f"""
            SELECT url FROM '{ nightly_build }.json'
            """).fetchone()[0]
        create_tables_for_report(nightly_build, con, build_info, url)
        
        if count_consecutive_failures(nightly_build, con) == 0 or get_binaries_count(nightly_build, con):
            get_platform_arch_from_artifact_name(nightly_build, con, build_info)
            platform = str(build_info.get("platform"))
            architectures = build_info.get('architectures')
            for architecture in architectures:
                if architecture != 'windows-arm64':
                    matrix_data.append({
                        "nightly_build": nightly_build,
                        "architectures": architecture,
                        "runs_on": get_runner(platform,architecture),
                        "run_id": build_info.get('nightly_build_run_id'),
                        "name": get_binary_name(nightly_build, platform, architecture)
                    })

    # matrix_data.append({
    #     "nightly_build": "LinuxRelease",
    #     "architectures": "linux-aarch64",
    #     "runs_on": "ubuntu-latest",
    #     "run_id": "12021416084",
    #     "name": "linux-aarch64"
    # })
    # matrix_data.append({
    #     "nightly_build": "LinuxRelease",
    #     "architectures": "linux-amd64",
    #     "runs_on": "ubuntu-latest",
    #     "run_id": "12021416084",
    #     "name": "linux"
    # })
    # matrix_data.append({
    #     "nightly_build": "Windows",
    #     "architectures": "windows-amd64",
    #     "runs_on": "windows-2019",
    #     "run_id": "12820190894",
    #     "name": "windows-amd64"
    # })
    # matrix_data.append({
    #     "nightly_build": "OSX",
    #     "architectures": "x86_64",
    #     "runs_on": "macos-latest",
    #     "run_id": "12642824816",
    #     "name": "osx"
    # })
    # matrix_data.append({
    #     "nightly_build": "OSX",
    #     "architectures": "arm64",
    #     "runs_on": "macos-13",
    #     "run_id": "12642824816",
    #     "name": "osx"
    # })

    with open("inputs.json", "w") as f:
        json.dump(matrix_data, f, indent=4)

    con.close()
    
if __name__ == "__main__":
    main()