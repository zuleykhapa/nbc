import duckdb
import argparse
import pandas as pd
import tabulate
import subprocess
import json

GH_REPO = 'duckdb/duckdb'

def get_value_for_key(key, nightly_build):
    value = duckdb.sql(f"""
        SELECT { key } 
        FROM read_json('{ nightly_build }.json') 
        WHERE status = 'completed' 
        ORDER BY createdAt 
        DESC LIMIT 1;
        """).fetchone()[0]
    return value
    
def get_tables(command, f_output): # saves command execution results into a file
    data = open(f_output, "w")
    return subprocess.run(command, stdout=data)

# count consecutive failures
def count_consecutive_failures(nightly_build, input_file, url):
    duckdb.sql(f"""
        CREATE OR REPLACE TABLE gh_run_list AS (
            SELECT *
            FROM '{ input_file }')
            ORDER BY createdAt DESC
    """)
    latest_success_rowid = duckdb.sql(f"""
        SELECT rowid
        FROM gh_run_list
        WHERE conclusion = 'success'
        ORDER BY createdAt DESC
    """).fetchone()
    count_consecutive_failures = latest_success_rowid[0] if latest_success_rowid else -1 # when -1 then all runs in the json file have conclusion 'failure'

    tmp_url = duckdb.sql(f"""
                SELECT
                    url
                FROM gh_run_list
                WHERE conclusion = 'success'
                ORDER BY createdAt DESC
            """).fetchone()
    url = tmp_url[0] if tmp_url else ''

    if count_consecutive_failures == 0:
        with open("build_report_{}.md".format(nightly_build), 'a') as f:
            f.write(f"\n\n### { nightly_build } nightly-build has succeeded.\n")            
            f.write(f"Latest run: [ Run Link ]({ url })\n")
            return count_consecutive_failures
    # since all runs in the json file have conclusion = 'failure', we count them all 
    # and don't include the link to the last successfull run in a report
    if count_consecutive_failures == -1:
        count_consecutive_failures = duckdb.sql(f"""
            SELECT
                count(*)
            FROM gh_run_list
            WHERE conclusion = 'failure'
        """).fetchone()[0]
    
    total_count = duckdb.sql(f"""
        SELECT
            count(*)
        FROM gh_run_list
    """).fetchone()[0]
    
    with open("build_report_{}.md".format(nightly_build), 'w') as f:
        f.write(f"\n\n### { nightly_build } nightly-build has not succeeded the previous **{ count_consecutive_failures }** times.\n")
        if count_consecutive_failures < total_count:
            f.write(f"Latest successfull run: [ Run Link ]({ url })\n")

    with open("build_report_{}.md".format(nightly_build), 'a') as f:
        f.write(f"\n#### Failure Details\n")
        f.write(duckdb.query(f"""
                    SELECT
                        conclusion,
                        createdAt,
                        url
                    FROM gh_run_list
                    WHERE conclusion = 'failure'
                    ORDER BY createdAt DESC
                    LIMIT { count_consecutive_failures }
            """).to_df().to_markdown(index=False)
        )
    return count_consecutive_failures

def create_build_report(nightly_build, input_file, jobs, artifacts):
    url= duckdb.sql(f"SELECT url FROM '{ input_file }'").fetchone()[0]

    failures_count = count_consecutive_failures(nightly_build, input_file, url)

    if nightly_build not in ('Python', 'Julia'):
        duckdb.sql(f"""
            CREATE OR REPLACE TABLE steps AS (
                SELECT * FROM read_json('{ jobs }')
            )
        """)
        duckdb.sql(f"""
                CREATE OR REPLACE TABLE artifacts AS (
                    SELECT * FROM read_json('{ artifacts }')
                );
            """)
        with open("build_report_{}.md".format(nightly_build), 'a') as f:
            f.write(f"\n#### Workflow Artifacts \n")
            # check if the artifatcs table is not empty
            artifacts_count = duckdb.sql(f"SELECT list_count(artifacts) FROM artifacts;").fetchone()[0]
            if artifacts_count > 0:
                f.write(duckdb.query(f"""
                    SELECT
                        t1.job_name AS "Build (Architecture)",
                        t1.conclusion AS "Conclusion",
                        t2.name AS "Artifact",
                        t2.updated_at AS "Uploaded at"
                    FROM (
                        SELECT
                            job_name,
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
                                FROM steps
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
                            FROM artifacts
                            )
                        ORDER BY expires_at
                        ) as t2;
                    """).to_df().to_markdown(index=False)
                )
            else:
                f.write(duckdb.query(f"""
                    SELECT job_name, conclusion 
                    FROM (
                        SELECT unnest(j['steps']) steps, j['name'] job_name, j['conclusion'] conclusion 
                        FROM (
                            SELECT unnest(jobs) j 
                            FROM steps
                            )
                        ) 
                        WHERE steps['name'] LIKE '%upload-artifact%'
                    """).to_df().to_markdown(index=False)
                )
    else:
        with open("build_report_{}.md".format(nightly_build), 'a') as f:
            f.write(f"**{ nightly_build }** run doesn't upload artifacts.\n\n")
    return { 
        "failures_count": failures_count,
        "url": url
        }
    
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("nightly_build")
    args = parser.parse_args()
    nightly_build = args.nightly_build

    con = duckdb.connect()
    gh_run_list_file = f"{ nightly_build }.json"
    runs_command = [
            "gh", "run", "list",
            "--repo", GH_REPO,
            "--event", "repository_dispatch",
            "--workflow", nightly_build,
            "--json", "status,conclusion,url,name,createdAt,databaseId,headSha"
        ]
    get_tables(runs_command, gh_run_list_file)
    run_id = get_value_for_key('databaseId', nightly_build)
    jobs_file = f"{ nightly_build }_jobs.json"
    jobs_command = [
            "gh", "run", "view",
            "--repo", GH_REPO,
            f"{ run_id }",
            "--json", "jobs"
        ]
    get_tables(jobs_command, jobs_file)
    artifacts_file = f"{ nightly_build }_artifacts.json"
    artifacts_command = [
            "gh", "api",
            f"repos/{ GH_REPO }/actions/runs/{ run_id }/artifacts"
        ]
    get_tables(artifacts_command, artifacts_file)
    output_data = create_build_report(nightly_build, gh_run_list_file, jobs_file, artifacts_file)
    con.close()
    output_data["run_id"] = run_id
    print(json.dumps(output_data))
    
if __name__ == "__main__":
    main()