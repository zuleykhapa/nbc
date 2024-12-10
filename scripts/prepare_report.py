import duckdb
import argparse
import pandas
import tabulate
import sys

parser = argparse.ArgumentParser()
parser.add_argument("file_name")
parser.add_argument("--platform")
parser.add_argument("--url")
args = parser.parse_args()
if not args:
    print("SET file_name argument")

file_name = args.file_name
platform = args.platform
url = args.url
with open("res_{}.md".format(platform), 'w') as f:
    f.write(f"\n#### Extensions failed to INSTALL or to LOAD: [ Run Link ](https:{ url })\n")
    f.write(duckdb.query(f"""
                SELECT * 
                FROM read_csv("{ file_name }")
                    ORDER BY nightly_build, architecture, runs_on, version, extension, failed_statement
                """).to_df().to_markdown(index=False)
    )