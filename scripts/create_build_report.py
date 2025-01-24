'''
The scripts/create_build_report.py script job is to create a final report file "{ CURR_DATE }_REPORT_FILE.md".
    For each name of nightly-build it writes the latest run's conclusion, in case of failure,
    followed with a list of last 7 failed runs.
    Then it adds 'artifacts_per_jobs_{ nightly_build }' table contents.

Can be tested locally running 'python scripts/create_tables_and_inputs.py' with preconditions:
    1. Run 'scripts/create_build_report.py'.
    2. mkdir tables && mv run_info_tables.duckdb tables
'''

import duckdb
import datetime
import pandas as pd
import tabulate
import subprocess
import json
import os
import glob
import re
from collections import defaultdict
from shared_functions import fetch_data
from shared_functions import list_all_runs
from shared_functions import count_consecutive_failures

GH_REPO = os.environ.get('GH_REPO', 'duckdb/duckdb')
CURR_DATE = os.environ.get('CURR_DATE', datetime.datetime.now().strftime('%Y-%m-%d'))
REPORT_FILE = f"{ CURR_DATE }_REPORT_FILE.md"
HAS_NO_ARTIFACTS = ('Python', 'Julia', 'Swift', 'SwiftRelease')

def create_build_report(nightly_build, con, build_info, url):
    # failures_count = count_consecutive_failures(nightly_build, con)
    failures_count = 0

    with open(REPORT_FILE, 'a') as f:
        if failures_count == 0:
            f.write(f"\n## { nightly_build }\n")            
            f.write(f"\n\n### { nightly_build } nightly-build has succeeded.\n")            
            f.write(f"Latest run: [ Run Link ]({ url })\n")

        else:
            failures_count = -1 # means all runs in the json file have conclusion = 'failure' 
            # so we need to update its value.
            # We count all runs and do not add a last successful run link to the report
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
                """).fetchone()
                latest_success_url = tmp_url[0] if tmp_url else ''
                f.write(f"Latest successful run: [ Run Link ]({ latest_success_url })\n")

            f.write(f"\n#### Failure Details\n")
            failure_details = con.execute(f"""
                SELECT
                    conclusion as "Conclusion",
                    createdAt as "Created at",
                    url as "URL"
                FROM 'gh_run_list_{ nightly_build }'
                WHERE conclusion = 'failure'
                ORDER BY createdAt DESC
                LIMIT 7
            """).df()
            f.write(failure_details.to_markdown(index=False) + "\n")
            
        # check if the artifatcs table is not empty
        # if nightly_build not in HAS_NO_ARTIFACTS:
        #     f.write(f"\n#### Workflow Artifacts\n")
        #     artifacts_per_job = con.execute(f"""
        #         SELECT * FROM 'artifacts_per_jobs_{ nightly_build }';
        #         """).df()
        #     f.write(artifacts_per_job.to_markdown(index=False) + "\n")
        # else:
        #     f.write(f"**{ nightly_build }** run doesn't upload artifacts.\n\n")
        
        # add extensions
        file_name_pattern = f"failed_ext/ext_{ nightly_build }_*/list_failed_ext_{ nightly_build }_*.csv"
        matching_files = glob.glob(file_name_pattern)
        if matching_files:
            f.write(f"\n#### List of failed extensions\n")
            failed_extensions = con.execute(f"""
                SELECT * FROM read_csv('{ file_name_pattern }')
            """).df()
            f.write(failed_extensions.to_markdown(index=False) + "\n")
        else:
            if failures_count == 0:
                f.write(f"\n#### All extensions were successfully installed and loaded.\n")

    build_info["failures_count"] = failures_count
    build_info["url"] = url
    
def main():
    db_name = 'tables/run_info_tables.duckdb'
    con = duckdb.connect(db_name)
    # list all nightly-build runs on current date to get all nightly-build names
    result = list_all_runs(con)
    nightly_builds = [row[0] for row in result]
    # create complete report
    for nightly_build in nightly_builds:
        build_info = {}
        # url = con.execute(f"""
        #     SELECT url FROM 'gh_run_list_{ nightly_build }' LIMIT 1
        #     """).fetchone()[0]
        url = ""
        create_build_report(nightly_build, con, build_info, url)    
    con.close()
    
    
if __name__ == "__main__":
    main()