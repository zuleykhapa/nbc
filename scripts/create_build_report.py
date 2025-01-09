import duckdb
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
            '.[] | select(.name == ("Windows")) '
        )
        # the whole list of builds:
        # "--jq", (
        #     '.[] | select(.name == ("Android", "Julia", "LinuxRelease", "OSX", "Pyodide", '
        #     '"Python", "R", "Swift", "SwiftRelease", "DuckDB-Wasm extensions", "Windows")) '
        # )
    ]
    fetch_data(gh_run_list_command, gh_run_list_file)
    result = con.execute(f"SELECT name FROM '{ gh_run_list_file }';").fetchall()
    return result

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
        
        # add extensions
        file_name_pattern = f"list_failed_ext_{ nightly_build }_*/list_failed_ext_{ nightly_build }_*.csv"
        failed_extensions = con.execute(f"""
            CREATE TABLE ext_{ nightly_build } AS
                SELECT * FROM read_csv(f'{ file_name_pattern }')
        """).df()
        f.write(failed_extensions.to_markdown(index=False))
    




    build_info["failures_count"] = failures_count
    build_info["url"] = url
    
def main():
    con = duckdb.connect('run_info_tables.duckdb')
    # list all nightly-build runs on current date
    result = list_all_runs(con)
    nightly_builds = [row[0] for row in result]
    result = con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'").fetchall()
    print(result)

    # create complete report
    for nightly_build in nightly_builds:
        build_info = {}
        url = con.execute(f"""
            SELECT url FROM 'gh_run_list_{ nightly_build }' LIMIT 1
            """).fetchone()[0]
        create_build_report(nightly_build, con, build_info, url)    
    con.close()
    
if __name__ == "__main__":
    main()