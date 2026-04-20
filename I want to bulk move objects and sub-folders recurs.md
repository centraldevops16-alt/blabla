<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# I want to bulk move objects and sub-folders recursively from a folder in S3 bucket from Glacier to IA, how can i do it?

You can’t “directly” move Glacier objects to IA; you must first **restore** them and then **over‑copy** them with storage class `STANDARD_IA`. For a whole folder with sub‑folders you do this recursively, using either the AWS CLI or an automated script (e.g., boto3).[^1_1][^1_2][^1_3]

Below I’ll show you a simple **CLI‑driven** pattern; if you want to scale to millions of objects, you can adapt it to boto3 + S3 Batch Operations later.[^1_4][^1_5]

***

### 1. Understand the pattern

For each object in Glacier:

1. Restore it (takes minutes to hours depending on Tier).[^1_6][^1_7]
2. Copy it in‑place with `--storage-class STANDARD_IA` (or to a new key) so the restored object becomes IA.[^1_2][^1_3]

Because S3 objects are immutable, “move” is actually:

- `CopyObject` with `StorageClass=STANDARD_IA` (same or new key)
- Optional: delete the old key if you want to effectively move.[^1_8][^1_1]

***

### 2. AWS CLI bulk restore + copy (recursive)

Assume:

- Bucket: `my-bucket`
- Folder: `archived/`
- You want to move all objects under `archived/` from Glacier to `STANDARD_IA`.


#### Step A: Restore all objects in the folder

First, restore all objects under the prefix (you can parallelize multiple `--request-payer` / `--request-tier` if needed).[^1_7][^1_6]

```bash
# Initiate restore for all objects under 'archived/'
aws s3api list-objects-v2 \
  --bucket my-bucket \
  --prefix "archived/" \
  --query "Contents[].Key" \
  --output text \
| while read key; do
    echo "Restoring: $key"
    aws s3api restore-object \
      --bucket my-bucket \
      --key "$key" \
      --restore-request '{"Days": 7, "GlacierJobParameters": {"Tier": "Standard"}}'
  done
```

You’ll need to wait until objects are restored (status visible in `Restore` field of `head-object`).[^1_6][^1_7]

#### Step B: Copy them to STANDARD_IA (same keys)

Once restored, overwrite them with `STANDARD_IA`.[^1_3][^1_2]

```bash
aws s3 cp \
  s3://my-bucket/archived/ \
  s3://my-bucket/archived/ \
  --recursive \
  --storage-class STANDARD_IA \
  --force-glacier-transfer
```

The `--force-glacier-transfer` tells the CLI it’s okay to deal with Glacier objects that are already restored.[^1_9][^1_3]

> If you want to “move” them to a different folder instead of in‑place, change destination key:
> ```bash > aws s3 cp s3://my-bucket/archived/ s3://my-bucket/ia/ \ >   --recursive --storage-class STANDARD_IA --force-glacier-transfer > ```

***

### 3. Boto3 script (for very large numbers)

If you have **hundreds of millions of objects**, you can wrap the same pattern in a Python script with `boto3`.[^1_10][^1_7]

Very simplified sketch:

```python
import boto3

s3 = boto3.client('s3')

bucket = "my-bucket"
prefix = "archived/"
storage_class = "STANDARD_IA"

paginator = s3.get_paginator('list_objects_v2')
for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
    for obj in page.get('Contents', []):
        key = obj['Key']
        print(f"Restoring {key}...")
        s3.restore_object(
            Bucket=bucket,
            Key=key,
            RestoreRequest={'Days': 7, 'GlacierJobParameters': {'Tier': 'Standard'}}
        )

# Later, when all are restored:
# for each object, copy in‑place with STANDARD_IA
for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
    for obj in page.get('Contents', []):
        key = obj['Key']
        print(f"Copying to IA: {key}")
        s3.copy_object(
            Bucket=bucket,
            Key=key,
            CopySource={"Bucket": bucket, "Key": key},
            StorageClass=storage_class
        )
```


***

### 4. For petabyte‑scale or very long‑lived Glacier

If this is **hundreds of TBs or millions of objects**, consider:

- **S3 Batch Operations**:
    - Create an inventory of objects in the Glacier folder.
    - Run a Batch Restore job, then a Batch Copy job to set `STANDARD_IA`.[^1_11][^1_5][^1_4]
- **Costs and timing**:
    - Glacier restore costs and retrieval time depend on retrieval tier (Bulk / Standard / Expedited).[^1_7][^1_6]
    - IA storage is cheaper than Standard but more expensive than Glacier‑class.[^1_12][^1_2]

***

### 5. Practical tips for your use case

- Check current storage class first:

```bash
aws s3api head-object --bucket my-bucket --key "archived/subfolder/file.txt" \
  --query 'StorageClass'
```

- If you have many objects, run restore in batches (e.g., by prefix such as `archived/year=2023/`) to avoid throttling and make cost‑tracking easier.[^1_13][^1_7]
- Avoid deleting the Glacier objects until you’ve confirmed the IA objects exist, unless you’re re‑using the same key (in‑place copy implicitly replaces them).[^1_1][^1_2]

***

If you tell me roughly:

- number of objects,
- total size,
- whether Glacier Flexible or Deep Archive,

I can give you a tailored script (CLI or Python) and estimate cost‑time for the restore+copy.
<span style="display:none">[^1_14][^1_15][^1_16][^1_17][^1_18][^1_19][^1_20][^1_21][^1_22][^1_23][^1_24][^1_25][^1_26][^1_27][^1_28]</span>

<div align="center">⁂</div>

[^1_1]: https://stackoverflow.com/questions/60700194/move-s3-files-with-glacier-storage-class-to-a-different-folder

[^1_2]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/lifecycle-transition-general-considerations.html

[^1_3]: https://gist.github.com/34157927f4b3c4d2cc932de37f1277c4

[^1_4]: https://aws.amazon.com/blogs/storage/copy-objects-between-any-amazon-s3-storage-classes-using-s3-batch-operations/

[^1_5]: https://community.aws/content/2mfKdDVtXo4c3LHswpaelDlPhws/transition-storage-class-with-s3-batch-operations?lang=en

[^1_6]: https://docs.aws.amazon.com/cli/latest/reference/s3api/restore-object.html

[^1_7]: https://oneuptime.com/blog/post/2026-02-12-restore-objects-s3-glacier-deep-archive/view

[^1_8]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/copy-object.html

[^1_9]: https://docs.aws.amazon.com/cli/v1/userguide/cli-services-s3-commands.html

[^1_10]: https://stackoverflow.com/questions/74685252/how-to-restore-objects-from-amazon-glacier-to-standard-tier-permanently-in-a-s3

[^1_11]: https://aws.amazon.com/s3/features/batch-operations/

[^1_12]: https://oneuptime.com/blog/post/2026-02-12-s3-lifecycle-rules-transition-storage-classes/view

[^1_13]: https://www.scribd.com/document/830561111/S3-Deep-Glacier-to-S3-Standard-moving-objects

[^1_14]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/restoring-objects.html

[^1_15]: https://stackoverflow.com/questions/27099615/move-files-between-amazon-s3-to-glacier-and-vice-versa-programmatically-using-ap

[^1_16]: https://www.reddit.com/r/aws/comments/1f321v6/cost_and_time_efficient_way_to_move_large_data/

[^1_17]: https://www.youtube.com/watch?v=eXcQWqCT1h8

[^1_18]: https://github.com/aws-samples/s3-glacier-bulk-retrieval

[^1_19]: https://github.com/cfurst/GlacierThaw

[^1_20]: https://www.reddit.com/r/aws/comments/nvf3kx/moving_and_deleting_s3_objects_in_a_folder_within/

[^1_21]: https://aws.amazon.com/video/watch/1e8c15fb02c/

[^1_22]: https://builder.aws.com/content/2mfKdDVtXo4c3LHswpaelDlPhws/perform-unsupported-s3-storage-class-transitions-with-batch-operations

[^1_23]: https://rcdsdocs.it.northwestern.edu/tutorials/cloud/aws/archiving-data-amazon-S3.html

[^1_24]: https://docs.aws.amazon.com/cli/latest/reference/s3/mv.html

[^1_25]: https://stackoverflow.com/questions/48171851/aws-how-to-archive-files-from-s3-to-glacier-using-only-command-line

[^1_26]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/sc-howtoset.html

[^1_27]: https://www.reddit.com/r/aws/comments/zd3bvw/restore_objects_from_amazon_glacier_to_standard/

[^1_28]: https://www.youtube.com/watch?v=Svm4G-NaJrs

