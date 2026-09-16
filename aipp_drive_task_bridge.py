import base64
import json
import os

from aipp_drive_runtime import discover_task_candidates, get_access_token

ENV_NAME = "AIPP_DISCOVERED_TASKS_B64"


def main():
    token = get_access_token()
    folder_id = os.environ.get("GDRIVE_FOLDER_ID", "").strip()
    if not folder_id:
        raise RuntimeError("HALT: GDRIVE_FOLDER_ID is empty")
    candidates = discover_task_candidates(token, folder_id)
    encoded = base64.b64encode(json.dumps(candidates, ensure_ascii=False).encode("utf-8")).decode("ascii")
    github_env = os.environ.get("GITHUB_ENV")
    if not github_env:
        raise RuntimeError("HALT: GITHUB_ENV is unavailable")
    with open(github_env, "a", encoding="utf-8") as handle:
        handle.write(f"{ENV_NAME}={encoded}\n")
    print(f"DRIVE_TASK_BRIDGE_READY candidates={len(candidates)}")


if __name__ == "__main__":
    main()
