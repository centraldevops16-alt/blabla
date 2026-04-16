<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

## Policy 1: 7-Day Retention

This policy retains all objects for exactly 7 days before permanent deletion.

```json
{
  "Rules": [
    {
      "ID": "7DayRetention",
      "Status": "Enabled",
      "Expiration": {
        "Days": 7
      }
    }
  ]
}
```


## Policy 2: Tiered Transitions

This policy keeps objects in Standard storage initially, transitions to STANDARD_IA at 30 days, then to GLACIER_FLEXIBLE_RETRIEVAL at 90 days. Note that AWS requires a minimum 30-day stay in Standard before IA transition.[^1_1][^1_6]

```json
{
  "Rules": [
    {
      "ID": "TieredStorage",
      "Status": "Enabled",
      "Transitions": [
        {
          "Days": 30,
          "StorageClass": "STANDARD_IA"
        },
        {
          "Days": 90,
          "StorageClass": "GLACIER_FLEXIBLE_RETRIEVAL"
        }
      ]
    }
  ]
}
```

Apply these via AWS CLI with `aws s3api put-bucket-lifecycle-configuration` or the S3 console Management tab.[^1_1]
<span style="display:none">[^1_10][^1_11][^1_12][^1_13][^1_14][^1_15][^1_2][^1_3][^1_4][^1_5][^1_7][^1_8][^1_9]</span>

<div align="center">⁂</div>

[^1_1]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/lifecycle-configuration-examples.html

[^1_2]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lifecycle-mgmt.html

[^1_3]: https://www.cloudoptimo.com/blog/s3-lifecycle-policies-optimizing-cloud-storage-in-aws/

[^1_4]: https://docs.cloudera.com/management-console/cloud/environments/topics/mc-logs_lifecycle_management.html

[^1_5]: https://shajam.cloud/aws-s3-lifecycle-policy/

[^1_6]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/lifecycle-transition-general-considerations.html

[^1_7]: https://www.tech-reader.blog/2025/02/s3-glacier-step-by-step-guide-to.html

[^1_8]: https://packetsensei.com/cloud/amazon-aws/s3/amazon-aws-s3-lifecycle-policies/

[^1_9]: https://fornex.com/help/s3-lifecycle-policy/

[^1_10]: https://oneuptime.com/blog/post/2026-02-12-s3-lifecycle-rules-transition-storage-classes/view

[^1_11]: https://docs.amazonaws.cn/en_us/AmazonS3/latest/userguide/lifecycle-configuration-examples.html

[^1_12]: https://help.mspbackups.com/billing-storage/storage-providers/amazon/s3-lifecycle-policies

[^1_13]: https://www.youtube.com/watch?v=HcU-pMycGWg

[^1_14]: https://www.scaler.com/topics/aws/s3-lifecycle/

[^1_15]: https://notes.kodekloud.com/docs/Amazon-Simple-Storage-Service-Amazon-S3/AWS-S3-Basic-Features/Lifecycle-Policies/page

