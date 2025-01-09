import os
import json

input_files = [f for f in os.listdir() if f.startswith('input') and f.endswith('.json')]
matrix = [{"input_file": file} for file in input_files]
print(json.dumps(matrix))