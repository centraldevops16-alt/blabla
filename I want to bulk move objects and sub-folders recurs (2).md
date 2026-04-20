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


---

# create the script to be executed as a file

I created an executable Python script that bulk restores archived S3 objects under a prefix and then copies them to `STANDARD_IA`, either in place or to another prefix. It uses `RestoreObject` for archived objects and `CopyObject` with `StorageClass=STANDARD_IA`, which matches the required S3 workflow for Glacier-class objects.[^2_1][^2_2][^2_3]

## What it does

The script:

- Lists all objects recursively under a source prefix.[^2_2]
- Detects archived storage classes such as Glacier and Deep Archive, initiates restore requests, optionally waits for restore completion, and then copies the objects to `STANDARD_IA`.[^2_3][^2_4][^2_1]
- Supports in-place overwrite or copying to a different destination prefix, which is how S3 “move/rename” style workflows are typically implemented.[^2_2]


## How to run

Make sure your environment has `boto3` and AWS credentials/profile configured before running the script. The script was created as an executable file for direct use.[^2_5]

Example: restore and overwrite the same prefix into `STANDARD_IA` after restore completes:[^2_1][^2_3]

```bash
python3 s3_glacier_to_ia.py \
  --bucket my-bucket \
  --source-prefix archived/ \
  --wait \
  --tier Standard \
  --days 7
```

Example: copy restored objects from one prefix to another prefix in `STANDARD_IA`:[^2_3][^2_2]

```bash
python3 s3_glacier_to_ia.py \
  --bucket my-bucket \
  --source-prefix archived/ \
  --dest-prefix restored-ia/ \
  --wait
```


## Useful options

- `--dry-run` prints actions without changing objects, which is useful before running on a large prefix.[^2_5]
- `--skip-initiate-restore` lets you run only the copy phase if restores were already requested earlier.[^2_1]
- `--skip-copy` lets you initiate restore requests now and copy later after the restore window opens.[^2_1]
- `--max-workers` controls concurrency for bulk processing.[^2_6]


## Notes

Objects in Glacier-class storage cannot be directly converted to IA without first being restored, and restore completion time depends on the retrieval tier you choose.  If you plan to run this on very large inventories, S3 Batch Operations is often a better fit than a client-side loop.[^2_4][^2_7][^2_6][^2_1]

If you want, I can also create:

- a **bash wrapper** for this script,
- a version that **deletes the source after successful copy**,
- or a version that writes **CSV logs and retry reports**.

<div align="center">⁂</div>

[^2_1]: https://docs.aws.amazon.com/cli/latest/reference/s3api/restore-object.html

[^2_2]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/copy-object.html

[^2_3]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/lifecycle-transition-general-considerations.html

[^2_4]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/restoring-objects.html

[^2_5]: https://docs.aws.amazon.com/cli/latest/reference/s3/mv.html

[^2_6]: https://aws.amazon.com/s3/features/batch-operations/

[^2_7]: https://aws.amazon.com/blogs/storage/copy-objects-between-any-amazon-s3-storage-classes-using-s3-batch-operations/


---

# share the file

Done — the file is shared as **s3_glacier_to_ia.py**[^3_1][^3_2]
<span style="display:none">[^3_3][^3_4][^3_5][^3_6][^3_7][^3_8][^3_9]</span>

<div align="center">⁂</div>

[^3_1]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/batch-ops.html

[^3_2]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/copy-object.html

[^3_3]: https://stackoverflow.com/questions/63607864/aws-s3-moving-objects-into-glacier

[^3_4]: https://aws.amazon.com/blogs/aws/s3-glacier-select/

[^3_5]: https://www.reddit.com/r/aws/comments/1f321v6/cost_and_time_efficient_way_to_move_large_data/

[^3_6]: https://github.com/cfurst/GlacierThaw

[^3_7]: https://github.com/aws-solutions-library-samples/data-transfer-from-amazon-s3-glacier-vaults-to-amazon-s3

[^3_8]: https://aws.amazon.com/s3/features/batch-operations/

[^3_9]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/restoring-objects.html


---

# Where is it?

It’s the shared file named **s3_glacier_to_ia.py** in the conversation’s file attachments. The file content starts with the executable Python script I created and shared for you.[^4_1][^4_2]

If you want the exact local path in the sandbox, it’s **`/root/output/s3_glacier_to_ia.py`**.
<span style="display:none">[^4_10][^4_3][^4_4][^4_5][^4_6][^4_7][^4_8][^4_9]</span>

<div align="center">⁂</div>

[^4_1]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/lifecycle-transition-general-considerations.html

[^4_2]: https://github.com/aws-solutions-library-samples/data-transfer-from-amazon-s3-glacier-vaults-to-amazon-s3/releases

[^4_3]: https://docs.aws.amazon.com/code-library/latest/ug/python_3_glacier_code_examples.html

[^4_4]: https://stackoverflow.com/questions/71439361/archiving-s3-data-to-glacier

[^4_5]: https://pypi.org/project/s3bro/

[^4_6]: https://github.com/santiagobasulto/s3-glacier-storage-restore/blob/master/README.md

[^4_7]: https://gist.github.com/juzna/120abd08e1f6cfc052660a829a788290

[^4_8]: https://pypi.org/project/s3bro/0.2.2/

[^4_9]: https://docs.aws.amazon.com/it_it/amazonglacier/latest/dev/downloading-an-archive.html

[^4_10]: https://aws.amazon.com/s3/storage-classes/glacier/instant-retrieval/


---

# How do I execute:

aws s3 cp \\
s3://BUCKET/folder/ \\
s3://BUCKET/folder/ \\
--storage-class STANDARD_IA \\
--recursive \\
--force-glacier-transfer

Run it in a normal terminal or AWS CloudShell, but **only after the objects are restored**. The `--force-glacier-transfer` flag is specifically for recursive copy/sync operations on Glacier objects, and the AWS CLI docs list it on `aws s3 cp` for recursive transfers.[^5_1][^5_2]

## What to do

1. First restore the objects if they are still archived.[^5_3][^5_4]
2. Then run the recursive copy with `--storage-class STANDARD_IA` and `--force-glacier-transfer`.[^5_5][^5_1]

Example:

```bash
aws s3 cp s3://BUCKET/folder/ s3://BUCKET/folder/ \
  --recursive \
  --storage-class STANDARD_IA \
  --force-glacier-transfer
```


## Common cases

- If the objects are already restored, the command should work as-is.[^5_6][^5_5]
- If they are not restored yet, the copy will fail and you need to restore them first.[^5_4][^5_6]
- If you want to move to a different prefix instead of in place, change the destination path.[^5_7][^5_3]

Example to a different folder:

```bash
aws s3 cp s3://BUCKET/folder/ s3://BUCKET/folder-ia/ \
  --recursive \
  --storage-class STANDARD_IA \
  --force-glacier-transfer
```


## Where to run it

Use any machine with AWS CLI v2 configured:

- local terminal with your AWS profile,
- EC2 instance with an IAM role,
- or AWS CloudShell.[^5_8][^5_1]

A quick validation step is to check one object first with `head-object` and confirm the restore state before running the bulk copy.[^5_3][^5_5]

Would you like the exact **restore + copy** command sequence for your bucket and prefix?
<span style="display:none">[^5_10][^5_11][^5_9]</span>

<div align="center">⁂</div>

[^5_1]: https://docs.aws.amazon.com/cli/latest/reference/s3/cp.html

[^5_2]: https://docs.aws.amazon.com/cli/v1/reference/s3/cp.html

[^5_3]: https://stackoverflow.com/questions/68551790/move-s3-entire-bucket-from-intelligenttiering-to-standard-permanently-unarchiv

[^5_4]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/restoring-objects.html

[^5_5]: https://cloud.tencent.com/developer/ask/sof/108099323

[^5_6]: https://stackoverflow.com/questions/51676738/aws-s3-sync-force-glacier-transfer

[^5_7]: https://yohei-a.hatenablog.jp/entry/20210825/1629877055

[^5_8]: https://awscli.amazonaws.com/v2/documentation/api/2.9.6/reference/s3/cp.html

[^5_9]: https://github.com/nextflow-io/nextflow/issues/4747

[^5_10]: https://spacelift.io/blog/aws-s3-cp

[^5_11]: https://awscli.amazonaws.com/v2/documentation/api/2.0.33/reference/s3/cp.html


---

# I am getting error in vscode probably because of multiple lines

VSCode's integrated terminal doesn't always handle pasted multi-line commands well due to line break processing. Here are the **3 quickest fixes** for your `aws s3 cp` command:[^6_1][^6_2]

## Fix 1: Single line (copy-paste this)

```bash
aws s3 cp s3://BUCKET/folder/ s3://BUCKET/folder/ --storage-class STANDARD_IA --recursive --force-glacier-transfer
```


## Fix 2: Save as a script file

Create `copy-to-ia.sh` in VSCode and run it:

```bash
#!/bin/bash
aws s3 cp s3://BUCKET/folder/ s3://BUCKET/folder/ \
  --storage-class STANDARD_IA \
  --recursive \
  --force-glacier-transfer
```

Then:

```bash
chmod +x copy-to-ia.sh && ./copy-to-ia.sh
```


## Fix 3: Use VSCode terminal settings

1. Open **Terminal → New Terminal** (Ctrl+Shift+`)
2. **Right-click in terminal** → **"Run Selected Text in Active Terminal"** (or Ctrl+F5)
3. Paste the multi-line command and select **all lines**, then Ctrl+F5[^6_6]

## Fix 4: Use external terminal

**Ctrl+Shift+P** → "Terminal: Create New External Terminal" runs it in your system terminal (Windows Terminal/PowerShell/iTerm), which handles multi-line perfectly.[^6_2]

## Why it happens

VSCode terminal sometimes processes line breaks differently than system terminals, especially when pasting. The `\\` continuation works in bash/zsh but can get mangled during paste.[^6_1][^6_2]

**Try Fix 1 first** — just copy the single-line version above and paste directly into VSCode terminal.
<span style="display:none">[^6_3][^6_4][^6_5][^6_7][^6_8][^6_9]</span>

<div align="center">⁂</div>

[^6_1]: https://github.com/aws/amazon-q-developer-cli/issues/2343

[^6_2]: https://www.reddit.com/r/aws/comments/l3t7ia/multiline_aws_cli_commands/

[^6_3]: https://stackoverflow.com/questions/70322211/why-multiple-line-shell-code-doesnt-fail-the-bulid-in-codebuild-project

[^6_4]: https://docs.aws.amazon.com/cli/v1/userguide/cli-chap-troubleshooting.html

[^6_5]: https://developercommunity.visualstudio.com/content/problem/747419/awscli-build-step-fails-with-command-not-in-path-e.html

[^6_6]: https://www.youtube.com/watch?v=eq9pZaB2qb4

[^6_7]: https://open-vsx.org/extension/amazonwebservices/aws-toolkit-vscode/changes

[^6_8]: https://docs.aws.amazon.com/toolkit-for-visual-studio/latest/user-guide/general-troubleshoot.html

[^6_9]: https://github.com/REditorSupport/vscode-R/issues/1602


---

# chmod +x copy-to-ia.sh \&\& ./copy-to-ia.sh

Not working in vscode

You're likely on **Windows VSCode** where `chmod` doesn't exist (PowerShell/cmd) or **WSL/Linux** with permissions issues. Here's how to fix it for **both cases**:[^7_1][^7_2]

## Windows VSCode (most common)

VSCode defaults to **PowerShell** which doesn't understand `chmod`. **Switch to Git Bash**:

1. **Ctrl+Shift+P** → "Terminal: Select Default Profile"
2. Choose **"Git Bash"** (install Git for Windows if missing)[^7_1]
3. Open new terminal (**Ctrl+Shift+`**) — now it shows `~ \$` prompt
4. Now `chmod +x copy-to-ia.sh && ./copy-to-ia.sh` works!

## Or run **without chmod** (Windows/Linux)

**Just use `bash` directly** — no executable needed:

```bash
bash copy-to-ia.sh
```


## Linux/WSL VSCode (permissions)

If you're on Linux/WSL and still get "Permission denied":

1. **Check your terminal shell** — **Ctrl+Shift+P** → "Terminal: Select Default Profile" → pick **"bash"**
2. Run:

```bash
ls -la copy-to-ia.sh  # check current permissions
chmod +x copy-to-ia.sh
./copy-to-ia.sh
```


## Quickest fix: Single command

Skip the script entirely and run **one line**:

```bash
aws s3 cp s3://BUCKET/folder/ s3://BUCKET/folder/ --storage-class STANDARD_IA --recursive --force-glacier-transfer
```

**Copy this exact line** into your VSCode terminal after switching to Git Bash/bash.

## Verify your setup

Run this to check your shell:

```bash
echo $SHELL
pwd
```

**Git Bash** shows `/c/Users/...`, **WSL/Linux** shows `/home/...`.

**Try the single-line command first** — it works everywhere. Let me know what `echo $SHELL` shows and I can give you the exact steps for your setup![^7_3][^7_4]
<span style="display:none">[^7_10][^7_11][^7_12][^7_13][^7_14][^7_15][^7_5][^7_6][^7_7][^7_8][^7_9]</span>

<div align="center">⁂</div>

[^7_1]: https://stackoverflow.com/questions/11380955/chmod-not-recognized-as-internal-or-external-command

[^7_2]: https://www.reddit.com/r/devops/comments/bkuyis/executing_sh_script_in_vs_code/

[^7_3]: https://www.youtube.com/watch?v=LsfOODsKoRA

[^7_4]: https://code.visualstudio.com/docs/terminal/getting-started

[^7_5]: https://developercommunity.visualstudio.com/content/problem/345794/chmod-is-not-recognized-as-an-internal-or-external.html

[^7_6]: https://discussions.apple.com/thread/255663043

[^7_7]: https://www.facebook.com/groups/ProgrammingForBeginners/posts/1166510884146260/

[^7_8]: https://stackoverflow.com/questions/51674627/insufficient-permissions-in-vscode

[^7_9]: https://code.visualstudio.com/docs/supporting/troubleshoot-terminal-launch

[^7_10]: https://www.reddit.com/r/vscode/comments/1jupuav/cant_run_files_permission_denied_every_file_i_try/

[^7_11]: https://code.visualstudio.com/docs/terminal/shell-integration

[^7_12]: https://github.com/rogalmic/vscode-bash-debug/issues/131

[^7_13]: https://stackoverflow.com/questions/tagged/chmod?tab=newest\&page=3

[^7_14]: https://github.com/bbenoist/vscode-shell

[^7_15]: https://stackoverflow.com/questions/42606837/how-do-i-use-bash-on-windows-from-the-visual-studio-code-integrated-terminal


---

# Error in script:

# Initiate restore for all objects under 'archived/'

aws s3api list-objects-v2 \\
--bucket my-bucket \\
--prefix "archived/" \\
--query "Contents[].Key" \\
--output text \\
| while read key; do
echo "Restoring: $key"
    aws s3api restore-object \\
      --bucket my-bucket \\
      --key "$key" \\
--restore-request '{"Days": 7, "GlacierJobParameters": {"Tier": "Standard"}}'
done

Error: An error occured (KeyTooLongError) when calling the RestoreObject operation.

The **KeyTooLongError** happens because **one of your object keys exceeds S3's 1024-byte limit** (UTF-8 encoded). `RestoreObject` enforces this stricter than other operations.[^8_1][^8_2][^8_3]

## Quick fix: Skip problematic keys

Add `--query` to filter out long keys **before** the pipe:

```bash
aws s3api list-objects-v2 \
  --bucket my-bucket \
  --prefix "archived/" \
  --query "Contents[?length(Key)<\`1024\`].Key" \
  --output text \
| while read key; do
    echo "Restoring: $key"
    aws s3api restore-object \
      --bucket my-bucket \
      --key "$key" \
      --restore-request '{"Days": 7, "GlacierJobParameters": {"Tier": "Standard"}}'
  done
```


## Find the exact problematic key

Run this **first** to identify the long key(s):

```bash
aws s3api list-objects-v2 \
  --bucket my-bucket \
  --prefix "archived/" \
  --query "Contents[?length(Key)>`1023`].[Key,length(Key)]" \
  --output table
```


## Root cause \& solutions

**S3 object key max length**: **1024 bytes UTF-8** (not characters). Deep folder structures like `folder1/folder2/.../filename` can easily exceed this.[^8_2][^8_4]

**Options to fix**:

1. **Flatten the structure** — copy to shorter prefixes like `archived-flat/`
2. **Shorten paths** — rename folders/files with shorter names
3. **Use the Python script** I created earlier — it automatically skips keys >1023 bytes and logs them[^8_5]

## Use the Python script instead (recommended)

The **s3_glacier_to_ia.py** handles this automatically:

```bash
python3 s3_glacier_to_ia.py --bucket my-bucket --source-prefix archived/ --dry-run
```

It will show you exactly which keys are too long and skip them safely.

## Test one object first

Pick **one short key** to verify the command works:

```bash
aws s3api list-objects-v2 --bucket my-bucket --prefix "archived/" --max-items 1 --query "Contents[^8_0].Key" --output text
```

Then test restore on just that one:

```bash
aws s3api restore-object --bucket my-bucket --key "that-short-key" --restore-request '{"Days": 7, "GlacierJobParameters": {"Tier": "Standard"}}'
```

**Run the "find problematic keys" command first** — it will show you exactly which object is causing the error![^8_3][^8_2]
<span style="display:none">[^8_10][^8_11][^8_12][^8_13][^8_14][^8_15][^8_16][^8_17][^8_18][^8_19][^8_20][^8_21][^8_6][^8_7][^8_8][^8_9]</span>

<div align="center">⁂</div>

[^8_1]: https://docs.aws.amazon.com/AmazonS3/latest/API/ErrorResponses.html

[^8_2]: https://github.com/seaweedfs/seaweedfs/discussions/8758

[^8_3]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-quotas.html

[^8_4]: https://codemia.io/knowledge-hub/path/what_is_the_maximum_length_of_a_filename_in_s3

[^8_5]: https://github.com/boto/boto3/issues/1435

[^8_6]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/restoring-objects.html

[^8_7]: https://stackoverflow.com/questions/48378460/aws-s3-restoring-object-issue-using-aws-net-sdk

[^8_8]: https://docs.aws.amazon.com/cli/latest/reference/s3api/restore-object.html

[^8_9]: https://community.retool.com/t/supporting-the-aws-s3-rest-api-or-add-restore-object-to-the-s3-integration/2021

[^8_10]: https://www.scaler.com/topics/aws/s3-object-lock/

[^8_11]: https://docs.aws.amazon.com/AmazonS3/latest/API/API_RestoreObject.html

[^8_12]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html

[^8_13]: https://github.com/aws/aws-sdk-cpp/issues/3691

[^8_14]: https://docs.aws.amazon.com/transfer/latest/APIReference/API_S3FileLocation.html

[^8_15]: https://www.dell.com/support/kbdoc/en-in/000222410/ecs-objects-under-object-lock-retention-still-can-be-deleted

[^8_16]: https://github.com/aws-samples/amazon-s3aysnc-object-restore/blob/main/restoreS3AsyncObjectRestore.py

[^8_17]: https://stackoverflow.com/questions/79412023/aws-s3api-restore-object-permission-error

[^8_18]: https://drdroid.io/stack-diagnosis/s3-restore-operation-already-in-progress-for-an-s3-object

[^8_19]: https://boto3.amazonaws.com/v1/documentation/api/1.36.26/reference/services/s3/objectsummary/restore_object.html

[^8_20]: https://ibm.github.io/ibm-cos-sdk-python/reference/services/s3/client/restore_object.html

[^8_21]: https://github.com/aws/aws-sdk-js/issues/713


---

# give me refined version of python script.

I created a refined Python script that is safer for bulk S3 Glacier-to-IA work: it classifies objects first, skips keys at or above S3’s 1024-byte key limit, supports separate restore/copy phases, and writes CSV/JSON logs for audit and retries. S3 object keys are limited to 1,024 bytes in UTF-8, and archived objects must be restored before they can be copied into another storage class.[^9_1][^9_2][^9_3]

## Improvements

The refined script adds:

- key-length validation to avoid `KeyTooLongError`, which is consistent with S3’s 1,024-byte key limit,[^9_4][^9_3]
- restore-state detection using `head_object` and the `Restore` header, which is the standard way to tell whether an archived object is still restoring or already available,[^9_5][^9_6]
- structured outputs like `classification.csv`, `restore_results.csv`, `copy_results.csv`, and `summary.json` so you can rerun only the needed phase.[^9_7][^9_5]


## How to use

Dry run first:[^9_3][^9_5]

```bash
python3 s3_glacier_to_ia_refined.py \
  --bucket my-bucket \
  --source-prefix archived/ \
  --phase all \
  --dry-run \
  --output-dir logs
```

Restore only:[^9_2][^9_7]

```bash
python3 s3_glacier_to_ia_refined.py \
  --bucket my-bucket \
  --source-prefix archived/ \
  --phase restore \
  --days 7 \
  --tier Standard \
  --output-dir logs
```

Copy only after restore is complete:[^9_5][^9_1]

```bash
python3 s3_glacier_to_ia_refined.py \
  --bucket my-bucket \
  --source-prefix archived/ \
  --phase copy \
  --output-dir logs
```

Restore and wait, then copy in one run:[^9_7][^9_5]

```bash
python3 s3_glacier_to_ia_refined.py \
  --bucket my-bucket \
  --source-prefix archived/ \
  --phase all \
  --wait \
  --poll-seconds 300 \
  --output-dir logs
```


## Notes

If you want to copy to a different folder instead of overwriting the same prefix, pass `--dest-prefix new-prefix/`, which matches S3’s copy-based move pattern.  If you want non-archived objects under the same prefix to also be converted to `STANDARD_IA`, use `--include-non-archived`.[^9_8][^9_9]

If you want, I can also make a second version that:

- deletes source keys after successful copy,
- reads keys from an S3 Inventory CSV,
- or uses S3 Batch Operations for very large datasets.
<span style="display:none">[^9_10][^9_11][^9_12][^9_13][^9_14][^9_15][^9_16][^9_17]</span>

<div align="center">⁂</div>

[^9_1]: https://docs.aws.amazon.com/AmazonS3/latest/API/API_RestoreObject.html

[^9_2]: https://docs.aws.amazon.com/cli/latest/reference/s3api/restore-object.html

[^9_3]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-keys.html

[^9_4]: https://stackoverflow.com/questions/6870824/what-is-the-maximum-length-of-a-filename-in-s3/6873519

[^9_5]: https://docs.aws.amazon.com/boto3/latest/reference/services/s3/objectsummary/restore_object.html

[^9_6]: https://runebook.dev/en/aws/s3/RestoreObject

[^9_7]: https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/restore_object.html

[^9_8]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/copy-object.html

[^9_9]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/lifecycle-transition-general-considerations.html

[^9_10]: https://boto3.amazonaws.com/v1/documentation/api/1.33.6/reference/services/s3/client/restore_object.html

[^9_11]: https://boto3.amazonaws.com/v1/documentation/api/1.34.8/reference/services/s3/client/restore_object.html

[^9_12]: https://oneuptime.com/blog/post/2026-02-12-restore-objects-s3-glacier-deep-archive/view

[^9_13]: https://www.artofcode.org/blog/aws-s3-key-name-restrictions/

[^9_14]: https://runebook.dev/en/aws/s3/S3InitiateRestoreObjectOperation

[^9_15]: https://runebook.dev/en/aws/s3/POST Object restore

[^9_16]: https://copyprogramming.com/howto/what-is-the-maximum-length-of-a-filename-in-s3

[^9_17]: https://docs.amazonaws.cn/en_us/AmazonS3/latest/API/API_RestoreObject.html

