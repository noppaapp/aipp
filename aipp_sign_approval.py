#!/usr/bin/env python3
"""Offline authority signer; the private key never enters the AIPP runtime."""

import argparse
import base64
import os
import sys
from datetime import datetime, timezone

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aipp_authority import DECISION_APPROVED, DECISION_COMPLETED, signing_message


def _raw(key_obj, public):
    enc = serialization.Encoding.Raw
    if public:
        return key_obj.public_bytes(enc, serialization.PublicFormat.Raw)
    return key_obj.private_bytes(enc, serialization.PrivateFormat.Raw, serialization.NoEncryption())


def keygen():
    key = Ed25519PrivateKey.generate()
    print("AIPP_APPROVER_PRIVATE_KEY=" + base64.b64encode(_raw(key, False)).decode())
    print("AIPP_AUTHORITY_PUBKEY=" + base64.b64encode(_raw(key.public_key(), True)).decode())


def sign(proposal_id, task_id, decision, approver, timestamp=None):
    encoded = os.environ.get("AIPP_APPROVER_PRIVATE_KEY", "").strip()
    if not encoded:
        raise SystemExit("AIPP_APPROVER_PRIVATE_KEY is not set")
    key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(encoded))
    timestamp = timestamp or datetime.now(timezone.utc).isoformat()
    sig = base64.b64encode(key.sign(signing_message(proposal_id, task_id, decision, timestamp, approver))).decode()
    return f"| {proposal_id} | {task_id} | {decision} | {timestamp} | {approver} | {sig} |"


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("keygen")
    s = sub.add_parser("sign")
    s.add_argument("--proposal-id", required=True)
    s.add_argument("--task-id", required=True)
    s.add_argument("--decision", choices=[DECISION_APPROVED, DECISION_COMPLETED], default=DECISION_APPROVED)
    s.add_argument("--approver", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "keygen":
        keygen()
    else:
        print(sign(args.proposal_id, args.task_id, args.decision, args.approver))


if __name__ == "__main__":
    sys.exit(main())
