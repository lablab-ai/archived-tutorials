import base64
import json
import os
import sys
import time
from uuid import uuid4

import requests
from actions_toolkit import core


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


class PlagiarismChecker:
    def __init__(self, access_token, plagiarism_update_url):
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        self.base_url = "https://api.copyleaks.com/v3/scans/submit/file"
        self.plagiarism_update_url = plagiarism_update_url

    def check_plagiarism(self, file_path, scan_id):
        with open(file_path, "r") as f:
            content = f.read()

        data = {
            "base64": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
            "filename": f"{scan_id}.txt",
            "properties": {
                # "sandbox": True,
                "webhooks": {"status": f"{self.plagiarism_update_url}/{scan_id}"},
                # "aiGeneratedText": {"detect": True},
            },
        }

        response = requests.put(
            f"{self.base_url}/{scan_id}",
            headers=self.headers,
            data=json.dumps(data),
        )

        if response.status_code != 201:  # Status code: 201 - Created
            print(
                f"Error checking plagiarism for {file_path}: {response.text}",
                flush=True,
            )

            return False

        return True


if __name__ == "__main__":
    api_key = os.getenv("COPYLEAKS_API_KEY")
    email = os.getenv("COPYLEAKS_EMAIL")
    internal_api_key = os.getenv("INTERNAL_API_KEY")
    plagiarism_update_url = os.getenv("PLAGIARISM_UPDATE_URL")

    THRESHOLD = os.getenv("PLAGIARISM_THRESHOLD") or 65
    THRESHOLD = float(THRESHOLD)

    # log to copyleaks
    access_token = log_to_copyleaks(email, api_key)

    # init plagiarism checker
    plagiarism_checker = PlagiarismChecker(
        access_token=access_token, plagiarism_update_url=plagiarism_update_url
    )

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

    # pass each file to copyleaks
    for scan_id, file_path in id_file_map.items():
        plagiarism_checker.check_plagiarism(file_path, scan_id)

    # create list of scan ids with statuses
    scan_status = {
        scan_id: {
            "delivered": False,  # delivered from copyleaks to db
            "status": False,  # status of scan from copyleaks - if score is in range
        }
        for scan_id in id_file_map.keys()
    }

    # listen for results from webhooks (each 5s, max 12min)
    t_start = time.time()
    while True:
        # check time
        if time.time() - t_start > 8 * 60:  # 8 min * 60 sec
            print("Timeout exceeded", flush=True)
            break

        # check if all scans are delivered
        if all([scan_status[scan_id]["delivered"] for scan_id in scan_status.keys()]):
            break

        # check if all scans are completed
        if all([scan_status[scan_id]["status"] for scan_id in scan_status.keys()]):
            # passed test
            print("No plagiarism detected.", flush=True)
            sys.exit(0)

        for scan_id, status in scan_status.items():
            # check if scan is delivered
            if status["delivered"]:
                continue

            # check if scan is completed
            result = requests.get(
                f"https://api.lablab.ai/plagiarism/status/{scan_id}",
                headers={"Authorization": f"Bearer {internal_api_key}"},
            )

            # if status is not 200, not delivered, continue
            if result.status_code != 200:
                continue

            # extract status
            # { scanId: string, status: "Completed" | "Error", score: float [0, 1]}
            result = result.json()
            status = result["status"]

            # if status is not completed, set to delivered and status to false
            if status != "Completed":
                scan_status[scan_id]["delivered"] = True
                scan_status[scan_id]["status"] = False
                continue

            # if status is completed, check THRESHOLD
            score = result["score"]

            # if score is in range, set to delivered and status to true (NO PLAGIARISM)
            if score <= THRESHOLD:
                scan_status[scan_id]["delivered"] = True
                scan_status[scan_id]["status"] = True
                continue

            # if score is not in range, set to delivered and status to false
            scan_status[scan_id]["delivered"] = True
            scan_status[scan_id]["status"] = False

        # sleep for 5s
        time.sleep(5)

    # list of flagged files in github pr (where plagiarism was detected or not delivered)
    flagged_files = [
        id_file_map[scan_id]
        for scan_id, status in scan_status.items()
        if not status["delivered"] or not status["status"]
    ]

    if flagged_files:
        error_msg = "Plagiarism check failed. Please review the flagged files.\n- "

        # print flagged files
        error_msg += "\n- ".join(flagged_files)

        core.set_failed(error_msg)

        sys.exit(1)

    sys.exit(0)
