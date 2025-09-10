import pandas
import argparse

GH_REPO = os.environ.get('GH_REPO', 'duckdb/duckdb')

parser = argparse.ArgumentParser()
parser.add_argument("--new_name")
parser.add_argument("--old_name")
args = parser.parse_args()

new_name = args.new_name
old_name = args.old_name

pattern = f"{new_name}_{old_name}"
regression_outputs=f"regression_*_${{ matrix.versions.new_name }}_${{ matrix.versions.old_name }}.txt"
issue_body_file="issue_body_${{ matrix.versions.new_name }}_${{ matrix.versions.old_name }}.txt"