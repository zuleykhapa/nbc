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
import subprocess
import json
import os
import re
from collections import defaultdict
from shared_functions import fetch_data
from shared_functions import list_all_runs
from shared_functions import count_consecutive_failures

GH_REPO = os.environ.get('GH_REPO', 'duckdb/duckdb')
CURR_DATE = os.environ.get('CURR_DATE', datetime.datetime.now().strftime('%Y-%m-%d'))
REPORT_FILE = f"{ CURR_DATE }_REPORT_FILE.md"
HAS_NO_ARTIFACTS = ('Python', 'Julia', 'Swift', 'SwiftRelease')
SHOULD_BE_TESTED = ('Python', 'OSX', 'LinuxRelease', 'Windows')

def get_value_for_key(key, nightly_build):
    value = duckdb.sql(f"""
        SELECT { key } 
        FROM read_json('{ nightly_build }.json') 
        WHERE status = 'completed' 
        ORDER BY createdAt 
        DESC LIMIT 1;
        """).fetchone()[0]
    return value

def get_nightly_build_run_id(nightly_build):
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
    return nightly_build_run_id

def save_run_data_to_json_files(nightly_build, con, nightly_build_run_id):
    '''
    Fetches GH Actions data related to specified nightly-build and saves it into json files.
        As result "{ nightly_build }.json", "{ nightly_build }_jobs.json" and "{ nightly_build }_artifacts.json"
        files are created. They will be used by create_tables_for_report()
    '''
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

def create_tables_for_report(nightly_build, con, url):
    '''
    In 'run_info_tables.duckdb' file creates 'gh_run_list_{ nightly_build }', 'steps_{ nightly_build }'
        and 'artifacts_{ nightly_build }' tables from json files created on save_run_data_to_json_files()
    Using 'steps' and 'artifacts' tables creates 'artifacts_per_jobs_{ nightly_build }' table 
        for the final report.
    '''
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
    if nightly_build not in HAS_NO_ARTIFACTS:
        print(nightly_build)
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
                FROM 'artifacts_{ nightly_build }'
            )
            WHERE artifacts['name'] LIKE '%binaries%'
        """).fetchone()
    return binaries_count[0] if binaries_count else 0

def get_platform_arch_from_artifact_name(nightly_build, con):
    if nightly_build in HAS_NO_ARTIFACTS:
        platform = str(nightly_build).lower()
        architectures = ['linux_amd64', 'linux_arm64'] if nightly_build == 'Python' else ['x64']
    else:
        '''
        From artifact names in 'artifacts_per_jobs_{ nightly_build }' table create a list of 'items'.
            Each item is in a format like this: [duckdb-binaries-linux_arm64](url)
            Return an array of architectures.
        '''
        result = con.execute(f"""
            SELECT Artifact
            FROM 'artifacts_per_jobs_{ nightly_build }'
            WHERE Artifact LIKE '%64]%';
            """).fetchall()
        items = [row[0] for row in result if row[0] is not None]
        pattern = r"\[duckdb-extensions-(\w+)(?:[_](\w+))?\]\(.*\)" # (\w+)(?:[_](\w+))? finds the words separated by - ; \]\(.*\) handles brackets
        platform = None
        architectures = []
        if items:
            for item in items:
                match = re.match(pattern, item)
                if match:
                    architectures.append(match.group(1))
                    print(match.group(1))
    return architectures 

def main():
    matrix_data = []
    con = duckdb.connect('run_info_tables.duckdb')
    # nightly_build = "InvokeCI"
    result = list_all_runs(con)
    nightly_builds = [row[0] for row in result]
    for nightly_build in nightly_builds:
        nightly_build_run_id = get_nightly_build_run_id(nightly_build)
        save_run_data_to_json_files(nightly_build, con, nightly_build_run_id)
        url = con.execute(f"""
            SELECT url FROM '{ nightly_build }.json'
            """).fetchone()[0]
        create_tables_for_report(nightly_build, con, url)
        
        if nightly_build in SHOULD_BE_TESTED:
            architectures = get_platform_arch_from_artifact_name(nightly_build, con)
            print(nightly_build, architectures)
            if nightly_build == 'OSX':
                for architecture in architectures:
                    matrix_data.append({
                        "nightly_build": nightly_build,
                        "duckdb_arch": architecture,
                        "runs_on": "macos-latest" if architecture == 'osx_arm64' else "macos-13",
                        "run_id": nightly_build_run_id
                    })
            if nightly_build == "Windows" and architecture == 'windows_amd64':
                matrix_data.append({
                    "nightly_build": nightly_build,
                    "duckdb_arch": architecture,
                    "runs_on": "windows-2019",
                    "run_id": nightly_build_run_id
                })
            if nightly_build in ("LinuxRelease", "Python"):
                for architecture in architectures:
                    matrix_data.append({
                        "nightly_build": nightly_build,
                        "duckdb_arch": architecture,
                        "runs_on": "ubuntu-22.04-arm" if architecture == 'linux_arm64' else "ubuntu-latest",
                        "run_id": nightly_build_run_id
                    })
                
    with open("inputs.json", "w") as f:
        json.dump(matrix_data, f, indent=4)

    con.close()
    
if __name__ == "__main__":
    main()