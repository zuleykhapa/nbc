import threading
import argparse
import json

class ErrorContainer:
    def __init__(self):
        self._lock = threading.Lock()
        self._errors = []

    def append(self, item):
        with self._lock:
            self._errors.append(item)

    def get_errors(self):
        with self._lock:
            return list(self._errors)

    def __len__(self):
        with self._lock:
            return len(self._errors)


error_container = ErrorContainer()
new_data = {"test": "test/sql/copy/csv/test_skip.test_slow", "return_code": 1, "stdout": "Query unexpectedly failed (test/sql/copy/csv/test_skip.test_slow:193)", "stderr": "FATAL Error: Failed: database has been invalidated because of a previous fatal error. The database must be restarted prior to being used again."}
error_container.append(new_data)

def main():
    error_list = error_container.get_errors()
    with open("failures_summary.json", 'w') as f:
        json.dump(error_list, f, indent=2)
    print(
    '''\n\n====================================================
================  FAILURES SUMMARY  ================
====================================================\n
'''
    )
    for i, error in enumerate(error_container.get_errors(), start=1):
        print(f"\n{i}:", error["test"], "\n")
        print(error["stderr"])

        subprocess.run(f'echo "::warning::{i}: {error["test"]}"', shell=True)

        # print(f'echo "::warning::{i}: {error["test"]}"')
        # print(f'echo "::warning::{error["stderr"]}"')
if __name__ == "__main__":
    main()