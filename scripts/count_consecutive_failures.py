import duckdb
import argparse
import pandas as pd
import tabulate
import subprocess
import json
import datetime

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
        CREATE OR REPLACE TABLE gh_run_list AS (
            SELECT *
            FROM '{ input_file }')
            ORDER BY createdAt DESC
    """)
    latest_success_rowid = con.execute(f"""
        SELECT rowid
        FROM gh_run_list
        WHERE conclusion = 'success'
        ORDER BY createdAt DESC
    """).fetchone()
    count_consecutive_failures = latest_success_rowid[0] if latest_success_rowid else -1 # when -1 then all runs in the json file have conclusion 'failure'

    tmp_url = con.execute(f"""
                SELECT
                    url
                FROM gh_run_list
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
            FROM gh_run_list
            WHERE conclusion = 'failure'
        """).fetchone()[0]
    
    total_count = con.execute(f"""
        SELECT
            count(*)
        FROM gh_run_list
    """).fetchone()[0]
    
    with open(REPORT_FILE, 'a') as f:
        f.write(f"\n## { nightly_build }\n")            
        f.write(f"\n\n### { nightly_build } nightly-build has not succeeded the previous **{ count_consecutive_failures }** times.\n")
        if count_consecutive_failures < total_count:
            f.write(f"Latest successfull run: [ Run Link ]({ url })\n")

    with open(REPORT_FILE, 'a') as f:
        f.write(f"\n#### Failure Details\n")
        f.write(con.execute(f"""
                    SELECT
                        conclusion as "Conclusion",
                        createdAt as "Created at",
                        url as "URL"
                    FROM gh_run_list
                    WHERE conclusion = 'failure'
                    ORDER BY createdAt DESC
                    LIMIT { count_consecutive_failures }
            """).df().to_markdown(index=False))
        
    return count_consecutive_failures
    
def main():
    output_data = []
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
        "--jq", '.[] | select(.name == "Python" or .name == "LinuxRelease" or .name == "Windows" or .name == "OSX")'
        # "--jq", '.[] | select(.name == "Android" or .name == "Julia" or .name == "LinuxRelease" or .name == "OSX" or .name == "Pyodide" or .name == "Python" or .name == "R" or .name == "Swift" or .name == "SwiftRelease" or .name == "DuckDB-Wasm extensions" or .name == "Windows")'
    ]
    fetch_data(gh_run_list_command,gh_run_list_file)
    result = con.execute(f"SELECT name FROM '{ gh_run_list_file }';").fetchall()
    nightly_builds = [row[0] for row in result]
    print(nightly_builds)
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
        # create_build_report(nightly_build, gh_run_list_file, jobs_file, artifacts_file)
        build_info["run_id"] = run_id
        build_info[f"nightly_build"] = nightly_build
        output_data.append(build_info)
    con.close()
    print(json.dumps(output_data, indent=4))
    
if __name__ == "__main__":
    main()