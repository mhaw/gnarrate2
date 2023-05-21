#configure.py
import json
def load_config(file_name="config.json"):
    with open(file_name, "r") as f:
        config = json.load(f)
    return config