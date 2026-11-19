import base64
import json
import os

from aipp_drive_runtime import (
    discover_task_candidates,
    get_access_token,
    publish_task_candidates_to_runtime_env,
)


def main():
    token = get_access_token()
    folder_id = os.environ.get("GDRIVE_FOLDER_ID", "").strip()
    if not folder_id:
        raise RuntimeError("HALT: GDRIVE_FOLDER_ID is empty")
    candidates = discover_task_candidates(token, folder_id)
    publish_task_candidates_to_runtime_env(candidates)
    print(f"DRIVE_TASK_BRIDGE_READY candidates={len(candidates)}")


if __name__ == "__main__":
    main()
