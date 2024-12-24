import requests
import argparse
import json

REPO_OWNER = 'zuleykhapa'
REPO_NAME = 'nbc'
WORKFLOW_FILE = '.github/workflows/Test.yml'
REF = 'move-to-python'

url = f"https://api.github.com/repos/{ REPO_OWNER }/{ REPO_NAME }/actions/workflows/{ WORKFLOW_FILE }/dispatches"

parser = argparse.ArgumentParser()
parser.add_argument("GH_TOKEN")
parser.add_argument("--inputs")
args = parser.parse_args()
GH_TOKEN = args.GH_TOKEN
loaded_data = args.inputs

with open(loaded_data, "r") as file:
    inputs = json.load(file)

headers = {
    "Authorisation": f"Bearer { GITHUB_TOKEN }",
    "Accept": "application/vnd.github.v3_json",
}

for input in inputs:
    if input["failures_count"] == 0:
        nightly_build = info.get("nightly_build")
        platform = info.get("platform")
        architectures = info.get("architectures")
        runs_on = info.get("runs_on")
        run_id = info.get("run_id")

    payload = {
        "ref": REF,
        "inputs": {
            "nightly_build": nightly_build,
            "platform": platform,
            "architectures": ",".join(architectures) if isinstance(architectures, list) else architectures,
            "runs_on": runs_on,
            "run_id": run_id,
        },
    }

    response = requests.post(url, headers=headers, json=payload)

    if response.status_code == 204:
        print("Workflow triggered successfully!")
    else:
        print(f"Failed to trigger workflow: { response.status_code }")
        print(response.json())