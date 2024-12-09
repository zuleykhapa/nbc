import duckdb
import argparse

# Verifying version
parser = argparse.ArgumentParser()
parser.add_argument("input_file")
parser.add_argument("--jobs")
parser.add_argument("--artifacts")
parser.add_argument("--nightly_build")
args = parser.parse_args()

if not args:
    print("Usage: python scripts/count_consecutive_failures.py <input_file>.json --jobs <nightly-build>.json --artifacts <nightly-build_artifacts>.json \
            --nightly_build <nightly-build>")

input_file = args.input_file
nightly_build = args.nightly_build
jobs = args.jobs
artifacts = args.artifacts

# count consecutive failures
all = duckdb.sql(f"SELECT * FROM read_json('{ input_file }') WHERE status = 'completed'")
rows = all.fetchall()
conclusions = [row[0] for row in rows]
failures=0
for c in conclusions:
    if c == 'failure':
        failures+=1
    elif c == '':
        continue
    else:
        break

url= duckdb.sql(f"""SELECT url FROM '{ input_file }'""").fetchone()[0]
def create_run_status():
    if failures > 0:
        failures_list = "failures_list.md"
        duckdb.sql(f"""
                    COPY (
                        SELECT conclusion, createdAt, url
                        FROM read_json('{ input_file }') 
                        WHERE conclusion='failure'
                        LIMIT '{ failures }'
                    )  
                    TO '{ failures_list }' (HEADER 0, QUOTE '', SEPARATOR '|');
                    """)
        with open("run_status_{}.md".format(nightly_build), 'w') as f:
            f.write(f"\nThe **'{ nightly_build }'** nightly-build has not succeeded the previous '{ failures }' times.\n")
            f.write(f"#### Failure Details\n\n")
            f.write(f"| Conclusion | Started At | Run URL |\n")
            f.write(f"|------------|------------|---------|\n")
            with open(failures_list, 'r') as failures_file:
                f.write(failures_file.read())
    else:
        with open("run_status_{}.md".format(nightly_build), 'a') as f:
            f.write(f"\nThe **'{ nightly_build }'** nightly-build has succeeded.\n")
    
    with open("run_status_{}.md".format(nightly_build), 'a') as f:
        f.write(f"\nSee the latest run: [ Run Link ]({ url })\n")

    if nightly_build != 'Python':
        with open("run_status_{}.md".format(nightly_build), 'a') as f:
            f.write(f"#### Run Details\n\n")
            f.write(f"| Build (Architecture) | Conclusion | Artifact |\n")
            f.write(f"|----------------------|------------|----------|\n")
            run_status = "run_status.md"
            duckdb.sql(f"""
                CREATE OR REPLACE TABLE steps AS (
                    SELECT * FROM read_json('{ jobs }')
                );
            """)
            duckdb.sql(f"""
                    CREATE OR REPLACE TABLE artifacts AS (
                        SELECT * FROM read_json('{ artifacts }')
                    );
                """)
            # check if the artifatcs table is not empty
            artifacts_count = duckdb.sql(f"SELECT list_count(artifacts) FROM artifacts;").fetchone()[0]
            if artifacts_count > 0:
                duckdb.sql(f"""
                    COPY (
                        SELECT job_name, conclusion, artifact_name 
                        FROM (
                            SELECT a['name'] artifact_name, a['created_at'] created_at
                            FROM (
                                SELECT unnest(artifacts) a 
                                FROM artifacts)) tmp1 
                                ASOF JOIN (
                                    SELECT * 
                                    FROM (
                                        SELECT unnest(j['steps']) step, j['name'] job_name, j['completedAt'] completedAt, j['conclusion'] conclusion 
                                        FROM (
                                            SELECT unnest(jobs) j 
                                            FROM steps)) 
                                            WHERE step['name'] LIKE '%upload-artifact%') tmp2 
                                            ON tmp1.created_at >= tmp2.step['completedAt']
                    )  
                    TO '{ run_status }' (HEADER 0, QUOTE '', SEPARATOR '|');
                """)
            else:
                duckdb.sql(f"""
                    COPY (
                        SELECT job_name, conclusion 
                        FROM (
                            SELECT unnest(j['steps']) steps, j['name'] job_name, j['conclusion'] conclusion 
                            FROM (
                                SELECT unnest(jobs) j 
                                FROM steps
                                )
                            ) 
                            WHERE steps['name'] LIKE '%upload-artifact%'
                        )
                    TO '{ run_status }' (HEADER 0, QUOTE '', SEPARATOR '|');
                """)
            with open(run_status, 'r') as run_status_file:
                    f.write(run_status_file.read())
    else:
        with open("run_status_{}.md".format(nightly_build), 'a') as f:
            f.write(f"**{ nightly_build }** run doesn't upload artifacts.\n\n")
    
def main():
    create_run_status()
    
if __name__ == "__main__":
    main()