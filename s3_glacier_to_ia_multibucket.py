#!/usr/bin/env python3
import argparse
import concurrent.futures as cf
import csv
import json
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

ARCHIVE_CLASSES = {"GLACIER", "DEEP_ARCHIVE"}
ACTIVE_ARCHIVE_CLASS = "GLACIER_IR"
TARGET_STORAGE_CLASS = "STANDARD_IA"
MAX_S3_KEY_BYTES = 1024
DEFAULT_CONN_POOL = 128


thread_local = threading.local()


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def eprint(msg: str) -> None:
    print(msg, file=sys.stderr)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Bulk restore archived S3 objects and copy them to STANDARD_IA across multiple buckets "
            "in the same account and region."
        )
    )
    bucket_group = p.add_mutually_exclusive_group(required=False)
    bucket_group.add_argument("--bucket", help="Single bucket name")
    bucket_group.add_argument("--buckets", nargs="+", help="Explicit list of bucket names")
    bucket_group.add_argument("--bucket-file", help="Text file with one bucket name per line")
    bucket_group.add_argument("--all-buckets-in-region", action="store_true", help="Auto-discover all buckets in the account and process only buckets in --region")

    p.add_argument("--region", required=True, help="AWS region to target, for example ap-south-1")
    p.add_argument("--source-prefix", help="Optional source prefix. Omit to process the whole bucket")
    p.add_argument("--dest-prefix", help="Optional destination prefix; valid only when --source-prefix is used")
    p.add_argument("--days", type=int, default=7, help="Restore retention in days for Glacier/Deep Archive")
    p.add_argument("--tier", choices=["Bulk", "Standard", "Expedited"], default="Standard", help="Restore tier")
    p.add_argument("--phase", choices=["all", "restore", "copy"], default="all", help="Run restore only, copy only, or both")
    p.add_argument("--wait", action="store_true", help="Wait for restore completion before copy")
    p.add_argument("--poll-seconds", type=int, default=300, help="Polling interval while waiting for restore")
    p.add_argument("--bucket-workers", type=int, default=8, help="Parallel bucket worker count")
    p.add_argument("--object-workers", type=int, default=32, help="Parallel object worker count per bucket")
    p.add_argument("--include-non-archived", action="store_true", help="Also copy non-archived objects to STANDARD_IA")
    p.add_argument("--profile", help="AWS profile name")
    p.add_argument("--dry-run", action="store_true", help="Print actions without making changes")
    p.add_argument("--output-dir", default=".", help="Directory for CSV and JSON logs")
    p.add_argument("--expected-bucket-owner", help="Optional expected AWS account ID for bucket ownership checks")
    p.add_argument("--skip-bucket-region-check", action="store_true", help="Skip bucket region discovery if you already passed only same-region buckets")
    return p.parse_args()


def normalize_prefix(prefix: Optional[str]) -> Optional[str]:
    if prefix is None:
        return None
    prefix = prefix.strip()
    if prefix == "":
        return None
    return prefix if prefix.endswith("/") else prefix + "/"


def session_from_args(args: argparse.Namespace):
    session_kwargs = {}
    if args.profile:
        session_kwargs["profile_name"] = args.profile
    return boto3.Session(**session_kwargs)


def make_s3_client(session, region: str, pool_size: int):
    return session.client(
        "s3",
        region_name=region,
        config=Config(retries={"max_attempts": 10, "mode": "standard"}, max_pool_connections=pool_size),
    )


def get_s3_client(session, region: str, pool_size: int):
    key = f"s3::{region}::{pool_size}"
    if not hasattr(thread_local, key.replace(':', '_')):
        setattr(thread_local, key.replace(':', '_'), make_s3_client(session, region, pool_size))
    return getattr(thread_local, key.replace(':', '_'))


def utf8_len(s: str) -> int:
    return len(s.encode("utf-8"))


def discover_buckets(session, region: str, expected_owner: Optional[str], pool_size: int) -> List[str]:
    s3 = make_s3_client(session, region, pool_size)
    resp = s3.list_buckets()
    all_names = [b["Name"] for b in resp.get("Buckets", [])]
    filtered = []
    for name in all_names:
        try:
            params = {"Bucket": name}
            if expected_owner:
                params["ExpectedBucketOwner"] = expected_owner
            head = s3.head_bucket(**params)
            bucket_region = head["ResponseMetadata"]["HTTPHeaders"].get("x-amz-bucket-region")
            if bucket_region == region:
                filtered.append(name)
        except ClientError:
            continue
    return sorted(filtered)


def read_bucket_file(path: str) -> List[str]:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            rows.append(line)
    return rows


def validate_bucket_region(session, bucket: str, region: str, expected_owner: Optional[str], pool_size: int) -> Tuple[str, bool, str]:
    s3 = make_s3_client(session, region, pool_size)
    try:
        params = {"Bucket": bucket}
        if expected_owner:
            params["ExpectedBucketOwner"] = expected_owner
        resp = s3.head_bucket(**params)
        bucket_region = resp["ResponseMetadata"]["HTTPHeaders"].get("x-amz-bucket-region")
        if bucket_region == region:
            return bucket, True, bucket_region
        return bucket, False, bucket_region or "unknown"
    except ClientError as e:
        return bucket, False, e.response.get("Error", {}).get("Code", "Unknown")


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


def bucket_slug(name: str) -> str:
    return name.replace("/", "_")


def process_bucket(session, args: argparse.Namespace, bucket: str, outdir: Path) -> Dict:
    client = get_s3_client(session, args.region, max(args.object_workers * 2, DEFAULT_CONN_POOL))
    bucket_dir = outdir / bucket_slug(bucket)
    bucket_dir.mkdir(parents=True, exist_ok=True)

    scope = f"s3://{bucket}/{args.source_prefix}" if args.source_prefix else f"entire bucket s3://{bucket}"
    eprint(f"[{now_utc()}] Listing objects under {scope}")
    keys = list(list_keys(client, bucket, args.source_prefix))

    if not keys:
        summary = {
            "timestamp": now_utc(),
            "bucket": bucket,
            "source_prefix": args.source_prefix,
            "dest_prefix": args.dest_prefix,
            "message": "No objects found",
        }
        write_json(bucket_dir / "summary.json", summary)
        return summary

    classified: List[Dict] = []
    with cf.ThreadPoolExecutor(max_workers=args.object_workers) as ex:
        futures = [ex.submit(classify_object, client, bucket, key) for key in keys]
        for fut in cf.as_completed(futures):
            classified.append(fut.result())
    write_csv(bucket_dir / "classification.csv", classified)

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
            with cf.ThreadPoolExecutor(max_workers=args.object_workers) as ex:
                futures = [
                    ex.submit(request_restore, client, bucket, r["key"], args.days, args.tier, args.dry_run)
                    for r in restore_targets
                ]
                for fut in cf.as_completed(futures):
                    restore_results.append(fut.result())
            write_csv(bucket_dir / "restore_results.csv", restore_results)

        if args.wait and restore_targets:
            with cf.ThreadPoolExecutor(max_workers=min(args.object_workers, 32)) as ex:
                futures = [
                    ex.submit(wait_for_restore, client, bucket, r["key"], args.poll_seconds)
                    for r in restore_targets
                ]
                for fut in cf.as_completed(futures):
                    waited_results.append(fut.result())
            write_csv(bucket_dir / "wait_results.csv", waited_results)

    if args.phase in {"all", "copy"}:
        if args.phase == "copy":
            classified = []
            with cf.ThreadPoolExecutor(max_workers=args.object_workers) as ex:
                futures = [ex.submit(classify_object, client, bucket, key) for key in keys]
                for fut in cf.as_completed(futures):
                    classified.append(fut.result())
            write_csv(bucket_dir / "classification_copy_phase.csv", classified)
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

        with cf.ThreadPoolExecutor(max_workers=args.object_workers) as ex:
            futures = []
            for r in copy_now:
                source_key = r["key"]
                dest_key = map_destination_key(source_key, args.source_prefix, args.dest_prefix)
                futures.append(ex.submit(copy_object_to_ia, client, bucket, source_key, dest_key, args.dry_run))
            for fut in cf.as_completed(futures):
                copy_results.append(fut.result())
        write_csv(bucket_dir / "copy_results.csv", copy_results)

    summary = {
        "timestamp": now_utc(),
        "bucket": bucket,
        "region": args.region,
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
    write_json(bucket_dir / "summary.json", summary)
    return summary


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
    session = session_from_args(args)

    if args.bucket:
        buckets = [args.bucket]
    elif args.buckets:
        buckets = args.buckets
    elif args.bucket_file:
        buckets = read_bucket_file(args.bucket_file)
    elif args.all_buckets_in_region:
        eprint(f"[{now_utc()}] Discovering buckets in region {args.region}")
        buckets = discover_buckets(session, args.region, args.expected_bucket_owner, DEFAULT_CONN_POOL)
    else:
        eprint("ERROR: pass one of --bucket, --buckets, --bucket-file, or --all-buckets-in-region")
        return 2

    if not buckets:
        eprint("No buckets to process.")
        return 0

    region_rows = []
    if not args.skip_bucket_region_check:
        eprint(f"[{now_utc()}] Validating bucket regions for {len(buckets)} buckets")
        with cf.ThreadPoolExecutor(max_workers=min(len(buckets), args.bucket_workers)) as ex:
            futures = [
                ex.submit(validate_bucket_region, session, b, args.region, args.expected_bucket_owner, DEFAULT_CONN_POOL)
                for b in buckets
            ]
            valid_buckets = []
            for fut in cf.as_completed(futures):
                bucket, ok, detail = fut.result()
                region_rows.append({"bucket": bucket, "ok": ok, "detail": detail})
                if ok:
                    valid_buckets.append(bucket)
        write_csv(outdir / "bucket_region_validation.csv", region_rows)
        buckets = sorted(valid_buckets)

    eprint(f"[{now_utc()}] Processing {len(buckets)} buckets in region {args.region}")
    summaries: List[Dict] = []
    with cf.ThreadPoolExecutor(max_workers=min(len(buckets), args.bucket_workers)) as ex:
        futures = [ex.submit(process_bucket, session, args, bucket, outdir) for bucket in buckets]
        for fut in cf.as_completed(futures):
            summaries.append(fut.result())

    totals = {
        "timestamp": now_utc(),
        "region": args.region,
        "bucket_count": len(summaries),
        "phase": args.phase,
        "dry_run": args.dry_run,
        "total_objects": sum(x.get("total_objects", 0) for x in summaries),
        "too_long_keys_skipped": sum(x.get("too_long_keys_skipped", 0) for x in summaries),
        "archived_objects": sum(x.get("archived_objects", 0) for x in summaries),
        "restore_requests": sum(x.get("restore_requests", 0) for x in summaries),
        "wait_checks": sum(x.get("wait_checks", 0) for x in summaries),
        "copy_attempts": sum(x.get("copy_attempts", 0) for x in summaries),
        "target_storage_class": TARGET_STORAGE_CLASS,
        "buckets": sorted([x.get("bucket") for x in summaries if x.get("bucket")]),
    }
    write_csv(outdir / "bucket_summaries.csv", summaries)
    write_json(outdir / "summary_all_buckets.json", totals)
    print(json.dumps(totals, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
