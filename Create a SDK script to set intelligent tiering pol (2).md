<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# Create a SDK script to set intelligent tiering policy to all buckets in a region in AWS account.

Add option to set the policy for bucket whose name matches specific pattern.

Yes — below is a reusable Python SDK script using boto3 that applies an S3 Intelligent-Tiering configuration to every bucket in a target region, with an optional bucket-name pattern filter. The script uses `put_bucket_intelligent_tiering_configuration`, which supports a configuration ID, optional object prefix filter, and tiering transitions such as `ARCHIVE_ACCESS` and `DEEP_ARCHIVE_ACCESS`; AWS also notes that `us-east-1` buckets return `null` as `LocationConstraint`, and `HeadBucket` is the preferred way to discover a bucket’s region.[^1_1][^1_2]

## Script

```python
#!/usr/bin/env python3

import argparse
import fnmatch
import sys
from botocore.exceptions import ClientError
import boto3


def parse_args():
    parser = argparse.ArgumentParser(
        description="Apply S3 Intelligent-Tiering configuration to all buckets in a region."
    )
    parser.add_argument(
        "--region",
        required=True,
        help="Target AWS region for bucket selection, for example ap-south-1",
    )
    parser.add_argument(
        "--bucket-pattern",
        default="*",
        help="Optional shell-style bucket name pattern, for example prod-* or *-logs",
    )
    parser.add_argument(
        "--object-prefix",
        default=None,
        help="Optional object key prefix filter inside each bucket, for example logs/ or archive/",
    )
    parser.add_argument(
        "--config-id",
        default="default-intelligent-tiering",
        help="Intelligent-Tiering configuration ID",
    )
    parser.add_argument(
        "--archive-days",
        type=int,
        default=90,
        help="Days of no access before ARCHIVE_ACCESS, minimum 90",
    )
    parser.add_argument(
        "--deep-archive-days",
        type=int,
        default=180,
        help="Days of no access before DEEP_ARCHIVE_ACCESS, minimum 180",
    )
    parser.add_argument(
        "--expected-bucket-owner",
        default=None,
        help="Optional 12-digit AWS account ID for safety",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show matching buckets without applying configuration",
    )
    return parser.parse_args()


def validate_args(args):
    if args.archive_days < 90:
        raise ValueError("--archive-days must be at least 90")
    if args.deep_archive_days < 180:
        raise ValueError("--deep-archive-days must be at least 180")
    if args.deep_archive_days <= args.archive_days:
        raise ValueError("--deep-archive-days must be greater than --archive-days")


def get_bucket_region(s3_client, bucket_name, expected_owner=None):
    params = {"Bucket": bucket_name}
    if expected_owner:
        params["ExpectedBucketOwner"] = expected_owner

    response = s3_client.get_bucket_location(**params)
    location = response.get("LocationConstraint")

    if location is None:
        return "us-east-1"
    if location == "EU":
        return "eu-west-1"
    return location


def build_tiering_config(config_id, archive_days, deep_archive_days, object_prefix=None):
    config = {
        "Id": config_id,
        "Status": "Enabled",
        "Tierings": [
            {
                "Days": archive_days,
                "AccessTier": "ARCHIVE_ACCESS",
            },
            {
                "Days": deep_archive_days,
                "AccessTier": "DEEP_ARCHIVE_ACCESS",
            },
        ],
    }

    if object_prefix:
        config["Filter"] = {"Prefix": object_prefix}

    return config


def apply_policy_to_bucket(s3_client, bucket_name, config_id, config, expected_owner=None):
    params = {
        "Bucket": bucket_name,
        "Id": config_id,
        "IntelligentTieringConfiguration": config,
    }
    if expected_owner:
        params["ExpectedBucketOwner"] = expected_owner

    s3_client.put_bucket_intelligent_tiering_configuration(**params)


def main():
    args = parse_args()

    try:
        validate_args(args)
    except ValueError as exc:
        print(f"Argument error: {exc}", file=sys.stderr)
        sys.exit(2)

    s3 = boto3.client("s3")

    try:
        buckets = s3.list_buckets()["Buckets"]
    except ClientError as exc:
        print(f"Failed to list buckets: {exc}", file=sys.stderr)
        sys.exit(1)

    matched_buckets = []
    skipped_buckets = []

    for bucket in buckets:
        bucket_name = bucket["Name"]

        if not fnmatch.fnmatch(bucket_name, args.bucket_pattern):
            continue

        try:
            bucket_region = get_bucket_region(
                s3, bucket_name, expected_owner=args.expected_bucket_owner
            )
        except ClientError as exc:
            skipped_buckets.append((bucket_name, f"region lookup failed: {exc}"))
            continue

        if bucket_region != args.region:
            continue

        matched_buckets.append(bucket_name)

    if not matched_buckets:
        print("No buckets matched the given criteria.")
        if skipped_buckets:
            print("\nSkipped buckets:")
            for name, reason in skipped_buckets:
                print(f"  - {name}: {reason}")
        return

    config = build_tiering_config(
        config_id=args.config_id,
        archive_days=args.archive_days,
        deep_archive_days=args.deep_archive_days,
        object_prefix=args.object_prefix,
    )

    print("Matched buckets:")
    for bucket_name in matched_buckets:
        print(f"  - {bucket_name}")

    if args.dry_run:
        print("\nDry run enabled. No changes were made.")
        return

    print("\nApplying Intelligent-Tiering configuration...")
    success = []
    failed = []

    for bucket_name in matched_buckets:
        try:
            apply_policy_to_bucket(
                s3_client=s3,
                bucket_name=bucket_name,
                config_id=args.config_id,
                config=config,
                expected_owner=args.expected_bucket_owner,
            )
            success.append(bucket_name)
            print(f"[OK] {bucket_name}")
        except ClientError as exc:
            failed.append((bucket_name, str(exc)))
            print(f"[FAILED] {bucket_name}: {exc}")

    print("\nCompleted.")
    print(f"Successful: {len(success)}")
    print(f"Failed: {len(failed)}")

    if failed:
        print("\nFailures:")
        for bucket_name, error in failed:
            print(f"  - {bucket_name}: {error}")

    if skipped_buckets:
        print("\nSkipped during discovery:")
        for bucket_name, reason in skipped_buckets:
            print(f"  - {bucket_name}: {reason}")


if __name__ == "__main__":
    main()
```


## What it does

This script lists all buckets in the account, resolves each bucket’s region, filters buckets to the region you pass with `--region`, and optionally narrows the selection with a shell-style name match such as `prod-*` or `*-logs`.  It then applies `put_bucket_intelligent_tiering_configuration` with a rule ID, `Status`, and `Tierings`, and if you pass `--object-prefix`, it adds the supported `Filter: {Prefix: ...}` so the rule applies only to matching object keys within each bucket.[^1_2][^1_1]

## Example usage

Apply to all buckets in `ap-south-1`:[^1_2]

```bash
python s3_intelligent_tiering_bulk.py --region ap-south-1
```

Apply only to buckets whose names start with `prod-`:[^1_2]

```bash
python s3_intelligent_tiering_bulk.py --region ap-south-1 --bucket-pattern "prod-*"
```

Apply only to matching buckets and only for objects under `logs/`:[^1_1]

```bash
python s3_intelligent_tiering_bulk.py \
  --region ap-south-1 \
  --bucket-pattern "prod-*" \
  --object-prefix "logs/"
```

Preview matching buckets without changes:[^1_2]

```bash
python s3_intelligent_tiering_bulk.py \
  --region ap-south-1 \
  --bucket-pattern "*-logs" \
  --dry-run
```


## Required permissions

The caller needs permission to list buckets and discover their location, and AWS documents that setting the configuration requires `s3:PutIntelligentTieringConfiguration` on the bucket.[^1_1][^1_2]

A minimal starting point is:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListAllBuckets",
      "Effect": "Allow",
      "Action": [
        "s3:ListAllMyBuckets"
      ],
      "Resource": "*"
    },
    {
      "Sid": "BucketLocationAndTiering",
      "Effect": "Allow",
      "Action": [
        "s3:GetBucketLocation",
        "s3:PutIntelligentTieringConfiguration"
      ],
      "Resource": "arn:aws:s3:::*"
    }
  ]
}
```


## Important note

This API configures archive behavior for objects already stored in the S3 Intelligent-Tiering storage class; AWS notes you only need this bucket configuration if you want objects in that storage class to move into Archive Access or Deep Archive Access tiers automatically.[^1_1]

If you want, I can also give you:

- an AWS CLI version,
- a version with regex instead of wildcard matching,
- or a version that assumes role across multiple accounts.
<span style="display:none">[^1_10][^1_11][^1_12][^1_13][^1_14][^1_15][^1_3][^1_4][^1_5][^1_6][^1_7][^1_8][^1_9]</span>

<div align="center">⁂</div>

[^1_1]: https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/put_bucket_intelligent_tiering_configuration.html

[^1_2]: https://github.com/aws-samples/amazon-s3-intelligent-tiering-at-scale/blob/main/Python_put_bucket_policy_configuration.py

[^1_3]: https://dzone.com/articles/automating-storage-tiering-and-lifecycle-policies

[^1_4]: https://boto3.amazonaws.com/v1/documentation/api/1.35.6/reference/services/s3/client/put_bucket_inventory_configuration.html

[^1_5]: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3/client/put_bucket_intelligent_tiering_configuration.html

[^1_6]: https://runebook.dev/en/aws/s3/IntelligentTieringFilter

[^1_7]: https://stackoverflow.com/questions/34811146/boto-get-s3-bucket-location

[^1_8]: https://stackoverflow.com/questions/65357321/s3-bucket-policy-using-boto3

[^1_9]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-intelligent-tiering.html

[^1_10]: https://www.tutorialspoint.com/article/how-to-get-the-bucket-location-of-a-s3-bucket-using-boto3-and-aws-client

[^1_11]: https://www.youtube.com/watch?v=wsIMjdXiz7o

[^1_12]: https://boto3.amazonaws.com/v1/documentation/api/1.33.0/reference/services/s3/client/put_bucket_intelligent_tiering_configuration.html

[^1_13]: https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/get_bucket_location.html

[^1_14]: https://www.reddit.com/r/aws/comments/jt3nqp/s3_storageclassintelligent_tiering_and_defrosting/

[^1_15]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/intelligent-tiering-managing.html


---

# Update the policy to incorporate a set of bucket patterns

Yes — update the script so `--bucket-pattern` accepts multiple values, because Python’s `fnmatch` works on one pattern at a time and is commonly combined across a list of patterns in code.[^2_1][^2_2]

## Updated arguments

Change the argument from a single string to a list using `nargs="+"`, so you can pass one or more shell-style patterns like `prod-*`, `*-logs`, or `data-*`.[^2_1]

```python
parser.add_argument(
    "--bucket-patterns",
    nargs="+",
    default=["*"],
    help='One or more shell-style bucket name patterns, for example "prod-*" "*-logs" "data-*"',
)
```


## Updated matching logic

Replace the single-pattern check with `any(...)`, so a bucket is selected if its name matches at least one supplied pattern.[^2_2][^2_1]

```python
def bucket_matches_patterns(bucket_name, patterns):
    return any(fnmatch.fnmatch(bucket_name, pattern) for pattern in patterns)
```

Then replace:

```python
if not fnmatch.fnmatch(bucket_name, args.bucket_pattern):
    continue
```

with:

```python
if not bucket_matches_patterns(bucket_name, args.bucket_patterns):
    continue
```


## Full updated script

This version keeps the same Intelligent-Tiering API behavior and filter support, while adding support for a set of bucket patterns. AWS documents that the Intelligent-Tiering configuration can include an optional `Filter` and required `Tierings`, with `ARCHIVE_ACCESS` requiring at least 90 days and `DEEP_ARCHIVE_ACCESS` requiring at least 180 days.[^2_3]

```python
#!/usr/bin/env python3

import argparse
import fnmatch
import sys
from botocore.exceptions import ClientError
import boto3


def parse_args():
    parser = argparse.ArgumentParser(
        description="Apply S3 Intelligent-Tiering configuration to all buckets in a region."
    )
    parser.add_argument(
        "--region",
        required=True,
        help="Target AWS region for bucket selection, for example ap-south-1",
    )
    parser.add_argument(
        "--bucket-patterns",
        nargs="+",
        default=["*"],
        help='One or more shell-style bucket name patterns, for example "prod-*" "*-logs" "data-*"',
    )
    parser.add_argument(
        "--object-prefix",
        default=None,
        help="Optional object key prefix filter inside each bucket, for example logs/ or archive/",
    )
    parser.add_argument(
        "--config-id",
        default="default-intelligent-tiering",
        help="Intelligent-Tiering configuration ID",
    )
    parser.add_argument(
        "--archive-days",
        type=int,
        default=90,
        help="Days of no access before ARCHIVE_ACCESS, minimum 90",
    )
    parser.add_argument(
        "--deep-archive-days",
        type=int,
        default=180,
        help="Days of no access before DEEP_ARCHIVE_ACCESS, minimum 180",
    )
    parser.add_argument(
        "--expected-bucket-owner",
        default=None,
        help="Optional 12-digit AWS account ID for safety",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show matching buckets without applying configuration",
    )
    return parser.parse_args()


def validate_args(args):
    if args.archive_days < 90:
        raise ValueError("--archive-days must be at least 90")
    if args.deep_archive_days < 180:
        raise ValueError("--deep-archive-days must be at least 180")
    if args.deep_archive_days <= args.archive_days:
        raise ValueError("--deep-archive-days must be greater than --archive-days")


def bucket_matches_patterns(bucket_name, patterns):
    return any(fnmatch.fnmatch(bucket_name, pattern) for pattern in patterns)


def get_bucket_region(s3_client, bucket_name, expected_owner=None):
    params = {"Bucket": bucket_name}
    if expected_owner:
        params["ExpectedBucketOwner"] = expected_owner

    response = s3_client.get_bucket_location(**params)
    location = response.get("LocationConstraint")

    if location is None:
        return "us-east-1"
    if location == "EU":
        return "eu-west-1"
    return location


def build_tiering_config(config_id, archive_days, deep_archive_days, object_prefix=None):
    config = {
        "Id": config_id,
        "Status": "Enabled",
        "Tierings": [
            {
                "Days": archive_days,
                "AccessTier": "ARCHIVE_ACCESS",
            },
            {
                "Days": deep_archive_days,
                "AccessTier": "DEEP_ARCHIVE_ACCESS",
            },
        ],
    }

    if object_prefix:
        config["Filter"] = {"Prefix": object_prefix}

    return config


def apply_policy_to_bucket(s3_client, bucket_name, config_id, config, expected_owner=None):
    params = {
        "Bucket": bucket_name,
        "Id": config_id,
        "IntelligentTieringConfiguration": config,
    }
    if expected_owner:
        params["ExpectedBucketOwner"] = expected_owner

    s3_client.put_bucket_intelligent_tiering_configuration(**params)


def main():
    args = parse_args()

    try:
        validate_args(args)
    except ValueError as exc:
        print(f"Argument error: {exc}", file=sys.stderr)
        sys.exit(2)

    s3 = boto3.client("s3")

    try:
        buckets = s3.list_buckets()["Buckets"]
    except ClientError as exc:
        print(f"Failed to list buckets: {exc}", file=sys.stderr)
        sys.exit(1)

    matched_buckets = []
    skipped_buckets = []

    for bucket in buckets:
        bucket_name = bucket["Name"]

        if not bucket_matches_patterns(bucket_name, args.bucket_patterns):
            continue

        try:
            bucket_region = get_bucket_region(
                s3, bucket_name, expected_owner=args.expected_bucket_owner
            )
        except ClientError as exc:
            skipped_buckets.append((bucket_name, f"region lookup failed: {exc}"))
            continue

        if bucket_region != args.region:
            continue

        matched_buckets.append(bucket_name)

    if not matched_buckets:
        print("No buckets matched the given criteria.")
        if skipped_buckets:
            print("\nSkipped buckets:")
            for name, reason in skipped_buckets:
                print(f"  - {name}: {reason}")
        return

    config = build_tiering_config(
        config_id=args.config_id,
        archive_days=args.archive_days,
        deep_archive_days=args.deep_archive_days,
        object_prefix=args.object_prefix,
    )

    print("Bucket patterns:", ", ".join(args.bucket_patterns))
    print("Matched buckets:")
    for bucket_name in matched_buckets:
        print(f"  - {bucket_name}")

    if args.dry_run:
        print("\nDry run enabled. No changes were made.")
        return

    print("\nApplying Intelligent-Tiering configuration...")
    success = []
    failed = []

    for bucket_name in matched_buckets:
        try:
            apply_policy_to_bucket(
                s3_client=s3,
                bucket_name=bucket_name,
                config_id=args.config_id,
                config=config,
                expected_owner=args.expected_bucket_owner,
            )
            success.append(bucket_name)
            print(f"[OK] {bucket_name}")
        except ClientError as exc:
            failed.append((bucket_name, str(exc)))
            print(f"[FAILED] {bucket_name}: {exc}")

    print("\nCompleted.")
    print(f"Successful: {len(success)}")
    print(f"Failed: {len(failed)}")

    if failed:
        print("\nFailures:")
        for bucket_name, error in failed:
            print(f"  - {bucket_name}: {error}")

    if skipped_buckets:
        print("\nSkipped during discovery:")
        for bucket_name, reason in skipped_buckets:
            print(f"  - {bucket_name}: {reason}")


if __name__ == "__main__":
    main()
```


## Usage examples

You can now pass a set of patterns in one command, and any bucket matching one of them will be included.[^2_2][^2_1]

```bash
python s3_intelligent_tiering_bulk.py \
  --region ap-south-1 \
  --bucket-patterns "prod-*" "*-logs" "data-*"
```

With object prefix filter:[^2_3]

```bash
python s3_intelligent_tiering_bulk.py \
  --region ap-south-1 \
  --bucket-patterns "prod-*" "*-archive" \
  --object-prefix "logs/"
```

Dry run first:[^2_1]

```bash
python s3_intelligent_tiering_bulk.py \
  --region ap-south-1 \
  --bucket-patterns "prod-*" "*-logs" \
  --dry-run
```


## Optional enhancement

If you want, I can make it even cleaner by supporting:

- comma-separated patterns like `--bucket-patterns prod-*,*-logs,data-*`,
- regex matching instead of wildcard matching,
- or exclude patterns such as `--exclude-patterns "*-tmp" "*-backup"`.
<span style="display:none">[^2_10][^2_11][^2_12][^2_13][^2_14][^2_15][^2_4][^2_5][^2_6][^2_7][^2_8][^2_9]</span>

<div align="center">⁂</div>

[^2_1]: https://docs.python.org/3/library/fnmatch.html

[^2_2]: https://stackoverflow.com/questions/5351766/use-fnmatch-filter-to-filter-files-by-more-than-one-possible-file-extension

[^2_3]: https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/put_bucket_intelligent_tiering_configuration.html

[^2_4]: https://www.geeksforgeeks.org/python/fnmatch-unix-filename-pattern-matching-python/

[^2_5]: https://www.thecodingforums.com/threads/more-efficient-fnmatch-fnmatch-for-multiple-patterns.397998/

[^2_6]: https://facelessuser.github.io/wcmatch/fnmatch/

[^2_7]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/metrics-configurations-filter.html

[^2_8]: https://www.w3schools.com/python/ref_module_fnmatch.asp

[^2_9]: https://docs.aws.amazon.com/cli/latest/reference/s3api/put-bucket-intelligent-tiering-configuration.html

[^2_10]: https://docs.aws.amazon.com/AmazonS3/latest/API/API_IntelligentTieringConfiguration.html

[^2_11]: https://github.com/python/cpython/blob/main/Lib/fnmatch.py

[^2_12]: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3/client/put_bucket_intelligent_tiering_configuration.html

[^2_13]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/intelligent-tiering-overview.html

[^2_14]: https://pymotw.com/3/fnmatch/index.html

[^2_15]: https://github.com/aws-samples/amazon-s3-intelligent-tiering-at-scale/blob/main/Python_put_bucket_policy_configuration.py


---

# Update the script to set a custom policy

Yes — the cleanest way to support a **custom policy** is to let the script accept either a JSON string or a JSON file and pass that structure directly as the `IntelligentTieringConfiguration`. AWS’s boto3 API supports a custom configuration object with `Id`, `Status`, optional `Filter` using `Prefix`, `Tag`, or `And`, and `Tierings` containing `ARCHIVE_ACCESS` and `DEEP_ARCHIVE_ACCESS`; AWS also documents the minimum days as 90 and 180 respectively, with a maximum of 730 days.[^3_1]

## Recommended approach

Instead of hardcoding `archive_days`, `deep_archive_days`, and `object_prefix`, make the script accept:

- `--policy-file policy.json`, or
- `--policy-json '{"Id":"...","Status":"Enabled",...}'`[^3_2][^3_1]

That makes the script flexible enough for:

- prefix-only policies,
- tag-based policies,
- prefix-and-tag policies,
- enabled or disabled configs,
- and different tiering day values within AWS limits.[^3_1]


## Updated script

This version keeps the region filter and multiple bucket patterns, but replaces the fixed policy builder with a custom policy loader. The script validates required fields before calling `put_bucket_intelligent_tiering_configuration`.[^3_2][^3_1]

```python
#!/usr/bin/env python3

import argparse
import fnmatch
import json
import sys

import boto3
from botocore.exceptions import ClientError


def parse_args():
    parser = argparse.ArgumentParser(
        description="Apply a custom S3 Intelligent-Tiering configuration to buckets in a region."
    )
    parser.add_argument(
        "--region",
        required=True,
        help="Target AWS region for bucket selection, for example ap-south-1",
    )
    parser.add_argument(
        "--bucket-patterns",
        nargs="+",
        default=["*"],
        help='One or more shell-style bucket name patterns, for example "prod-*" "*-logs" "data-*"',
    )
    parser.add_argument(
        "--policy-file",
        help="Path to a JSON file containing the Intelligent-Tiering configuration",
    )
    parser.add_argument(
        "--policy-json",
        help='Inline JSON string for the Intelligent-Tiering configuration',
    )
    parser.add_argument(
        "--expected-bucket-owner",
        default=None,
        help="Optional 12-digit AWS account ID for safety",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show matching buckets and validated policy without applying configuration",
    )
    return parser.parse_args()


def bucket_matches_patterns(bucket_name, patterns):
    return any(fnmatch.fnmatch(bucket_name, pattern) for pattern in patterns)


def get_bucket_region(s3_client, bucket_name, expected_owner=None):
    params = {"Bucket": bucket_name}
    if expected_owner:
        params["ExpectedBucketOwner"] = expected_owner

    response = s3_client.get_bucket_location(**params)
    location = response.get("LocationConstraint")

    if location is None:
        return "us-east-1"
    if location == "EU":
        return "eu-west-1"
    return location


def load_policy(args):
    if bool(args.policy_file) == bool(args.policy_json):
        raise ValueError("Provide exactly one of --policy-file or --policy-json")

    if args.policy_file:
        with open(args.policy_file, "r", encoding="utf-8") as f:
            policy = json.load(f)
    else:
        policy = json.loads(args.policy_json)

    return policy


def validate_policy(policy):
    if not isinstance(policy, dict):
        raise ValueError("Policy must be a JSON object")

    required_top_level = ["Id", "Status", "Tierings"]
    for field in required_top_level:
        if field not in policy:
            raise ValueError(f"Policy missing required field: {field}")

    if policy["Status"] not in ("Enabled", "Disabled"):
        raise ValueError("Policy Status must be Enabled or Disabled")

    if not isinstance(policy["Tierings"], list) or not policy["Tierings"]:
        raise ValueError("Policy Tierings must be a non-empty list")

    valid_tiers = {"ARCHIVE_ACCESS", "DEEP_ARCHIVE_ACCESS"}

    for tier in policy["Tierings"]:
        if "AccessTier" not in tier or "Days" not in tier:
            raise ValueError("Each tiering entry must include AccessTier and Days")

        if tier["AccessTier"] not in valid_tiers:
            raise ValueError(
                f"Invalid AccessTier: {tier['AccessTier']}. "
                "Allowed values: ARCHIVE_ACCESS, DEEP_ARCHIVE_ACCESS"
            )

        if not isinstance(tier["Days"], int):
            raise ValueError("Tiering Days must be an integer")

        if tier["AccessTier"] == "ARCHIVE_ACCESS":
            if tier["Days"] < 90 or tier["Days"] > 730:
                raise ValueError("ARCHIVE_ACCESS Days must be between 90 and 730")

        if tier["AccessTier"] == "DEEP_ARCHIVE_ACCESS":
            if tier["Days"] < 180 or tier["Days"] > 730:
                raise ValueError("DEEP_ARCHIVE_ACCESS Days must be between 180 and 730")

    archive_days = next(
        (t["Days"] for t in policy["Tierings"] if t["AccessTier"] == "ARCHIVE_ACCESS"),
        None,
    )
    deep_archive_days = next(
        (t["Days"] for t in policy["Tierings"] if t["AccessTier"] == "DEEP_ARCHIVE_ACCESS"),
        None,
    )

    if archive_days is not None and deep_archive_days is not None:
        if deep_archive_days <= archive_days:
            raise ValueError("DEEP_ARCHIVE_ACCESS Days must be greater than ARCHIVE_ACCESS Days")

    if "Filter" in policy:
        filter_obj = policy["Filter"]
        if not isinstance(filter_obj, dict):
            raise ValueError("Filter must be a JSON object")

        allowed_filter_keys = {"Prefix", "Tag", "And"}
        unknown_keys = set(filter_obj.keys()) - allowed_filter_keys
        if unknown_keys:
            raise ValueError(f"Unsupported Filter keys: {sorted(unknown_keys)}")

    return policy["Id"]


def apply_policy_to_bucket(s3_client, bucket_name, config_id, policy, expected_owner=None):
    params = {
        "Bucket": bucket_name,
        "Id": config_id,
        "IntelligentTieringConfiguration": policy,
    }
    if expected_owner:
        params["ExpectedBucketOwner"] = expected_owner

    s3_client.put_bucket_intelligent_tiering_configuration(**params)


def main():
    args = parse_args()

    try:
        policy = load_policy(args)
        config_id = validate_policy(policy)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"Policy error: {exc}", file=sys.stderr)
        sys.exit(2)

    s3 = boto3.client("s3")

    try:
        buckets = s3.list_buckets()["Buckets"]
    except ClientError as exc:
        print(f"Failed to list buckets: {exc}", file=sys.stderr)
        sys.exit(1)

    matched_buckets = []
    skipped_buckets = []

    for bucket in buckets:
        bucket_name = bucket["Name"]

        if not bucket_matches_patterns(bucket_name, args.bucket_patterns):
            continue

        try:
            bucket_region = get_bucket_region(
                s3, bucket_name, expected_owner=args.expected_bucket_owner
            )
        except ClientError as exc:
            skipped_buckets.append((bucket_name, f"region lookup failed: {exc}"))
            continue

        if bucket_region != args.region:
            continue

        matched_buckets.append(bucket_name)

    if not matched_buckets:
        print("No buckets matched the given criteria.")
        if skipped_buckets:
            print("\nSkipped buckets:")
            for name, reason in skipped_buckets:
                print(f"  - {name}: {reason}")
        return

    print("Bucket patterns:", ", ".join(args.bucket_patterns))
    print("Policy ID:", config_id)
    print("Matched buckets:")
    for bucket_name in matched_buckets:
        print(f"  - {bucket_name}")

    if args.dry_run:
        print("\nValidated policy:")
        print(json.dumps(policy, indent=2))
        print("\nDry run enabled. No changes were made.")
        return

    print("\nApplying Intelligent-Tiering configuration...")
    success = []
    failed = []

    for bucket_name in matched_buckets:
        try:
            apply_policy_to_bucket(
                s3_client=s3,
                bucket_name=bucket_name,
                config_id=config_id,
                policy=policy,
                expected_owner=args.expected_bucket_owner,
            )
            success.append(bucket_name)
            print(f"[OK] {bucket_name}")
        except ClientError as exc:
            failed.append((bucket_name, str(exc)))
            print(f"[FAILED] {bucket_name}: {exc}")

    print("\nCompleted.")
    print(f"Successful: {len(success)}")
    print(f"Failed: {len(failed)}")

    if failed:
        print("\nFailures:")
        for bucket_name, error in failed:
            print(f"  - {bucket_name}: {error}")

    if skipped_buckets:
        print("\nSkipped during discovery:")
        for bucket_name, reason in skipped_buckets:
            print(f"  - {bucket_name}: {reason}")


if __name__ == "__main__":
    main()
```


## Example policy file

A valid custom policy can include a prefix filter and both archive tiers, because boto3 supports `Filter` with `Prefix`, `Tag`, or `And`, plus the `Tierings` list.[^3_1]

```json
{
  "Id": "custom-logs-tiering",
  "Status": "Enabled",
  "Filter": {
    "Prefix": "logs/"
  },
  "Tierings": [
    {
      "AccessTier": "ARCHIVE_ACCESS",
      "Days": 120
    },
    {
      "AccessTier": "DEEP_ARCHIVE_ACCESS",
      "Days": 210
    }
  ]
}
```


## Tag-based example

AWS also supports a tag-based filter in the same policy structure.[^3_1]

```json
{
  "Id": "tag-based-tiering",
  "Status": "Enabled",
  "Filter": {
    "Tag": {
      "Key": "archive",
      "Value": "true"
    }
  },
  "Tierings": [
    {
      "AccessTier": "ARCHIVE_ACCESS",
      "Days": 90
    },
    {
      "AccessTier": "DEEP_ARCHIVE_ACCESS",
      "Days": 180
    }
  ]
}
```


## Prefix and tag together

AWS’s `Filter.And` form lets you require both a prefix and one or more tags.[^3_1]

```json
{
  "Id": "raw-data-tiering",
  "Status": "Enabled",
  "Filter": {
    "And": {
      "Prefix": "raw/",
      "Tags": [
        {
          "Key": "dataset",
          "Value": "cold"
        }
      ]
    }
  },
  "Tierings": [
    {
      "AccessTier": "ARCHIVE_ACCESS",
      "Days": 90
    },
    {
      "AccessTier": "DEEP_ARCHIVE_ACCESS",
      "Days": 180
    }
  ]
}
```


## Usage examples

Use a policy file:[^3_2]

```bash
python s3_intelligent_tiering_bulk.py \
  --region ap-south-1 \
  --bucket-patterns "prod-*" "*-logs" \
  --policy-file policy.json
```

Use inline JSON:[^3_2]

```bash
python s3_intelligent_tiering_bulk.py \
  --region ap-south-1 \
  --bucket-patterns "prod-*" \
  --policy-json '{"Id":"custom-tiering","Status":"Enabled","Tierings":[{"AccessTier":"ARCHIVE_ACCESS","Days":90},{"AccessTier":"DEEP_ARCHIVE_ACCESS","Days":180}]}'
```

Dry run first:[^3_2]

```bash
python s3_intelligent_tiering_bulk.py \
  --region ap-south-1 \
  --bucket-patterns "prod-*" "*-logs" \
  --policy-file policy.json \
  --dry-run
```


## Practical note

The policy is sent as-is to `put_bucket_intelligent_tiering_configuration`, so if you reuse the same `Id`, the configuration is updated for each bucket with that ID rather than creating a different rule shape in the script itself. AWS also documents a limit of up to 1,000 Intelligent-Tiering configurations per bucket.[^3_1]

If you want, I can next update this into:

- a **production-ready version with logging and retry/backoff**,
- a **cross-account assume-role version**,
- or a **version that first checks whether the same policy already exists before updating**.
<span style="display:none">[^3_10][^3_11][^3_12][^3_13][^3_14][^3_15][^3_3][^3_4][^3_5][^3_6][^3_7][^3_8][^3_9]</span>

<div align="center">⁂</div>

[^3_1]: https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/put_bucket_intelligent_tiering_configuration.html

[^3_2]: https://docs.python.org/3/library/argparse.html

[^3_3]: https://boto3.amazonaws.com/v1/documentation/api/1.26.86/reference/services/s3/client/list_bucket_intelligent_tiering_configurations.html

[^3_4]: https://oneuptime.com/blog/post/2026-02-12-s3-intelligent-tiering-optimize-storage-costs/view

[^3_5]: https://stackoverflow.com/questions/59039076/how-to-upload-a-file-to-amazon-glacier-deep-archive-using-boto3

[^3_6]: https://github.com/aws-samples/amazon-s3-intelligent-tiering-at-scale/blob/main/Python_put_bucket_policy_configuration.py

[^3_7]: https://runebook.dev/en/aws/s3/IntelligentTieringFilter

[^3_8]: https://gist.github.com/matthewfeickert/3b7d30e408fe4002aac728fc911ced35

[^3_9]: https://discuss.elastic.co/t/s3-intelligent-tiering-class-with-deep-archive-access-tier-for-snapshots-is-working/342122

[^3_10]: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3/client/list_bucket_intelligent_tiering_configurations.html

[^3_11]: https://www.cloudthat.com/resources/blog/leveraging-intelligent-tiering-with-amazon-s3

[^3_12]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-intelligent-tiering.html

[^3_13]: https://bugs.python.org/issue35005

[^3_14]: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3/client/put_bucket_intelligent_tiering_configuration.html

[^3_15]: https://boto3.amazonaws.com/v1/documentation/api/1.33.2/reference/services/s3/client/put_bucket_intelligent_tiering_configuration.html


---

# Update the script to remove all existing lifecycle policies and add new one. Add params to control if policies needed to be removed or added or both.

Yes — this needs to switch from the Intelligent-Tiering bucket configuration API to the **S3 lifecycle configuration** APIs, because removing existing lifecycle rules and adding a new lifecycle rule is done with `delete_bucket_lifecycle` and `put_bucket_lifecycle_configuration`. AWS documents that `delete_bucket_lifecycle` removes all lifecycle rules on a bucket, while `put_bucket_lifecycle_configuration` creates or replaces the lifecycle configuration for that bucket.[^4_1][^4_2]

## What changes

The updated script below adds an operation selector so you can choose:

- `remove` — delete all existing lifecycle rules,
- `add` — add or replace with a new lifecycle configuration,
- `both` — first remove all lifecycle rules, then apply the new one.[^4_2][^4_1]

It also accepts a custom lifecycle policy from `--policy-file` or `--policy-json`, because lifecycle rules can include filters such as prefix, tags, size filters, transitions, expirations, and noncurrent version actions.[^4_3][^4_1]

## Updated script

```python
#!/usr/bin/env python3

import argparse
import fnmatch
import json
import sys

import boto3
from botocore.exceptions import ClientError


def parse_args():
    parser = argparse.ArgumentParser(
        description="Remove and/or apply S3 lifecycle policies to buckets in a region."
    )
    parser.add_argument(
        "--region",
        required=True,
        help="Target AWS region for bucket selection, for example ap-south-1",
    )
    parser.add_argument(
        "--bucket-patterns",
        nargs="+",
        default=["*"],
        help='One or more shell-style bucket name patterns, for example "prod-*" "*-logs" "data-*"',
    )
    parser.add_argument(
        "--mode",
        choices=["remove", "add", "both"],
        required=True,
        help="Operation mode: remove existing lifecycle policy, add new one, or do both",
    )
    parser.add_argument(
        "--policy-file",
        help="Path to a JSON file containing the LifecycleConfiguration payload",
    )
    parser.add_argument(
        "--policy-json",
        help='Inline JSON string containing the LifecycleConfiguration payload',
    )
    parser.add_argument(
        "--expected-bucket-owner",
        default=None,
        help="Optional 12-digit AWS account ID for safety",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show matching buckets and intended actions without making changes",
    )
    return parser.parse_args()


def bucket_matches_patterns(bucket_name, patterns):
    return any(fnmatch.fnmatch(bucket_name, pattern) for pattern in patterns)


def get_bucket_region(s3_client, bucket_name, expected_owner=None):
    params = {"Bucket": bucket_name}
    if expected_owner:
        params["ExpectedBucketOwner"] = expected_owner

    response = s3_client.get_bucket_location(**params)
    location = response.get("LocationConstraint")

    if location is None:
        return "us-east-1"
    if location == "EU":
        return "eu-west-1"
    return location


def load_policy(args):
    if args.mode in ("add", "both"):
        if bool(args.policy_file) == bool(args.policy_json):
            raise ValueError("For mode add/both, provide exactly one of --policy-file or --policy-json")

        if args.policy_file:
            with open(args.policy_file, "r", encoding="utf-8") as f:
                policy = json.load(f)
        else:
            policy = json.loads(args.policy_json)

        return policy

    return None


def validate_lifecycle_policy(policy):
    if not isinstance(policy, dict):
        raise ValueError("Lifecycle policy must be a JSON object")

    if "Rules" not in policy:
        raise ValueError("Lifecycle policy must contain 'Rules'")

    rules = policy["Rules"]
    if not isinstance(rules, list) or not rules:
        raise ValueError("'Rules' must be a non-empty list")

    if len(rules) > 1000:
        raise ValueError("S3 lifecycle configuration supports up to 1000 rules per bucket")

    for idx, rule in enumerate(rules, start=1):
        if not isinstance(rule, dict):
            raise ValueError(f"Rule #{idx} must be an object")

        if "Status" not in rule:
            raise ValueError(f"Rule #{idx} missing required field: Status")

        if rule["Status"] not in ("Enabled", "Disabled"):
            raise ValueError(f"Rule #{idx} Status must be Enabled or Disabled")

        has_filter = "Filter" in rule
        has_prefix = "Prefix" in rule

        if has_filter and has_prefix:
            raise ValueError(f"Rule #{idx} cannot contain both Prefix and Filter")

        actions = [
            "Transitions",
            "Expiration",
            "NoncurrentVersionTransitions",
            "NoncurrentVersionExpiration",
            "AbortIncompleteMultipartUpload",
            "ExpiredObjectDeleteMarker",
        ]
        if not any(action in rule for action in actions):
            raise ValueError(f"Rule #{idx} must define at least one lifecycle action")

    return True


def remove_lifecycle_policy(s3_client, bucket_name, expected_owner=None):
    params = {"Bucket": bucket_name}
    if expected_owner:
        params["ExpectedBucketOwner"] = expected_owner

    s3_client.delete_bucket_lifecycle(**params)


def add_lifecycle_policy(s3_client, bucket_name, policy, expected_owner=None):
    params = {
        "Bucket": bucket_name,
        "LifecycleConfiguration": policy,
    }
    if expected_owner:
        params["ExpectedBucketOwner"] = expected_owner

    s3_client.put_bucket_lifecycle_configuration(**params)


def main():
    args = parse_args()

    try:
        policy = load_policy(args)
        if policy is not None:
            validate_lifecycle_policy(policy)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"Policy error: {exc}", file=sys.stderr)
        sys.exit(2)

    s3 = boto3.client("s3")

    try:
        buckets = s3.list_buckets()["Buckets"]
    except ClientError as exc:
        print(f"Failed to list buckets: {exc}", file=sys.stderr)
        sys.exit(1)

    matched_buckets = []
    skipped_buckets = []

    for bucket in buckets:
        bucket_name = bucket["Name"]

        if not bucket_matches_patterns(bucket_name, args.bucket_patterns):
            continue

        try:
            bucket_region = get_bucket_region(
                s3, bucket_name, expected_owner=args.expected_bucket_owner
            )
        except ClientError as exc:
            skipped_buckets.append((bucket_name, f"region lookup failed: {exc}"))
            continue

        if bucket_region != args.region:
            continue

        matched_buckets.append(bucket_name)

    if not matched_buckets:
        print("No buckets matched the given criteria.")
        if skipped_buckets:
            print("\nSkipped buckets:")
            for name, reason in skipped_buckets:
                print(f"  - {name}: {reason}")
        return

    print("Bucket patterns:", ", ".join(args.bucket_patterns))
    print("Mode:", args.mode)
    print("Matched buckets:")
    for bucket_name in matched_buckets:
        print(f"  - {bucket_name}")

    if policy is not None:
        print("\nValidated lifecycle policy:")
        print(json.dumps(policy, indent=2))

    if args.dry_run:
        print("\nDry run enabled. No changes were made.")
        return

    removed = []
    added = []
    failed = []

    for bucket_name in matched_buckets:
        try:
            if args.mode in ("remove", "both"):
                remove_lifecycle_policy(
                    s3_client=s3,
                    bucket_name=bucket_name,
                    expected_owner=args.expected_bucket_owner,
                )
                removed.append(bucket_name)
                print(f"[REMOVED] {bucket_name}")

            if args.mode in ("add", "both"):
                add_lifecycle_policy(
                    s3_client=s3,
                    bucket_name=bucket_name,
                    policy=policy,
                    expected_owner=args.expected_bucket_owner,
                )
                added.append(bucket_name)
                print(f"[ADDED] {bucket_name}")

        except ClientError as exc:
            failed.append((bucket_name, str(exc)))
            print(f"[FAILED] {bucket_name}: {exc}")

    print("\nCompleted.")
    print(f"Removed: {len(removed)}")
    print(f"Added: {len(added)}")
    print(f"Failed: {len(failed)}")

    if failed:
        print("\nFailures:")
        for bucket_name, error in failed:
            print(f"  - {bucket_name}: {error}")

    if skipped_buckets:
        print("\nSkipped during discovery:")
        for bucket_name, reason in skipped_buckets:
            print(f"  - {bucket_name}: {reason}")


if __name__ == "__main__":
    main()
```


## Example lifecycle policy

AWS lifecycle configuration uses a `Rules` array, and each rule can target objects using `Filter` with prefix, tags, or combinations, then apply transition or expiration actions.[^4_4][^4_3]

```json
{
  "Rules": [
    {
      "ID": "move-logs-to-intelligent-tiering",
      "Status": "Enabled",
      "Filter": {
        "Prefix": "logs/"
      },
      "Transitions": [
        {
          "Days": 0,
          "StorageClass": "INTELLIGENT_TIERING"
        }
      ]
    }
  ]
}
```


## Commands

Remove all existing lifecycle policies from matching buckets:[^4_2]

```bash
python s3_lifecycle_bulk.py \
  --region ap-south-1 \
  --bucket-patterns "prod-*" "*-logs" \
  --mode remove
```

Add or replace lifecycle policy on matching buckets:[^4_1]

```bash
python s3_lifecycle_bulk.py \
  --region ap-south-1 \
  --bucket-patterns "prod-*" "*-logs" \
  --mode add \
  --policy-file lifecycle-policy.json
```

Remove old policies and then add the new one:[^4_1][^4_2]

```bash
python s3_lifecycle_bulk.py \
  --region ap-south-1 \
  --bucket-patterns "prod-*" "*-logs" \
  --mode both \
  --policy-file lifecycle-policy.json
```

Dry run first:[^4_1]

```bash
python s3_lifecycle_bulk.py \
  --region ap-south-1 \
  --bucket-patterns "prod-*" "*-logs" \
  --mode both \
  --policy-file lifecycle-policy.json \
  --dry-run
```


## Important behavior

`put_bucket_lifecycle_configuration` replaces the bucket’s existing lifecycle configuration, so if you use `--mode add`, the new policy already overwrites the old lifecycle configuration without needing a separate remove step. The explicit `remove` step is only useful when you want a clean deletion-only action or want the workflow to be operationally explicit as `remove` then `add`.[^4_1]

## IAM permissions

AWS documents that deleting lifecycle configuration requires `s3:PutLifecycleConfiguration`, and the same lifecycle configuration API family is used to manage bucket lifecycle rules.[^4_5][^4_1]

A practical policy baseline is:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListBuckets",
      "Effect": "Allow",
      "Action": [
        "s3:ListAllMyBuckets"
      ],
      "Resource": "*"
    },
    {
      "Sid": "ManageLifecycle",
      "Effect": "Allow",
      "Action": [
        "s3:GetBucketLocation",
        "s3:GetLifecycleConfiguration",
        "s3:PutLifecycleConfiguration"
      ],
      "Resource": "arn:aws:s3:::*"
    }
  ]
}
```

If you want, I can make the next version more production-ready with:

- `--skip-if-no-lifecycle`,
- backup/export of existing lifecycle rules before removal,
- assume-role support for multi-account runs,
- or a safer confirmation prompt before bulk delete.
<span style="display:none">[^4_10][^4_11][^4_12][^4_13][^4_14][^4_15][^4_6][^4_7][^4_8][^4_9]</span>

<div align="center">⁂</div>

[^4_1]: https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/put_bucket_lifecycle_configuration.html

[^4_2]: https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/delete_bucket_lifecycle.html

[^4_3]: https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/get_bucket_lifecycle_configuration.html

[^4_4]: https://github.com/awsdocs/amazon-s3-developer-guide/blob/master/doc_source/intro-lifecycle-rules.md?plain=1

[^4_5]: https://boto3.amazonaws.com/v1/documentation/api/1.35.2/reference/services/s3/client/delete_bucket_lifecycle.html

[^4_6]: https://stackoverflow.com/questions/44170622/how-to-setup-lifecycle-to-delete-folders-under-s3-bucket-using-boto3

[^4_7]: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3/client/put_bucket_lifecycle_configuration.html

[^4_8]: https://boto3.amazonaws.com/v1/documentation/api/1.26.87/reference/services/s3/bucketlifecycleconfiguration/put.html

[^4_9]: https://boto3.amazonaws.com/v1/documentation/api/1.28.55/reference/services/s3/client/get_bucket_lifecycle_configuration.html

[^4_10]: https://techdocs.akamai.com/cloud-computing/docs/use-tags-and-prefixes-in-lifecycle-policies-to-delete-objects

[^4_11]: https://servicedesk.surf.nl/wiki/spaces/WIKI/pages/112592348/Object+Store+S3+Life+Cycle+Policies

[^4_12]: https://stackoverflow.com/questions/66357302/s3-bucket-lifecycle-configuration-with-boto3-lambda-function-and-getting-malform

[^4_13]: https://docs.amazonaws.cn/en_us/AmazonS3/latest/userguide/intro-lifecycle-rules.html

[^4_14]: https://github.com/aws-samples/amazon-s3-mpu-lifecycle-management/blob/main/s3_lifecycle_rule_configurator.py

[^4_15]: https://github.com/boto/boto3/issues/2491


---

# Add:

--skip-if-no-lifecycle
export of existing lifecycle rules before removal
safer confirmation prompt before bulk delete

Yes — those are good safety additions for a bulk lifecycle-change script. AWS documents that `get_bucket_lifecycle_configuration` returns a `NoSuchLifecycleConfiguration` error when no lifecycle configuration exists, and `delete_bucket_lifecycle` removes all lifecycle rules from the bucket.[^5_1][^5_2]

## What’s added

This version adds:

- `--skip-if-no-lifecycle` to skip buckets that do not currently have lifecycle rules during `remove` or `both`, using the documented `NoSuchLifecycleConfiguration` condition.[^5_1]
- Export of current lifecycle rules before deletion into timestamped JSON files, so you have a per-bucket backup of the existing `LifecycleConfiguration`.[^5_3]
- A safer confirmation prompt for destructive bulk operations, requiring the user to type an exact confirmation string unless `--yes` is supplied. Exact typed confirmation is a common and safer CLI pattern for destructive actions.[^5_4][^5_5]


## Updated script

```python
#!/usr/bin/env python3

import argparse
import fnmatch
import json
import os
import re
import sys
from datetime import datetime

import boto3
from botocore.exceptions import ClientError


def parse_args():
    parser = argparse.ArgumentParser(
        description="Remove and/or apply S3 lifecycle policies to buckets in a region."
    )
    parser.add_argument(
        "--region",
        required=True,
        help="Target AWS region for bucket selection, for example ap-south-1",
    )
    parser.add_argument(
        "--bucket-patterns",
        nargs="+",
        default=["*"],
        help='One or more shell-style bucket name patterns, for example "prod-*" "*-logs" "data-*"',
    )
    parser.add_argument(
        "--mode",
        choices=["remove", "add", "both"],
        required=True,
        help="Operation mode: remove existing lifecycle policy, add new one, or do both",
    )
    parser.add_argument(
        "--policy-file",
        help="Path to a JSON file containing the LifecycleConfiguration payload",
    )
    parser.add_argument(
        "--policy-json",
        help='Inline JSON string containing the LifecycleConfiguration payload',
    )
    parser.add_argument(
        "--expected-bucket-owner",
        default=None,
        help="Optional 12-digit AWS account ID for safety",
    )
    parser.add_argument(
        "--skip-if-no-lifecycle",
        action="store_true",
        help="Skip buckets that do not currently have a lifecycle configuration for remove/both mode",
    )
    parser.add_argument(
        "--export-dir",
        default="lifecycle-backups",
        help="Directory where existing lifecycle configurations are exported before removal",
    )
    parser.add_argument(
        "--no-export-before-remove",
        action="store_true",
        help="Disable export of existing lifecycle configuration before removal",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip interactive confirmation prompt",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show matching buckets and intended actions without making changes",
    )
    return parser.parse_args()


def bucket_matches_patterns(bucket_name, patterns):
    return any(fnmatch.fnmatch(bucket_name, pattern) for pattern in patterns)


def get_bucket_region(s3_client, bucket_name, expected_owner=None):
    params = {"Bucket": bucket_name}
    if expected_owner:
        params["ExpectedBucketOwner"] = expected_owner

    response = s3_client.get_bucket_location(**params)
    location = response.get("LocationConstraint")

    if location is None:
        return "us-east-1"
    if location == "EU":
        return "eu-west-1"
    return location


def load_policy(args):
    if args.mode in ("add", "both"):
        if bool(args.policy_file) == bool(args.policy_json):
            raise ValueError("For mode add/both, provide exactly one of --policy-file or --policy-json")

        if args.policy_file:
            with open(args.policy_file, "r", encoding="utf-8") as f:
                policy = json.load(f)
        else:
            policy = json.loads(args.policy_json)

        return policy

    return None


def validate_lifecycle_policy(policy):
    if not isinstance(policy, dict):
        raise ValueError("Lifecycle policy must be a JSON object")

    if "Rules" not in policy:
        raise ValueError("Lifecycle policy must contain 'Rules'")

    rules = policy["Rules"]
    if not isinstance(rules, list) or not rules:
        raise ValueError("'Rules' must be a non-empty list")

    if len(rules) > 1000:
        raise ValueError("S3 lifecycle configuration supports up to 1000 rules per bucket")

    for idx, rule in enumerate(rules, start=1):
        if not isinstance(rule, dict):
            raise ValueError(f"Rule #{idx} must be an object")

        if "Status" not in rule:
            raise ValueError(f"Rule #{idx} missing required field: Status")

        if rule["Status"] not in ("Enabled", "Disabled"):
            raise ValueError(f"Rule #{idx} Status must be Enabled or Disabled")

        has_filter = "Filter" in rule
        has_prefix = "Prefix" in rule

        if has_filter and has_prefix:
            raise ValueError(f"Rule #{idx} cannot contain both Prefix and Filter")

        actions = [
            "Transitions",
            "Expiration",
            "NoncurrentVersionTransitions",
            "NoncurrentVersionExpiration",
            "AbortIncompleteMultipartUpload",
            "ExpiredObjectDeleteMarker",
        ]
        if not any(action in rule for action in actions):
            raise ValueError(f"Rule #{idx} must define at least one lifecycle action")

    return True


def get_lifecycle_policy(s3_client, bucket_name, expected_owner=None):
    params = {"Bucket": bucket_name}
    if expected_owner:
        params["ExpectedBucketOwner"] = expected_owner

    try:
        return s3_client.get_bucket_lifecycle_configuration(**params)
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code")
        if error_code == "NoSuchLifecycleConfiguration":
            return None
        raise


def remove_lifecycle_policy(s3_client, bucket_name, expected_owner=None):
    params = {"Bucket": bucket_name}
    if expected_owner:
        params["ExpectedBucketOwner"] = expected_owner

    s3_client.delete_bucket_lifecycle(**params)


def add_lifecycle_policy(s3_client, bucket_name, policy, expected_owner=None):
    params = {
        "Bucket": bucket_name,
        "LifecycleConfiguration": policy,
    }
    if expected_owner:
        params["ExpectedBucketOwner"] = expected_owner

    s3_client.put_bucket_lifecycle_configuration(**params)


def sanitize_filename(name):
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


def export_lifecycle_policy(export_dir, bucket_name, policy):
    os.makedirs(export_dir, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    filename = f"{sanitize_filename(bucket_name)}-lifecycle-{timestamp}.json"
    filepath = os.path.join(export_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(policy, f, indent=2)

    return filepath


def confirm_bulk_action(args, matched_buckets):
    destructive = args.mode in ("remove", "both")
    if not destructive or args.dry_run or args.yes:
        return

    print("\nWARNING: You are about to perform lifecycle policy changes on multiple buckets.")
    print(f"Mode: {args.mode}")
    print(f"Region: {args.region}")
    print(f"Matched bucket count: {len(matched_buckets)}")
    print("Buckets:")
    for bucket_name in matched_buckets:
        print(f"  - {bucket_name}")

    confirmation_text = f"delete-lifecycle-{args.region}-{len(matched_buckets)}"
    print("\nTo continue, type the exact confirmation text below:")
    print(confirmation_text)

    user_input = input("> ").strip()
    if user_input != confirmation_text:
        print("Confirmation failed. Aborting.")
        sys.exit(3)


def main():
    args = parse_args()

    try:
        policy = load_policy(args)
        if policy is not None:
            validate_lifecycle_policy(policy)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"Policy error: {exc}", file=sys.stderr)
        sys.exit(2)

    s3 = boto3.client("s3")

    try:
        buckets = s3.list_buckets()["Buckets"]
    except ClientError as exc:
        print(f"Failed to list buckets: {exc}", file=sys.stderr)
        sys.exit(1)

    matched_buckets = []
    skipped_buckets = []

    for bucket in buckets:
        bucket_name = bucket["Name"]

        if not bucket_matches_patterns(bucket_name, args.bucket_patterns):
            continue

        try:
            bucket_region = get_bucket_region(
                s3, bucket_name, expected_owner=args.expected_bucket_owner
            )
        except ClientError as exc:
            skipped_buckets.append((bucket_name, f"region lookup failed: {exc}"))
            continue

        if bucket_region != args.region:
            continue

        matched_buckets.append(bucket_name)

    if not matched_buckets:
        print("No buckets matched the given criteria.")
        if skipped_buckets:
            print("\nSkipped buckets:")
            for name, reason in skipped_buckets:
                print(f"  - {name}: {reason}")
        return

    print("Bucket patterns:", ", ".join(args.bucket_patterns))
    print("Mode:", args.mode)
    print("Matched buckets:")
    for bucket_name in matched_buckets:
        print(f"  - {bucket_name}")

    if policy is not None:
        print("\nValidated lifecycle policy:")
        print(json.dumps(policy, indent=2))

    if args.dry_run:
        print("\nDry run enabled. No changes were made.")
        return

    confirm_bulk_action(args, matched_buckets)

    removed = []
    added = []
    skipped_no_lifecycle = []
    exported_files = []
    failed = []

    for bucket_name in matched_buckets:
        try:
            existing_policy = None
            if args.mode in ("remove", "both"):
                existing_policy = get_lifecycle_policy(
                    s3_client=s3,
                    bucket_name=bucket_name,
                    expected_owner=args.expected_bucket_owner,
                )

                if existing_policy is None and args.skip_if_no_lifecycle:
                    skipped_no_lifecycle.append(bucket_name)
                    print(f"[SKIPPED:NO_LIFECYCLE] {bucket_name}")
                    continue

                if existing_policy is not None and not args.no_export_before_remove:
                    export_path = export_lifecycle_policy(
                        export_dir=args.export_dir,
                        bucket_name=bucket_name,
                        policy=existing_policy,
                    )
                    exported_files.append(export_path)
                    print(f"[EXPORTED] {bucket_name} -> {export_path}")

                if existing_policy is not None:
                    remove_lifecycle_policy(
                        s3_client=s3,
                        bucket_name=bucket_name,
                        expected_owner=args.expected_bucket_owner,
                    )
                    removed.append(bucket_name)
                    print(f"[REMOVED] {bucket_name}")
                else:
                    print(f"[NO_LIFECYCLE] {bucket_name}")

            if args.mode in ("add", "both"):
                add_lifecycle_policy(
                    s3_client=s3,
                    bucket_name=bucket_name,
                    policy=policy,
                    expected_owner=args.expected_bucket_owner,
                )
                added.append(bucket_name)
                print(f"[ADDED] {bucket_name}")

        except ClientError as exc:
            failed.append((bucket_name, str(exc)))
            print(f"[FAILED] {bucket_name}: {exc}")

    print("\nCompleted.")
    print(f"Removed: {len(removed)}")
    print(f"Added: {len(added)}")
    print(f"Skipped (no lifecycle): {len(skipped_no_lifecycle)}")
    print(f"Exported backups: {len(exported_files)}")
    print(f"Failed: {len(failed)}")

    if exported_files:
        print("\nExported backup files:")
        for path in exported_files:
            print(f"  - {path}")

    if failed:
        print("\nFailures:")
        for bucket_name, error in failed:
            print(f"  - {bucket_name}: {error}")

    if skipped_buckets:
        print("\nSkipped during discovery:")
        for bucket_name, reason in skipped_buckets:
            print(f"  - {bucket_name}: {reason}")


if __name__ == "__main__":
    main()
```


## New parameters

These parameters make the removal workflow safer and more auditable. `NoSuchLifecycleConfiguration` is the documented signal that a bucket has no lifecycle configuration, so `--skip-if-no-lifecycle` can safely bypass those buckets instead of treating that state as an error.[^5_1]

- `--skip-if-no-lifecycle` — skip buckets with no existing lifecycle config during remove/both.
- `--export-dir lifecycle-backups` — directory to store exported lifecycle JSON backups before removal.
- `--no-export-before-remove` — disable backup export if you explicitly do not want it.
- `--yes` — bypass interactive confirmation.
- `--dry-run` — preview only.


## Example usage

Remove only, skip buckets without lifecycle, export backups, and require confirmation:[^5_2][^5_1]

```bash
python s3_lifecycle_bulk.py \
  --region ap-south-1 \
  --bucket-patterns "prod-*" "*-logs" \
  --mode remove \
  --skip-if-no-lifecycle \
  --export-dir lifecycle-backups
```

Remove and add new lifecycle config, with backups:[^5_6][^5_2]

```bash
python s3_lifecycle_bulk.py \
  --region ap-south-1 \
  --bucket-patterns "prod-*" "*-logs" \
  --mode both \
  --policy-file lifecycle-policy.json \
  --skip-if-no-lifecycle \
  --export-dir lifecycle-backups
```

Bypass confirmation in automation:[^5_4]

```bash
python s3_lifecycle_bulk.py \
  --region ap-south-1 \
  --bucket-patterns "prod-*" \
  --mode both \
  --policy-file lifecycle-policy.json \
  --skip-if-no-lifecycle \
  --yes
```


## One important behavior note

In the current logic, `--skip-if-no-lifecycle` skips the whole bucket in `both` mode if there is no existing lifecycle configuration, which means it will also skip adding the new policy to that bucket. That is a reasonable interpretation of “skip if no lifecycle,” but if you want a different behavior — for example, “skip removal but still add the new policy” — I can adjust that.[^5_6][^5_1]

## Better default

If your real intent is:

- remove old lifecycle config when it exists,
- but still add the new policy even when no lifecycle config exists,

then I recommend changing the `both` behavior slightly. That would usually be more practical for rollout jobs, because `put_bucket_lifecycle_configuration` can create or replace the lifecycle configuration directly.[^5_6]

If you want, I can give you that refined version next:

- `--skip-remove-if-no-lifecycle` instead of `--skip-if-no-lifecycle`,
- summary CSV/JSON report,
- and rollback helper using the exported backups.
<span style="display:none">[^5_10][^5_11][^5_12][^5_13][^5_14][^5_15][^5_16][^5_7][^5_8][^5_9]</span>

<div align="center">⁂</div>

[^5_1]: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3/client/get_bucket_lifecycle_configuration.html

[^5_2]: https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/delete_bucket_lifecycle.html

[^5_3]: https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/get_bucket_lifecycle_configuration.html

[^5_4]: https://gist.github.com/garrettdreyfus/8153571

[^5_5]: https://stackoverflow.com/questions/54380613/add-yes-no-confirmation-in-python-3-x

[^5_6]: https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/put_bucket_lifecycle_configuration.html

[^5_7]: https://stackoverflow.com/questions/55061007/how-to-check-if-a-bucket-has-lifecycle-configuration-set-using-boto3

[^5_8]: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3control/client/get_bucket_lifecycle_configuration.html

[^5_9]: https://hackmd.io/@Geeksforgeekscyril/r1qaUCImp

[^5_10]: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3/client/delete_bucket_lifecycle.html

[^5_11]: https://gist.github.com/gurunars/4470c97c916e7b3c4731469c69671d06

[^5_12]: https://ibm.github.io/ibm-cos-sdk-python-core/reference/services/s3/client/get_bucket_lifecycle_configuration.html

[^5_13]: https://www.tutorialspoint.com/article/how-to-get-the-lifecycle-of-a-s3-bucket-using-boto3-and-aws-client

[^5_14]: https://servicedesk.surf.nl/wiki/spaces/WIKI/pages/112592348/Object+Store+S3+Life+Cycle+Policies

[^5_15]: https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/get_bucket_lifecycle.html

[^5_16]: https://boto3.amazonaws.com/v1/documentation/api/1.35.1/reference/services/s3/client/delete_bucket_lifecycle.html


---

# I would prefer just the refined script without the rollback helper

Here’s the refined script only: it adds `--skip-remove-if-no-lifecycle`, exports existing lifecycle configs before removal, and requires a safer confirmation prompt for destructive bulk operations unless `--yes` is passed. AWS documents that `get_bucket_lifecycle_configuration` returns `NoSuchLifecycleConfiguration` when no lifecycle config exists, `delete_bucket_lifecycle` removes all lifecycle rules, and `put_bucket_lifecycle_configuration` creates or replaces the lifecycle configuration.[^6_1][^6_2][^6_3]

## Script

```python
#!/usr/bin/env python3

import argparse
import fnmatch
import json
import os
import re
import sys
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError


def parse_args():
    parser = argparse.ArgumentParser(
        description="Bulk remove and/or apply S3 lifecycle policies to buckets in a region."
    )
    parser.add_argument(
        "--region",
        required=True,
        help="Target AWS region for bucket selection, for example ap-south-1",
    )
    parser.add_argument(
        "--bucket-patterns",
        nargs="+",
        default=["*"],
        help='One or more shell-style bucket name patterns, for example "prod-*" "*-logs" "data-*"',
    )
    parser.add_argument(
        "--mode",
        choices=["remove", "add", "both"],
        required=True,
        help="Operation mode: remove existing lifecycle policy, add new one, or do both",
    )
    parser.add_argument(
        "--policy-file",
        help="Path to a JSON file containing the LifecycleConfiguration payload",
    )
    parser.add_argument(
        "--policy-json",
        help='Inline JSON string containing the LifecycleConfiguration payload',
    )
    parser.add_argument(
        "--expected-bucket-owner",
        default=None,
        help="Optional 12-digit AWS account ID for safety",
    )
    parser.add_argument(
        "--skip-remove-if-no-lifecycle",
        action="store_true",
        help="In remove/both mode, skip only the removal step if no lifecycle configuration exists; add still proceeds in both mode",
    )
    parser.add_argument(
        "--export-dir",
        default="lifecycle-backups",
        help="Directory where existing lifecycle configurations are exported before removal",
    )
    parser.add_argument(
        "--no-export-before-remove",
        action="store_true",
        help="Disable export of existing lifecycle configuration before removal",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip interactive confirmation prompt",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show matching buckets and intended actions without making changes",
    )
    return parser.parse_args()


def bucket_matches_patterns(bucket_name, patterns):
    return any(fnmatch.fnmatch(bucket_name, pattern) for pattern in patterns)


def get_bucket_region(s3_client, bucket_name, expected_owner=None):
    params = {"Bucket": bucket_name}
    if expected_owner:
        params["ExpectedBucketOwner"] = expected_owner

    response = s3_client.get_bucket_location(**params)
    location = response.get("LocationConstraint")

    if location is None:
        return "us-east-1"
    if location == "EU":
        return "eu-west-1"
    return location


def load_policy(args):
    if args.mode in ("add", "both"):
        if bool(args.policy_file) == bool(args.policy_json):
            raise ValueError("For mode add/both, provide exactly one of --policy-file or --policy-json")

        if args.policy_file:
            with open(args.policy_file, "r", encoding="utf-8") as f:
                policy = json.load(f)
        else:
            policy = json.loads(args.policy_json)

        return policy

    return None


def validate_lifecycle_policy(policy):
    if not isinstance(policy, dict):
        raise ValueError("Lifecycle policy must be a JSON object")

    if "Rules" not in policy:
        raise ValueError("Lifecycle policy must contain 'Rules'")

    rules = policy["Rules"]
    if not isinstance(rules, list) or not rules:
        raise ValueError("'Rules' must be a non-empty list")

    if len(rules) > 1000:
        raise ValueError("S3 lifecycle configuration supports up to 1000 rules per bucket")

    for idx, rule in enumerate(rules, start=1):
        if not isinstance(rule, dict):
            raise ValueError(f"Rule #{idx} must be an object")

        if "Status" not in rule:
            raise ValueError(f"Rule #{idx} missing required field: Status")

        if rule["Status"] not in ("Enabled", "Disabled"):
            raise ValueError(f"Rule #{idx} Status must be Enabled or Disabled")

        if "Filter" in rule and "Prefix" in rule:
            raise ValueError(f"Rule #{idx} cannot contain both Prefix and Filter")

        actions = [
            "Transitions",
            "Expiration",
            "NoncurrentVersionTransitions",
            "NoncurrentVersionExpiration",
            "AbortIncompleteMultipartUpload",
        ]
        if not any(action in rule for action in actions):
            raise ValueError(f"Rule #{idx} must define at least one lifecycle action")


def get_lifecycle_policy(s3_client, bucket_name, expected_owner=None):
    params = {"Bucket": bucket_name}
    if expected_owner:
        params["ExpectedBucketOwner"] = expected_owner

    try:
        return s3_client.get_bucket_lifecycle_configuration(**params)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code == "NoSuchLifecycleConfiguration":
            return None
        raise


def remove_lifecycle_policy(s3_client, bucket_name, expected_owner=None):
    params = {"Bucket": bucket_name}
    if expected_owner:
        params["ExpectedBucketOwner"] = expected_owner
    s3_client.delete_bucket_lifecycle(**params)


def add_lifecycle_policy(s3_client, bucket_name, policy, expected_owner=None):
    params = {"Bucket": bucket_name, "LifecycleConfiguration": policy}
    if expected_owner:
        params["ExpectedBucketOwner"] = expected_owner
    s3_client.put_bucket_lifecycle_configuration(**params)


def sanitize_filename(name):
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


def export_lifecycle_policy(export_dir, bucket_name, policy):
    os.makedirs(export_dir, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(
        export_dir,
        f"{sanitize_filename(bucket_name)}-lifecycle-{timestamp}.json",
    )
    with open(path, "w", encoding="utf-8") as f:
        json.dump(policy, f, indent=2)
    return path


def confirm_bulk_action(args, buckets):
    destructive = args.mode in ("remove", "both")
    if not destructive or args.dry_run or args.yes:
        return

    print("\nWARNING: This operation will modify lifecycle policies in bulk.")
    print(f"Mode: {args.mode}")
    print(f"Region: {args.region}")
    print(f"Matched buckets: {len(buckets)}")
    print("Buckets:")
    for bucket in buckets:
        print(f"  - {bucket}")

    token = f"confirm-{args.mode}-{args.region}-{len(buckets)}"
    print("\nTo continue, type the exact confirmation text:")
    print(token)
    entered = input("> ").strip()

    if entered != token:
        print("Confirmation failed. Aborting.")
        sys.exit(3)


def main():
    args = parse_args()

    try:
        policy = load_policy(args)
        if policy is not None:
            validate_lifecycle_policy(policy)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"Policy error: {exc}", file=sys.stderr)
        sys.exit(2)

    s3 = boto3.client("s3")

    try:
        buckets = s3.list_buckets()["Buckets"]
    except ClientError as exc:
        print(f"Failed to list buckets: {exc}", file=sys.stderr)
        sys.exit(1)

    matched_buckets = []
    skipped_buckets = []

    for bucket in buckets:
        bucket_name = bucket["Name"]

        if not bucket_matches_patterns(bucket_name, args.bucket_patterns):
            continue

        try:
            bucket_region = get_bucket_region(
                s3,
                bucket_name,
                expected_owner=args.expected_bucket_owner,
            )
        except ClientError as exc:
            skipped_buckets.append((bucket_name, f"region lookup failed: {exc}"))
            continue

        if bucket_region != args.region:
            continue

        matched_buckets.append(bucket_name)

    if not matched_buckets:
        print("No buckets matched the given criteria.")
        if skipped_buckets:
            print("\nSkipped buckets:")
            for name, reason in skipped_buckets:
                print(f"  - {name}: {reason}")
        return

    print("Bucket patterns:", ", ".join(args.bucket_patterns))
    print("Mode:", args.mode)
    print("Matched buckets:")
    for bucket_name in matched_buckets:
        print(f"  - {bucket_name}")

    if policy is not None:
        print("\nValidated lifecycle policy:")
        print(json.dumps(policy, indent=2))

    if args.dry_run:
        print("\nDry run enabled. No changes were made.")
        return

    confirm_bulk_action(args, matched_buckets)

    removed = []
    added = []
    skipped_remove_no_lifecycle = []
    exported_files = []
    failed = []

    for bucket_name in matched_buckets:
        try:
            existing_policy = None

            if args.mode in ("remove", "both"):
                existing_policy = get_lifecycle_policy(
                    s3,
                    bucket_name,
                    expected_owner=args.expected_bucket_owner,
                )

                if existing_policy is None:
                    if args.skip_remove_if_no_lifecycle:
                        skipped_remove_no_lifecycle.append(bucket_name)
                        print(f"[SKIP_REMOVE:NO_LIFECYCLE] {bucket_name}")
                    else:
                        print(f"[NO_LIFECYCLE] {bucket_name}")
                else:
                    if not args.no_export_before_remove:
                        export_path = export_lifecycle_policy(
                            args.export_dir,
                            bucket_name,
                            existing_policy,
                        )
                        exported_files.append(export_path)
                        print(f"[EXPORTED] {bucket_name} -> {export_path}")

                    remove_lifecycle_policy(
                        s3,
                        bucket_name,
                        expected_owner=args.expected_bucket_owner,
                    )
                    removed.append(bucket_name)
                    print(f"[REMOVED] {bucket_name}")

            if args.mode in ("add", "both"):
                add_lifecycle_policy(
                    s3,
                    bucket_name,
                    policy,
                    expected_owner=args.expected_bucket_owner,
                )
                added.append(bucket_name)
                print(f"[ADDED] {bucket_name}")

        except ClientError as exc:
            failed.append((bucket_name, str(exc)))
            print(f"[FAILED] {bucket_name}: {exc}")

    print("\nCompleted.")
    print(f"Removed: {len(removed)}")
    print(f"Added: {len(added)}")
    print(f"Skipped remove (no lifecycle): {len(skipped_remove_no_lifecycle)}")
    print(f"Exported backups: {len(exported_files)}")
    print(f"Failed: {len(failed)}")

    if exported_files:
        print("\nExported backup files:")
        for path in exported_files:
            print(f"  - {path}")

    if failed:
        print("\nFailures:")
        for bucket_name, error in failed:
            print(f"  - {bucket_name}: {error}")

    if skipped_buckets:
        print("\nSkipped during discovery:")
        for bucket_name, reason in skipped_buckets:
            print(f"  - {bucket_name}: {reason}")


if __name__ == "__main__":
    main()
```


## Key behavior

With `--skip-remove-if-no-lifecycle` in `both` mode, the script skips only the removal step for buckets that do not already have lifecycle rules, but it still applies the new lifecycle policy afterward. That fits well with AWS behavior because `put_bucket_lifecycle_configuration` replaces an existing lifecycle configuration or creates a new one if none exists.[^6_3][^6_1]

## Example usage

Apply new policy after removing existing one when present, while still adding to buckets that currently have no lifecycle config:[^6_2][^6_1]

```bash
python s3_lifecycle_bulk.py \
  --region ap-south-1 \
  --bucket-patterns "prod-*" "*-logs" \
  --mode both \
  --policy-file lifecycle-policy.json \
  --skip-remove-if-no-lifecycle \
  --export-dir lifecycle-backups
```

Remove only, with backup export and interactive confirmation:[^6_2]

```bash
python s3_lifecycle_bulk.py \
  --region ap-south-1 \
  --bucket-patterns "prod-*" \
  --mode remove \
  --export-dir lifecycle-backups
```

Skip confirmation for automation:[^6_2]

```bash
python s3_lifecycle_bulk.py \
  --region ap-south-1 \
  --bucket-patterns "prod-*" \
  --mode both \
  --policy-file lifecycle-policy.json \
  --skip-remove-if-no-lifecycle \
  --yes
```

If you want, I can also tighten this one more step by adding `--include-buckets-file` and `--exclude-buckets-file` for explicit allow/deny control in bulk runs.
<span style="display:none">[^6_10][^6_11][^6_12][^6_13][^6_14][^6_15][^6_4][^6_5][^6_6][^6_7][^6_8][^6_9]</span>

<div align="center">⁂</div>

[^6_1]: https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/put_bucket_lifecycle_configuration.html

[^6_2]: https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/delete_bucket_lifecycle.html

[^6_3]: https://stackoverflow.com/questions/55061007/how-to-check-if-a-bucket-has-lifecycle-configuration-set-using-boto3

[^6_4]: https://boto3.amazonaws.com/v1/documentation/api/1.35.6/reference/services/s3/client/put_bucket_lifecycle.html

[^6_5]: https://stackoverflow.com/questions/66357302/s3-bucket-lifecycle-configuration-with-boto3-lambda-function-and-getting-malform

[^6_6]: https://boto3.amazonaws.com/v1/documentation/api/1.26.116/reference/services/s3/client/put_bucket_lifecycle.html

[^6_7]: https://docs.aws.amazon.com/boto3/latest/reference/services/s3control/client/put_bucket_lifecycle_configuration.html

[^6_8]: https://hackmd.io/@Geeksforgeekscyril/r1qaUCImp

[^6_9]: https://github.com/boto/boto3/issues/2718

[^6_10]: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3/client/delete_bucket_lifecycle.html

[^6_11]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/lifecycle-configuration-examples.html

[^6_12]: https://www.tutorialspoint.com/article/how-to-get-the-lifecycle-of-a-s3-bucket-using-boto3-and-aws-client

[^6_13]: https://stackoverflow.com/questions/63510950/how-to-delete-s3-life-cycle-rule-using-boto3

[^6_14]: https://search.opentofu.org/provider/hashicorp/aws/latest/docs/resources/s3_bucket_lifecycle_configuration

[^6_15]: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3control/client/get_bucket_lifecycle_configuration.html


---

# Add option to exclude the bucket pattern.

Yes — add an `--exclude-bucket-patterns` parameter and filter buckets so they must match at least one include pattern and match none of the exclude patterns. Python’s `fnmatch` is designed for shell-style wildcard matching, and exclusion logic is typically implemented as “include if any include matches and no exclude matches.”[^7_1][^7_2]

## Updated parts

Add this argument:[^7_1]

```python
parser.add_argument(
    "--exclude-bucket-patterns",
    nargs="+",
    default=[],
    help='Optional shell-style bucket name patterns to exclude, for example "*-tmp" "*-backup"',
)
```

Add this helper:[^7_2][^7_1]

```python
def bucket_selected(bucket_name, include_patterns, exclude_patterns):
    included = any(fnmatch.fnmatch(bucket_name, pattern) for pattern in include_patterns)
    excluded = any(fnmatch.fnmatch(bucket_name, pattern) for pattern in exclude_patterns)
    return included and not excluded
```

Then replace the include-only check with:[^7_1]

```python
if not bucket_selected(bucket_name, args.bucket_patterns, args.exclude_bucket_patterns):
    continue
```


## Refined script with exclude support

AWS documents that `put_bucket_lifecycle_configuration` replaces the lifecycle configuration, while `delete_bucket_lifecycle` removes all lifecycle rules from a bucket, so this script still supports remove, add, or both.[^7_3][^7_4]

```python
#!/usr/bin/env python3

import argparse
import fnmatch
import json
import os
import re
import sys
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError


def parse_args():
    parser = argparse.ArgumentParser(
        description="Bulk remove and/or apply S3 lifecycle policies to buckets in a region."
    )
    parser.add_argument(
        "--region",
        required=True,
        help="Target AWS region for bucket selection, for example ap-south-1",
    )
    parser.add_argument(
        "--bucket-patterns",
        nargs="+",
        default=["*"],
        help='One or more shell-style bucket name patterns to include, for example "prod-*" "*-logs" "data-*"',
    )
    parser.add_argument(
        "--exclude-bucket-patterns",
        nargs="+",
        default=[],
        help='Optional shell-style bucket name patterns to exclude, for example "*-tmp" "*-backup"',
    )
    parser.add_argument(
        "--mode",
        choices=["remove", "add", "both"],
        required=True,
        help="Operation mode: remove existing lifecycle policy, add new one, or do both",
    )
    parser.add_argument(
        "--policy-file",
        help="Path to a JSON file containing the LifecycleConfiguration payload",
    )
    parser.add_argument(
        "--policy-json",
        help='Inline JSON string containing the LifecycleConfiguration payload',
    )
    parser.add_argument(
        "--expected-bucket-owner",
        default=None,
        help="Optional 12-digit AWS account ID for safety",
    )
    parser.add_argument(
        "--skip-remove-if-no-lifecycle",
        action="store_true",
        help="In remove/both mode, skip only the removal step if no lifecycle configuration exists; add still proceeds in both mode",
    )
    parser.add_argument(
        "--export-dir",
        default="lifecycle-backups",
        help="Directory where existing lifecycle configurations are exported before removal",
    )
    parser.add_argument(
        "--no-export-before-remove",
        action="store_true",
        help="Disable export of existing lifecycle configuration before removal",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip interactive confirmation prompt",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show matching buckets and intended actions without making changes",
    )
    return parser.parse_args()


def bucket_selected(bucket_name, include_patterns, exclude_patterns):
    included = any(fnmatch.fnmatch(bucket_name, pattern) for pattern in include_patterns)
    excluded = any(fnmatch.fnmatch(bucket_name, pattern) for pattern in exclude_patterns)
    return included and not excluded


def get_bucket_region(s3_client, bucket_name, expected_owner=None):
    params = {"Bucket": bucket_name}
    if expected_owner:
        params["ExpectedBucketOwner"] = expected_owner

    response = s3_client.get_bucket_location(**params)
    location = response.get("LocationConstraint")

    if location is None:
        return "us-east-1"
    if location == "EU":
        return "eu-west-1"
    return location


def load_policy(args):
    if args.mode in ("add", "both"):
        if bool(args.policy_file) == bool(args.policy_json):
            raise ValueError("For mode add/both, provide exactly one of --policy-file or --policy-json")

        if args.policy_file:
            with open(args.policy_file, "r", encoding="utf-8") as f:
                policy = json.load(f)
        else:
            policy = json.loads(args.policy_json)

        return policy

    return None


def validate_lifecycle_policy(policy):
    if not isinstance(policy, dict):
        raise ValueError("Lifecycle policy must be a JSON object")

    if "Rules" not in policy:
        raise ValueError("Lifecycle policy must contain 'Rules'")

    rules = policy["Rules"]
    if not isinstance(rules, list) or not rules:
        raise ValueError("'Rules' must be a non-empty list")

    if len(rules) > 1000:
        raise ValueError("S3 lifecycle configuration supports up to 1000 rules per bucket")

    for idx, rule in enumerate(rules, start=1):
        if not isinstance(rule, dict):
            raise ValueError(f"Rule #{idx} must be an object")

        if "Status" not in rule:
            raise ValueError(f"Rule #{idx} missing required field: Status")

        if rule["Status"] not in ("Enabled", "Disabled"):
            raise ValueError(f"Rule #{idx} Status must be Enabled or Disabled")

        if "Filter" in rule and "Prefix" in rule:
            raise ValueError(f"Rule #{idx} cannot contain both Prefix and Filter")

        actions = [
            "Transitions",
            "Expiration",
            "NoncurrentVersionTransitions",
            "NoncurrentVersionExpiration",
            "AbortIncompleteMultipartUpload",
        ]
        if not any(action in rule for action in actions):
            raise ValueError(f"Rule #{idx} must define at least one lifecycle action")


def get_lifecycle_policy(s3_client, bucket_name, expected_owner=None):
    params = {"Bucket": bucket_name}
    if expected_owner:
        params["ExpectedBucketOwner"] = expected_owner

    try:
        return s3_client.get_bucket_lifecycle_configuration(**params)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code == "NoSuchLifecycleConfiguration":
            return None
        raise


def remove_lifecycle_policy(s3_client, bucket_name, expected_owner=None):
    params = {"Bucket": bucket_name}
    if expected_owner:
        params["ExpectedBucketOwner"] = expected_owner
    s3_client.delete_bucket_lifecycle(**params)


def add_lifecycle_policy(s3_client, bucket_name, policy, expected_owner=None):
    params = {"Bucket": bucket_name, "LifecycleConfiguration": policy}
    if expected_owner:
        params["ExpectedBucketOwner"] = expected_owner
    s3_client.put_bucket_lifecycle_configuration(**params)


def sanitize_filename(name):
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


def export_lifecycle_policy(export_dir, bucket_name, policy):
    os.makedirs(export_dir, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(
        export_dir,
        f"{sanitize_filename(bucket_name)}-lifecycle-{timestamp}.json",
    )
    with open(path, "w", encoding="utf-8") as f:
        json.dump(policy, f, indent=2)
    return path


def confirm_bulk_action(args, buckets):
    destructive = args.mode in ("remove", "both")
    if not destructive or args.dry_run or args.yes:
        return

    print("\nWARNING: This operation will modify lifecycle policies in bulk.")
    print(f"Mode: {args.mode}")
    print(f"Region: {args.region}")
    print(f"Matched buckets: {len(buckets)}")
    print("Buckets:")
    for bucket in buckets:
        print(f"  - {bucket}")

    token = f"confirm-{args.mode}-{args.region}-{len(buckets)}"
    print("\nTo continue, type the exact confirmation text:")
    print(token)
    entered = input("> ").strip()

    if entered != token:
        print("Confirmation failed. Aborting.")
        sys.exit(3)


def main():
    args = parse_args()

    try:
        policy = load_policy(args)
        if policy is not None:
            validate_lifecycle_policy(policy)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"Policy error: {exc}", file=sys.stderr)
        sys.exit(2)

    s3 = boto3.client("s3")

    try:
        buckets = s3.list_buckets()["Buckets"]
    except ClientError as exc:
        print(f"Failed to list buckets: {exc}", file=sys.stderr)
        sys.exit(1)

    matched_buckets = []
    skipped_buckets = []

    for bucket in buckets:
        bucket_name = bucket["Name"]

        if not bucket_selected(
            bucket_name,
            args.bucket_patterns,
            args.exclude_bucket_patterns,
        ):
            continue

        try:
            bucket_region = get_bucket_region(
                s3,
                bucket_name,
                expected_owner=args.expected_bucket_owner,
            )
        except ClientError as exc:
            skipped_buckets.append((bucket_name, f"region lookup failed: {exc}"))
            continue

        if bucket_region != args.region:
            continue

        matched_buckets.append(bucket_name)

    if not matched_buckets:
        print("No buckets matched the given criteria.")
        if skipped_buckets:
            print("\nSkipped buckets:")
            for name, reason in skipped_buckets:
                print(f"  - {name}: {reason}")
        return

    print("Include bucket patterns:", ", ".join(args.bucket_patterns))
    print("Exclude bucket patterns:", ", ".join(args.exclude_bucket_patterns) if args.exclude_bucket_patterns else "(none)")
    print("Mode:", args.mode)
    print("Matched buckets:")
    for bucket_name in matched_buckets:
        print(f"  - {bucket_name}")

    if policy is not None:
        print("\nValidated lifecycle policy:")
        print(json.dumps(policy, indent=2))

    if args.dry_run:
        print("\nDry run enabled. No changes were made.")
        return

    confirm_bulk_action(args, matched_buckets)

    removed = []
    added = []
    skipped_remove_no_lifecycle = []
    exported_files = []
    failed = []

    for bucket_name in matched_buckets:
        try:
            existing_policy = None

            if args.mode in ("remove", "both"):
                existing_policy = get_lifecycle_policy(
                    s3,
                    bucket_name,
                    expected_owner=args.expected_bucket_owner,
                )

                if existing_policy is None:
                    if args.skip_remove_if_no_lifecycle:
                        skipped_remove_no_lifecycle.append(bucket_name)
                        print(f"[SKIP_REMOVE:NO_LIFECYCLE] {bucket_name}")
                    else:
                        print(f"[NO_LIFECYCLE] {bucket_name}")
                else:
                    if not args.no_export_before_remove:
                        export_path = export_lifecycle_policy(
                            args.export_dir,
                            bucket_name,
                            existing_policy,
                        )
                        exported_files.append(export_path)
                        print(f"[EXPORTED] {bucket_name} -> {export_path}")

                    remove_lifecycle_policy(
                        s3,
                        bucket_name,
                        expected_owner=args.expected_bucket_owner,
                    )
                    removed.append(bucket_name)
                    print(f"[REMOVED] {bucket_name}")

            if args.mode in ("add", "both"):
                add_lifecycle_policy(
                    s3,
                    bucket_name,
                    policy,
                    expected_owner=args.expected_bucket_owner,
                )
                added.append(bucket_name)
                print(f"[ADDED] {bucket_name}")

        except ClientError as exc:
            failed.append((bucket_name, str(exc)))
            print(f"[FAILED] {bucket_name}: {exc}")

    print("\nCompleted.")
    print(f"Removed: {len(removed)}")
    print(f"Added: {len(added)}")
    print(f"Skipped remove (no lifecycle): {len(skipped_remove_no_lifecycle)}")
    print(f"Exported backups: {len(exported_files)}")
    print(f"Failed: {len(failed)}")

    if exported_files:
        print("\nExported backup files:")
        for path in exported_files:
            print(f"  - {path}")

    if failed:
        print("\nFailures:")
        for bucket_name, error in failed:
            print(f"  - {bucket_name}: {error}")

    if skipped_buckets:
        print("\nSkipped during discovery:")
        for bucket_name, reason in skipped_buckets:
            print(f"  - {bucket_name}: {reason}")


if __name__ == "__main__":
    main()
```


## Example usage

Include `prod-*` and `*-logs`, but exclude temporary and backup buckets:[^7_1]

```bash
python s3_lifecycle_bulk.py \
  --region ap-south-1 \
  --bucket-patterns "prod-*" "*-logs" \
  --exclude-bucket-patterns "*-tmp" "*-backup" \
  --mode both \
  --policy-file lifecycle-policy.json \
  --skip-remove-if-no-lifecycle \
  --export-dir lifecycle-backups
```

Remove only from included buckets except explicitly excluded ones:[^7_4]

```bash
python s3_lifecycle_bulk.py \
  --region ap-south-1 \
  --bucket-patterns "*" \
  --exclude-bucket-patterns "aws-athena-query-results-*" "*-do-not-touch" \
  --mode remove
```

One important detail: the bucket must pass both filters, meaning it must match at least one include pattern and must not match any exclude pattern. That makes exclusion take precedence, which is usually the safest behavior for bulk operations.[^7_2][^7_1]
<span style="display:none">[^7_10][^7_11][^7_12][^7_13][^7_14][^7_15][^7_5][^7_6][^7_7][^7_8][^7_9]</span>

<div align="center">⁂</div>

[^7_1]: https://docs.python.org/3/library/fnmatch.html

[^7_2]: https://facelessuser.github.io/wcmatch/fnmatch/

[^7_3]: https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/put_bucket_lifecycle_configuration.html

[^7_4]: https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/delete_bucket_lifecycle.html

[^7_5]: https://stackoverflow.com/questions/66597569/fnmatch-fnmatch-use-a-pattern-to-exclude-sub-directories

[^7_6]: https://www.w3schools.com/python/ref_module_fnmatch.asp

[^7_7]: https://gist.github.com/abg/7813c54d173e1631219c

[^7_8]: https://www.pythonpool.com/python-fnmatch-library/

[^7_9]: https://stackoverflow.com/questions/70735043/add-multiple-s3-lifecycle-rules-to-s3-bucket-with-boto3

[^7_10]: https://stackoverflow.com/questions/63510950/how-to-delete-s3-life-cycle-rule-using-boto3

[^7_11]: https://www.geeksforgeeks.org/python/fnmatch-unix-filename-pattern-matching-python/

[^7_12]: https://boto3.amazonaws.com/v1/documentation/api/1.40.48/reference/services/s3control/client/put_bucket_lifecycle_configuration.html

[^7_13]: https://www.youtube.com/watch?v=YRRbUwOuGTU

[^7_14]: https://www.cmi.ac.in/~madhavan/courses/prog2-2015/docs/python-3.4.2-docs-html/library/fnmatch.html

[^7_15]: https://docs.aws.amazon.com/boto3/latest/reference/services/s3control/client/put_bucket_lifecycle_configuration.html

