'''
For the WeeklyRegression we would like to only know which builds had failed and 
    how many consecutive failures there are.

This script gets information about the nightly-build runs for
    "Android", "Julia", "LinuxRelease", "OSX", "Python", "R", "Swift",
    "SwiftRelease", "DuckDB-Wasm extensions", "Windows" and
    creates a table containing only failed builds.

1. create_failed_builds_table() - fetch `gh run list` of mentioned above nightly-builds into a `GH_run_list.json`.
    Create table `failed' containing the nightly-builds names and urls of the nightly builds which failed on current date.
2. gets nightly-builds names array.
3. create_failures_count_table() - to create this table we need to call gh API again, for each nightly-build and 
    count consecutive failures. We fetch 20 entries and if al of them have conclusion = 'failure', then 
    we call gh API again, but this time get 100 entries to count consecutive failures.
4. create_report_table() - create a table which goes to the WeeklyRegression report like this:

| Workflow name | Consecutive failures | Last successfull run |
|:--------------|:---------------------|:---------------------|
| [R](URL)      |                     2|                      |

'''
import duckdb
import pandas as pd
import tabulate
import subprocess
import json

GH_REPO = 'duckdb/duckdb'
REPORT_FILE = "nightly_builds_status.md"
COUNT_FILE = 'count.csv'
NIGHTLY_BUILDS = ("Android", "Julia", "Swift", "SwiftRelease", "InvokeCI")

def fetch_data(command, f_output): # saves command execution results into a file
    data = open(f_output, "w")
    try:
        subprocess.run(command, stdout=data, stderr=True, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Command failed with error: {e.stderr}")

def get_run_info(nightly_build, con, lines = "50"):
    gh_run_list_file = f"{ nightly_build }.json"
    runs_command = [
            "gh", "run", "list",
            "--repo", GH_REPO,
            "--event", "repository_dispatch",
            "--workflow", f"{ nightly_build }",
            "-L", lines,
            "--json", "status,conclusion,url,name,createdAt,databaseId,headSha"
        ]
    fetch_data(runs_command, gh_run_list_file)

def count_consecutive_failures(nightly_build, con):
    input_file = f"{ nightly_build }.json"
    con.execute(f"""
        CREATE OR REPLACE TABLE 'gh_run_list_{ nightly_build }' AS (
            SELECT *
            FROM '{ input_file }')
            ORDER BY createdAt DESC
    """)
    latest_success_rowid = con.execute(f"""
        SELECT min(rowid) 
        FROM 'gh_run_list_{ nightly_build }' 
        WHERE conclusion = 'success'
    """).fetchone()
    total_count = con.execute(f"""
        SELECT max(rowid) 
        FROM 'gh_run_list_{ nightly_build }'
    """).fetchone()
    total_count = total_count[0]
    rowid = total_count if latest_success_rowid[0] == None else latest_success_rowid[0]
    return rowid

def get_data(nightly_build, con, count):
    tmp_url = con.execute(f"""
        SELECT url, createdAt
        FROM 'gh_run_list_{ nightly_build }'
        WHERE rowid = { count }
    """).fetchall()
    return tmp_url[0] if tmp_url else ''

def create_failures_count_table(nightly_build, con):
    get_run_info(nightly_build, con)
    count = count_consecutive_failures(nightly_build, con)
    if count > 0:
        latest_success_url, createdAt = get_data(nightly_build, con, count)
        curr_run_url = get_data(nightly_build, con, 0)[0]
        with open(COUNT_FILE, 'a') as f:
            f.write(f"{nightly_build},{curr_run_url},{count},{latest_success_url},{createdAt}\n")

def create_report_table(con):
    failure_details = con.execute(f"""
        SELECT
            '[' || name || '](' || url || ')' AS 'Nightly Build',
            count AS 'Consecutive Failures',
            '[' || createdAt || '](' || latest_success_url || ')' AS 'Latest Successful Run'
        FROM 
            read_csv({ COUNT_FILE })
    """).df()
    if failure_details.empty:
        with open(REPORT_FILE, 'w') as f:
            f.write('#### All the nightly-builds had succeeded.\n')
    else:
        with open(REPORT_FILE, 'a') as f:
            f.write(failure_details.to_markdown(index=False) + '\n')

def main():
    con = duckdb.connect('run_info_tables.duckdb')
    with open(COUNT_FILE, "w") as f:
        f.write(f"name,url,count,latest_success_url,createdAt\n")
    for nightly_build in NIGHTLY_BUILDS:
        create_failures_count_table(nightly_build, con)
    create_report_table(con)
    con.close()

if __name__ == "__main__":
    main() 