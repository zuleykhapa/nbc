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
            '.[] | select(.name == ("OSX", "LinuxRelease", "Windows")) '
        )
    ]
        # the whole list of builds:
        # "--jq", (
        #     '.[] | select(.name == ("Android", "Julia", "LinuxRelease", "OSX", "Pyodide", '
        #     '"Python", "R", "Swift", "SwiftRelease", "DuckDB-Wasm extensions", "Windows")) '
        # )
    fetch_data(gh_run_list_command, gh_run_list_file)
    result = duckdb.sql(f"SELECT name FROM read_json('{ gh_run_list_file }')").fetchall()
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
    if nightly_build not in has_no_artifacts:
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
    if nightly_build not in has_no_artifacts:
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
    if nightly_build in has_no_artifacts:
        print("nightly_build", nightly_build)
        platform = str(nightly_build).lower()
        print("platform", platform)
        architectures = ['amd64', 'x86_64'] if nightly_build == 'Python' else ['x64']
    else:    
        result = con.execute(f"SELECT Artifact FROM 'artifacts_per_jobs_{ nightly_build }'").fetchall()
        items = [row[0] for row in result if row[0] is not None]
        # artifact names are usually look like this[duckdb-binaries-linux-aarch64](url)  
        # looking up the platform name (linux) and the architecture (linux-aarch64)
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
    build_info["architectures"] = ['osx'] if nightly_build == 'OSX' else architectures
    build_info["platform"] = platform
    
def main():
    matrix_data = []
    con = duckdb.connect('run_info_tables.duckdb')
    # list all nightly-build runs on current date
    result = list_all_runs(con)
    nightly_builds = [row[0] for row in result]
    for nightly_build in nightly_builds:
        build_info = {}
        prepare_data(nightly_build, con, build_info)
        url = con.execute(f"""
            SELECT url FROM '{ nightly_build }.json'
            """).fetchone()[0]
        create_tables_for_report(nightly_build, con, build_info, url)
        
        if build_info.get("failures_count") == 0:
            get_platform_arch_from_artifact_name(nightly_build, con, build_info)
            platform = str(build_info.get("platform"))
            match platform:
                case 'osx':
                    runs_on = [ "macos-latest" ]
                case 'windows':
                    runs_on = [ "windows-2019" ]
                case _:
                    runs_on = [ f"{ platform }-latest" ]
            
            architectures = build_info.get('architectures')
            for architecture in architectures:
                for r_on in runs_on:
                    matrix_data.append({
                        "nightly_build": nightly_build,
                        "platform": platform,
                        "architectures": architecture,
                        "runs_on": r_on,
                        "run_id": build_info.get('nightly_build_run_id')
                    })
        with open("inputs.json", "w") as f:
            json.dump(matrix_data, f, indent=4)

    con.close()
    
if __name__ == "__main__":
    main()