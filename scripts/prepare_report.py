import duckdb
import argparse
import pandas
import tabulate
import sys

parser = argparse.ArgumentParser()
parser.add_argument("input_csv")
parser.add_argument("--platform")
parser.add_argument("--url")
args = parser.parse_args()
if not args:
    print("SET input_csv argument")

input_csv = args.input_csv
platform = args.platform
url = args.url

# def prepare_report(input_csv, platform, url):
def prepare_report():
    with open("res_{}.md".format(platform), 'w') as f:
        f.write(f"\n\n#### Extensions failed to INSTALL\n")
        f.write(duckdb.query(f"""
                    SELECT architecture, version, extension
                    FROM read_csv("{ input_csv }")
                    WHERE failed_statement = 'INSTALL' 
                    ORDER BY nightly_build, architecture, runs_on, version, extension, failed_statement
                    """).to_df().to_markdown(index=False)
        )
        f.write(f"\n\n#### Extensions failed to LOAD\n")
        f.write(duckdb.query(f"""
                    SELECT architecture, version, extension
                    FROM read_csv("{ input_csv }")
                    WHERE failed_statement = 'LOAD' 
                    ORDER BY nightly_build, architecture, runs_on, version, extension, failed_statement
                    """).to_df().to_markdown(index=False)
        )