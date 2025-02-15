import subprocess
import duckdb
import datetime
import os

GH_REPO = os.environ.get('GH_REPO', 'duckdb/duckdb')
CURR_DATE = os.environ.get('CURR_DATE', datetime.datetime.now().strftime('%Y-%m-%d'))

# save command execution results into an f_output file
def fetch_data(command, f_output): 
    data = open(f_output, "w")
    try:
        subprocess.run(command, stdout=data, stderr=True, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Command failed with error: {e.stderr}")

# create a json file with the list all nightly-build runs for current date
def list_all_runs(con, build_job):
    gh_run_list_file = f"{ build_job }.json"
    gh_run_list_command = [
        "gh", "run", "list",
        "--repo", GH_REPO,
        "--workflow", f"{ build_job }",
        "--created", CURR_DATE,
        "--json", "status,conclusion,url,name,createdAt,databaseId,headSha"
    ]
    fetch_data(gh_run_list_command, gh_run_list_file)
    result = duckdb.sql(f"SELECT name FROM read_json('{ gh_run_list_file }')").fetchall()
    return result

# return a number of consecutive failures
def count_consecutive_failures(build_job, con):
    latest_success_rowid = con.execute(f"""
        SELECT rowid
        FROM 'gh_run_list_{ build_job }'
        WHERE conclusion = 'success'
        ORDER BY createdAt DESC
    """).fetchone()
    consecutive_failures = latest_success_rowid[0] if latest_success_rowid else -1 # when -1 then all runs in the json file have conclusion 'failure'
    return consecutive_failures


def sha_matching(short_sha, full_sha, build_job, architecture):
    if not full_sha.startswith(short_sha):
        print(f"""
        Version of { build_job } tested binary doesn't match to the version that triggered the build.
        - Version triggered the build: { full_sha }
        - Downloaded build version: { short_sha }
        """)
        non_matching_sha_file_name = "non_matching_sha_{}_{}.txt".format(build_job, architecture.replace("/", "-"))
        with open(non_matching_sha_file_name, 'a') as f:
            f.write(f"""
            Version of { build_job } { architecture } tested binary doesn't match to the version that triggered the build.
            - Version triggered the build: { full_sha }
            - Downloaded build version: { short_sha }
            """)
        return False
    print(f"""
    Versions of { build_job } build match:
    - Version triggered the build: { full_sha }
    - Downloaded build version: { short_sha }
    """)
    return True