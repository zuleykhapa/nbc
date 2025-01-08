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

def count_consecutive_failures(nightly_build, url, con):
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
    consecutive_failures = latest_success_rowid[0] if latest_success_rowid else -1 # when -1 then all runs in the json file have conclusion 'failure'
    return consecutive_failures

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
            '.[] | select(.name == ("Windows")) '
            # '.[] | select(.name == ("LinuxRelease", "OSX", "Windows", "Python")) '
        )
        # "--jq", (
        #     '.[] | select(.name == ("Android", "Julia", "LinuxRelease", "OSX", "Pyodide", '
        #     '"Python", "R", "Swift", "SwiftRelease", "DuckDB-Wasm extensions", "Windows")) '
        # )
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
    # nightly_build_run_id = get_value_for_key('databaseId', nightly_build)
    nightly_build_run_id ="12540028046"
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

def create_build_report(nightly_build, con, build_info, url):
    failures_count = count_consecutive_failures(nightly_build, url, con)

    with open(REPORT_FILE, 'a') as f:
        if failures_count == 0:
            f.write(f"\n## { nightly_build }\n")            
            f.write(f"\n\n### { nightly_build } nightly-build has succeeded.\n")            
            f.write(f"Latest run: [ Run Link ]({ url })\n")

        else:
            # failures_count = -1 means all runs in the json file have conclusion = 'failure' 
            # so we need to update its value.
            # We count all runs and do not add a last successfull run link to the report
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
                    LIMIT 1
                """).fetchall()
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
    build_info["failures_count"] = failures_count
    build_info["url"] = url

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
        architectures = ['amd64', 'aarch64'] if nightly_build == 'Python' else 'x64'
    else:    
        result = con.execute(f"SELECT Artifact FROM 'artifacts_per_jobs_{ nightly_build }'").fetchall()
        items = [row[0] for row in result if row[0] is not None]
        # artifact names are usually look like this[duckdb-binaries-linux-aarch64](url)  
        # looking up the platform name (linux) and the architecture (linux-aarch64)
        pattern = r"\[duckdb-binaries-(\w+)(?:[-_](\w+))?\]\(.*\)"
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

def get_current_run_id(build_info, REPO):
    curr_id_file = "curr_id.json"
    curr_id_command = [
        "gh", "run", "list",
        "--repo", REPO,
        "--workflow", "Check Nightly Build Status",
        "--created", CURR_DATE,
        "--limit", "1",
        "--json", "databaseId",
        # "--jq", '.[] | select(.status == "in_progress") '
    ]
    fetch_data(curr_id_command, curr_id_file)
    result = duckdb.sql(f"SELECT databaseId FROM '{ curr_id_file }';").fetchone()[0]
    return result
    
def main():
    output_data = []
    con = duckdb.connect('run_info_tables.duckdb')
    # list all nightly-build runs on current date
    result = list_all_runs(con)
    nightly_builds = [row[0] for row in result]
    # create complete report
    for nightly_build in nightly_builds:
        build_info = {}
        prepare_data(nightly_build, con, build_info)
        url = con.execute(f"SELECT url FROM '{ nightly_build }.json'").fetchone()[0]
        create_tables_for_report(nightly_build, con, build_info, url)
        create_build_report(nightly_build, con, build_info, url)
        
        
        # if build_info.get("failures_count") == 0:
        if build_info.get("failures_count") != 0:
            print("🦑", nightly_build, ":", build_info.get("failures_count"))
            get_platform_arch_from_artifact_name(nightly_build, con, build_info)
            # if get_binaries_count(nightly_build, con) > 0 or nightly_build == 'Python':
            # if nightly_build == 'Python':
            platform = str(build_info.get("platform"))
            match platform:
                case 'osx':
                    runs_on = [ "macos-latest" ]
                case 'windows':
                    runs_on = [ "windows-2019" ]
                case 'python':
                    runs_on = [ "ubuntu-latest" ]
                    # runs_on = [ "macos-latest", "windows-2019", "ubuntu-latest" ]
                case _:
                    runs_on = [ f"{ platform }-latest" ]

            ###################
            # VERIFY AND TEST #
            ###################
            # trigger workflow run
            REPO = 'zuleykhapa/nbc'
            WORKFLOW_FILE = 'Test.yml'
            # it's possible to trigger workflow runs like this only on 'main'
            REF = 'main'
            curr_run_id = get_current_run_id(build_info, REPO)
            print(nightly_build)
            print(platform)
            print(build_info.get("architectures"))
            print(runs_on)
            print("NB:", build_info.get("nightly_build_run_id"))
            print("curr:", build_info.get(curr_run_id))

            try:
                print(f"Triggering workflow for { nightly_build } { platform }...")
                trigger_command = [
                    "gh", "workflow", "run",
                    "--repo", REPO,
                    WORKFLOW_FILE,
                    "--ref", REF,
                    "-f", f"nightly_build={ nightly_build }",
                    "-f", f"platform={ platform }",
                    "-f", f"architectures={ build_info.get('architectures') }",
                    "-f", f"runs_on={ runs_on }",
                    "-f", f"run_id=12540028046",
                    # "-f", f"run_id={ build_info.get('nightly_build_run_id') }",
                    "-f", f"calling_run_id={ curr_run_id }"
                    # "-f", f"calling_run_id=12661739527"
                ]
                subprocess.run(trigger_command, check=True)
                print(f"Workflow for { nightly_build } { platform } triggered successfully.")
            except subprocess.CalledProcessError as e:
                print(f"Failed to trigger workflow for { nightly_build } { platform }: { e }")
        

            
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