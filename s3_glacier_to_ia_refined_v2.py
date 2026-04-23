#!/usr/bin/env python3
import argparse
import concurrent.futures as cf
import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

ARCHIVE_CLASSES = {"GLACIER", "DEEP_ARCHIVE"}
ACTIVE_ARCHIVE_CLASS = "GLACIER_IR"
TARGET_STORAGE_CLASS = "STANDARD_IA"
MAX_S3_KEY_BYTES = 1024


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def eprint(msg: str) -> None:
    print(msg, file=sys.stderr)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Bulk restore archived S3 objects and copy them to STANDARD_IA. "
            "If --source-prefix is omitted, the entire bucket is processed."
        )
    )
    p.add_argument("--bucket", required=True, help="S3 bucket name")
    p.add_argument("--source-prefix", help="Optional source prefix, for example archived/. Omit to process the whole bucket")
    p.add_argument("--dest-prefix", help="Optional destination prefix. Defaults to same as source for prefix mode; ignored for whole-bucket in-place copy")
    p.add_argument("--days", type=int, default=7, help="Restore retention in days for Glacier/Deep Archive")
    p.add_argument("--tier", choices=["Bulk", "Standard", "Expedited"], default="Standard", help="Restore tier")
    p.add_argument("--phase", choices=["all", "restore", "copy"], default="all", help="Run restore only, copy only, or both")
    p.add_argument("--wait", action="store_true", help="Wait for restore completion before copy")
    p.add_argument("--poll-seconds", type=int, default=300, help="Polling interval while waiting for restore")
    p.add_argument("--max-workers", type=int, default=16, help="Parallel worker count")
    p.add_argument("--include-non-archived", action="store_true", help="Also copy non-archived objects to STANDARD_IA")
    p.add_argument("--profile", help="AWS profile name")
    p.add_argument("--region", help="AWS region")
    p.add_argument("--dry-run", action="store_true", help="Print actions without making changes")
    p.add_argument("--output-dir", default=".", help="Directory for CSV and JSON logs")
    return p.parse_args()


def normalize_prefix(prefix: Optional[str]) -> Optional[str]:
    if prefix is None:
        return None
    prefix = prefix.strip()
    if prefix == "":
        return None
    return prefix if prefix.endswith("/") else prefix + "/"


def s3_client(args: argparse.Namespace):
    session_kwargs = {}
    if args.profile:
        session_kwargs["profile_name"] = args.profile
    if args.region:
        session_kwargs["region_name"] = args.region
    session = boto3.Session(**session_kwargs)
    return session.client("s3", config=Config(retries={"max_attempts": 10, "mode": "standard"}))


def utf8_len(s: str) -> int:
    return len(s.encode("utf-8"))


def list_keys(client, bucket: str, prefix: Optional[str] = None) -> Iterable[str]:
    paginator = client.get_paginator("list_objects_v2")
    kwargs = {"Bucket": bucket}
    if prefix:
        kwargs["Prefix"] = prefix
    for page in paginator.paginate(**kwargs):
        for obj in page.get("Contents", []):
            yield obj["Key"]


def head_meta(client, bucket: str, key: str) -> Dict:
    return client.head_object(Bucket=bucket, Key=key)


def storage_class(meta: Dict) -> str:
    return meta.get("StorageClass", "STANDARD")


def restore_header(meta: Dict) -> str:
    return meta.get("Restore", "") or ""


def restore_done(meta: Dict) -> bool:
    return 'ongoing-request="false"' in restore_header(meta)


def is_archived(sc: str) -> bool:
    return sc in ARCHIVE_CLASSES


def can_copy_now(sc: str, meta: Dict) -> bool:
    if sc == ACTIVE_ARCHIVE_CLASS:
        return True
    if sc in ARCHIVE_CLASSES:
        return restore_done(meta)
    return True


def map_destination_key(source_key: str, source_prefix: Optional[str], dest_prefix: Optional[str]) -> str:
    if not source_prefix:
        return source_key
    if not dest_prefix or dest_prefix == source_prefix:
        return source_key
    if not source_key.startswith(source_prefix):
        raise ValueError(f"Source key does not start with prefix: {source_key}")
    return dest_prefix + source_key[len(source_prefix):]


def classify_object(client, bucket: str, key: str) -> Dict:
    row = {
        "timestamp": now_utc(),
        "bucket": bucket,
        "key": key,
        "key_bytes": utf8_len(key),
        "storage_class": "",
        "restore": "",
        "eligible_for_restore": False,
        "eligible_for_copy_now": False,
        "status": "",
        "reason": "",
    }
    if row["key_bytes"] >= MAX_S3_KEY_BYTES:
        row["status"] = "skipped"
        row["reason"] = f"key_too_long_{row['key_bytes']}_bytes"
        return row
    try:
        meta = head_meta(client, bucket, key)
        sc = storage_class(meta)
        row["storage_class"] = sc
        row["restore"] = restore_header(meta)
        row["eligible_for_restore"] = is_archived(sc)
        row["eligible_for_copy_now"] = can_copy_now(sc, meta)
        row["status"] = "classified"
        if is_archived(sc) and not can_copy_now(sc, meta):
            row["reason"] = "archived_not_restored"
        elif is_archived(sc) and can_copy_now(sc, meta):
            row["reason"] = "archived_restored"
        elif sc == ACTIVE_ARCHIVE_CLASS:
            row["reason"] = "glacier_instant_retrieval"
        else:
            row["reason"] = "active_class"
        return row
    except ClientError as e:
        row["status"] = "error"
        row["reason"] = e.response.get("Error", {}).get("Code", "Unknown")
        return row


def request_restore(client, bucket: str, key: str, days: int, tier: str, dry_run: bool) -> Dict:
    row = {"timestamp": now_utc(), "bucket": bucket, "key": key, "action": "restore", "status": "", "message": ""}
    if dry_run:
        row["status"] = "dry_run"
        return row
    try:
        client.restore_object(
            Bucket=bucket,
            Key=key,
            RestoreRequest={"Days": days, "GlacierJobParameters": {"Tier": tier}},
        )
        row["status"] = "restore_requested"
        return row
    except ClientError as e:
        row["status"] = e.response.get("Error", {}).get("Code", "Unknown")
        row["message"] = str(e)
        return row


def wait_for_restore(client, bucket: str, key: str, poll_seconds: int) -> Dict:
    while True:
        try:
            meta = head_meta(client, bucket, key)
        except ClientError as e:
            return {
                "timestamp": now_utc(),
                "bucket": bucket,
                "key": key,
                "action": "wait",
                "status": e.response.get("Error", {}).get("Code", "Unknown"),
                "message": str(e),
            }
        sc = storage_class(meta)
        if sc == ACTIVE_ARCHIVE_CLASS or restore_done(meta):
            return {
                "timestamp": now_utc(),
                "bucket": bucket,
                "key": key,
                "action": "wait",
                "status": "restored",
                "message": restore_header(meta),
            }
        time.sleep(poll_seconds)


def copy_object_to_ia(client, bucket: str, source_key: str, dest_key: str, dry_run: bool) -> Dict:
    row = {
        "timestamp": now_utc(),
        "bucket": bucket,
        "source_key": source_key,
        "dest_key": dest_key,
        "action": "copy",
        "status": "",
        "message": "",
    }
    if dry_run:
        row["status"] = "dry_run"
        return row
    try:
        client.copy_object(
            Bucket=bucket,
            Key=dest_key,
            CopySource={"Bucket": bucket, "Key": source_key},
            StorageClass=TARGET_STORAGE_CLASS,
            MetadataDirective="COPY",
        )
        row["status"] = "copied"
        return row
    except ClientError as e:
        row["status"] = e.response.get("Error", {}).get("Code", "Unknown")
        row["message"] = str(e)
        return row


def write_csv(path: Path, rows: List[Dict]) -> None:
    if not rows:
        rows = [{"message": "no_rows"}]
    fields = sorted({k for r in rows for k in r.keys()})
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    args = parse_args()
    args.source_prefix = normalize_prefix(args.source_prefix)
    args.dest_prefix = normalize_prefix(args.dest_prefix)

    if args.source_prefix is None and args.dest_prefix:
        eprint("ERROR: --dest-prefix cannot be used when --source-prefix is omitted. Whole-bucket mode uses in-place copy only.")
        return 2

    if args.source_prefix and args.dest_prefix is None:
        args.dest_prefix = args.source_prefix

    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    client = s3_client(args)

    scope = f"s3://{args.bucket}/{args.source_prefix}" if args.source_prefix else f"entire bucket s3://{args.bucket}"
    eprint(f"[{now_utc()}] Listing objects under {scope}")
    keys = list(list_keys(client, args.bucket, args.source_prefix))
    if not keys:
        summary = {
            "timestamp": now_utc(),
            "bucket": args.bucket,
            "source_prefix": args.source_prefix,
            "dest_prefix": args.dest_prefix,
            "message": "No objects found",
        }
        write_json(outdir / "summary.json", summary)
        print(json.dumps(summary))
        return 0

    eprint(f"[{now_utc()}] Found {len(keys)} objects. Classifying...")
    classified: List[Dict] = []
    with cf.ThreadPoolExecutor(max_workers=args.max_workers) as ex:
        futures = [ex.submit(classify_object, client, args.bucket, key) for key in keys]
        for fut in cf.as_completed(futures):
            classified.append(fut.result())

    write_csv(outdir / "classification.csv", classified)

    too_long = [r for r in classified if r.get("reason", "").startswith("key_too_long_")]
    archived = [r for r in classified if r.get("eligible_for_restore") is True and r.get("status") == "classified"]
    copy_now = []
    for r in classified:
        if r.get("status") != "classified":
            continue
        sc = r.get("storage_class", "")
        if r.get("eligible_for_copy_now"):
            if sc in ARCHIVE_CLASSES or sc == ACTIVE_ARCHIVE_CLASS or args.include_non_archived:
                copy_now.append(r)

    restore_results: List[Dict] = []
    waited_results: List[Dict] = []
    copy_results: List[Dict] = []

    if args.phase in {"all", "restore"}:
        restore_targets = [r for r in archived if not r.get("eligible_for_copy_now")]
        if restore_targets:
            eprint(f"[{now_utc()}] Initiating restore for {len(restore_targets)} objects...")
            with cf.ThreadPoolExecutor(max_workers=args.max_workers) as ex:
                futures = [
                    ex.submit(request_restore, client, args.bucket, r["key"], args.days, args.tier, args.dry_run)
                    for r in restore_targets
                ]
                for fut in cf.as_completed(futures):
                    restore_results.append(fut.result())
            write_csv(outdir / "restore_results.csv", restore_results)

        if args.wait and restore_targets:
            eprint(f"[{now_utc()}] Waiting for restore completion for {len(restore_targets)} objects...")
            with cf.ThreadPoolExecutor(max_workers=args.max_workers) as ex:
                futures = [
                    ex.submit(wait_for_restore, client, args.bucket, r["key"], args.poll_seconds)
                    for r in restore_targets
                ]
                for fut in cf.as_completed(futures):
                    waited_results.append(fut.result())
            write_csv(outdir / "wait_results.csv", waited_results)

    if args.phase in {"all", "copy"}:
        if args.phase == "copy":
            eprint(f"[{now_utc()}] Re-classifying objects before copy...")
            classified = []
            with cf.ThreadPoolExecutor(max_workers=args.max_workers) as ex:
                futures = [ex.submit(classify_object, client, args.bucket, key) for key in keys]
                for fut in cf.as_completed(futures):
                    classified.append(fut.result())
            write_csv(outdir / "classification_copy_phase.csv", classified)
            copy_now = []
            for r in classified:
                if r.get("status") != "classified":
                    continue
                sc = r.get("storage_class", "")
                if r.get("eligible_for_copy_now"):
                    if sc in ARCHIVE_CLASSES or sc == ACTIVE_ARCHIVE_CLASS or args.include_non_archived:
                        copy_now.append(r)
        elif args.wait:
            completed_keys = {r["key"] for r in waited_results if r.get("status") == "restored"}
            archived_ready = [r for r in archived if r["key"] in completed_keys or r.get("eligible_for_copy_now")]
            copy_now = archived_ready + [r for r in copy_now if r.get("storage_class") not in ARCHIVE_CLASSES]

        eprint(f"[{now_utc()}] Copying {len(copy_now)} objects to {TARGET_STORAGE_CLASS}...")
        with cf.ThreadPoolExecutor(max_workers=args.max_workers) as ex:
            futures = []
            for r in copy_now:
                source_key = r["key"]
                dest_key = map_destination_key(source_key, args.source_prefix, args.dest_prefix)
                futures.append(ex.submit(copy_object_to_ia, client, args.bucket, source_key, dest_key, args.dry_run))
            for fut in cf.as_completed(futures):
                copy_results.append(fut.result())
        write_csv(outdir / "copy_results.csv", copy_results)

    summary = {
        "timestamp": now_utc(),
        "bucket": args.bucket,
        "source_prefix": args.source_prefix,
        "dest_prefix": args.dest_prefix,
        "phase": args.phase,
        "dry_run": args.dry_run,
        "total_objects": len(keys),
        "too_long_keys_skipped": len(too_long),
        "archived_objects": len(archived),
        "restore_requests": len(restore_results),
        "wait_checks": len(waited_results),
        "copy_attempts": len(copy_results),
        "target_storage_class": TARGET_STORAGE_CLASS,
    }
    write_json(outdir / "summary.json", summary)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
