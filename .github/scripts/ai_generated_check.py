import json
import os
import sys
from uuid import uuid4

import requests
from actions_toolkit import core

# Classes defined by Copyleaks
HUMAN_WRITTEN = 1
AI_GENERATED = 2


def log_to_copyleaks(email, api_key):
    login_result = requests.post(
        "https://id.copyleaks.com/v3/account/login/api",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"email": email, "key": api_key}),
    )

    # if status is not 200, exit
    if login_result.status_code != 200:
        core.set_failed(
            "Cannot access Plagiarism Checker API. Please contact with the administrator."
        )

        sys.exit(1)

    # extract access_token
    login_result = login_result.json()
    access_token = login_result["access_token"]

    return access_token


class AIGeneratedContentCheck:
    def __init__(self, access_token):
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        self.base_url = "https://api.copyleaks.com//v2/writer-detector/{scan_id}/check"

    def check_ai_generated_content(self, file_path, scan_id):
        with open(file_path, "r") as f:
            content = f.read()

        data = {
            "text": content,
        }

        response = requests.post(
            self.base_url.format(scan_id=scan_id),
            headers=self.headers,
            data=json.dumps(data),
        )

        # if error - AI Generated Content Check failed
        if response.status_code != 200:
            return False

        result = response.json()
        result = result["results"]

        # check if for each result .classification is 1 (Human)
        return all(r["classification"] == HUMAN_WRITTEN for r in result)


if __name__ == "__main__":
    api_key = os.getenv("COPYLEAKS_API_KEY")
    email = os.getenv("COPYLEAKS_EMAIL")

    access_token = log_to_copyleaks(email, api_key)

    ai_generated_content_checker = AIGeneratedContentCheck(access_token=access_token)

    # extract changed .mdx files
    changed_files = os.getenv("CHANGED_FILES")
    changed_files = json.loads(changed_files)

    removed_files = os.getenv("REMOVED_FILES")
    removed_files = json.loads(removed_files)

    changed_files = [f for f in changed_files if f not in removed_files]

    # filter out only markdown files
    md_files = [f for f in changed_files if f.endswith(".mdx") and os.path.exists(f)]

    # if no markdown files, exit
    if not md_files:
        print("No markdown files found.", flush=True)
        sys.exit(0)

    # generate unique id for each file [uuid or cuid], should be in {[id]: [file_path]}
    id_file_map = {str(uuid4()): f for f in md_files}

    # pass each file to copyleaks and save the result
    results = {}
    for scan_id, file_path in id_file_map.items():
        ai_content_result = ai_generated_content_checker.check_ai_generated_content(
            file_path=file_path, scan_id=scan_id
        )

        results[scan_id] = ai_content_result

    # if all are human written exit
    if all(results.values()):
        print("No plagiarism detected.", flush=True)
        sys.exit(0)

    # if any is not human written - lsit all files that are ai generated and exit
    ai_generated_files = [
        id_file_map[scan_id] for scan_id, result in results.items() if not result
    ]

    error_msg = "AI Generated Content detected in the following files:\n- "

    error_msg += "\n- ".join(ai_generated_files)

    core.set_failed(error_msg)

    sys.exit(1)
