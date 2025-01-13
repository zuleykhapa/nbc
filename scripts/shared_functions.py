import subprocess
import datetime
import duckdb

GH_REPO = 'duckdb/duckdb'
CURR_DATE = datetime.datetime.now().strftime('%Y-%m-%d')


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