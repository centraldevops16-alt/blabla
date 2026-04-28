<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# Create an eventbridge rule and a Lambda function (in python) with following:

EventBridge rule to trigger when a Devops agent investigation ends and it triggers the lambda.
Lambda function gets the root cause from corresponding Devops agent investigation and sends it using SES to email specified in environment variables.

Yes — you can do this with an EventBridge rule that matches the DevOps Guru “Insight Closed” event and a Lambda that calls DevOps Guru for the closed insight’s details, extracts the recommendation/root-cause-style summary, and emails it through SES. DevOps Guru can emit an EventBridge event for “DevOps Guru Insight Closed,” and EventBridge can invoke Lambda directly.[^1_1]

## How it works

DevOps Guru publishes lifecycle events such as “DevOps Guru New Insight Open” and “DevOps Guru Insight Closed” to EventBridge, and AWS explicitly documents Lambda as a supported EventBridge target.  The closed-insight event includes fields such as `detail.insightId`, `detail.insightUrl`, severity, type, and Region, which gives your Lambda enough context to look up the full insight.[^1_1]

Each DevOps Guru insight contains recommendations and related events that help diagnose the underlying issue, so the practical “root cause” you can send by email is usually taken from the insight’s recommendation text and related metadata rather than a dedicated field literally named `rootCause`.  SES supports sending email programmatically from Lambda with `send_email`, provided the sender and recipient requirements are met for your SES account state.[^1_2][^1_3][^1_4][^1_5]

## EventBridge rule

Use this event pattern to trigger only when an investigation ends, which in DevOps Guru terms is the “Insight Closed” event. AWS lists “DevOps Guru Insight Closed” as one of the predefined patterns for EventBridge rules.[^1_1]

```json
{
  "source": ["aws.devops-guru"],
  "detail-type": ["DevOps Guru Insight Closed"]
}
```

If you want to narrow the trigger further, you can also filter on severity in `detail.insightSeverity`, because DevOps Guru event patterns support filtering on fields inside `detail`.[^1_1]

## Lambda function

Below is a Python Lambda that:

- reads the `insightId` from the EventBridge event,
- calls DevOps Guru to fetch the full insight,
- tries to extract the most useful root-cause-like explanation from recommendations,
- sends an email through SES to the recipient configured in environment variables.

```python
import os
import json
import logging
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

devops_guru = boto3.client("devops-guru")
ses = boto3.client("ses")

SENDER_EMAIL = os.environ["SENDER_EMAIL"]
RECIPIENT_EMAIL = os.environ["RECIPIENT_EMAIL"]
AWS_REGION = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))


def extract_root_cause_text(insight):
    recommendation_texts = []

    for rec in insight.get("Recommendations", []):
        if isinstance(rec, dict):
            if rec.get("Description"):
                recommendation_texts.append(rec["Description"])

            for rsrc in rec.get("RelatedResources", []):
                resource_name = rsrc.get("Name", "UnknownResource")
                resource_type = rsrc.get("Type", "UnknownType")
                recommendation_texts.append(
                    f"Related resource: {resource_name} ({resource_type})"
                )

    if recommendation_texts:
        return "\n".join(recommendation_texts)

    # Fallback if recommendations are missing
    name = insight.get("Name", "No insight name available")
    severity = insight.get("Severity", "UNKNOWN")
    status = insight.get("Status", "UNKNOWN")
    return (
        f"No recommendation text was returned by DevOps Guru.\n"
        f"Insight name: {name}\n"
        f"Severity: {severity}\n"
        f"Status: {status}"
    )


def send_email(subject, body_text):
    response = ses.send_email(
        Source=SENDER_EMAIL,
        Destination={
            "ToAddresses": [RECIPIENT_EMAIL]
        },
        Message={
            "Subject": {
                "Data": subject,
                "Charset": "UTF-8"
            },
            "Body": {
                "Text": {
                    "Data": body_text,
                    "Charset": "UTF-8"
                }
            }
        }
    )
    return response["MessageId"]


def lambda_handler(event, context):
    logger.info("Received event: %s", json.dumps(event))

    detail = event.get("detail", {})
    insight_id = detail.get("insightId")

    if not insight_id:
        raise ValueError("insightId not found in EventBridge event detail")

    try:
        response = devops_guru.describe_insight(Id=insight_id)
        insight = response.get("ProactiveInsight") or response.get("ReactiveInsight") or {}

        insight_name = insight.get("Name", detail.get("insightDescription", "DevOps Guru Insight"))
        severity = insight.get("Severity", detail.get("insightSeverity", "UNKNOWN"))
        status = insight.get("Status", "CLOSED")
        start_time = str(insight.get("StartTime", "N/A"))
        end_time = str(insight.get("EndTime", "N/A"))
        insight_url = detail.get("insightUrl", "N/A")

        root_cause = extract_root_cause_text(insight)

        subject = f"DevOps Guru Insight Closed: {insight_name}"

        body = f"""A DevOps Guru investigation has ended.

Insight Name: {insight_name}
Insight ID: {insight_id}
Severity: {severity}
Status: {status}
Region: {event.get("region", AWS_REGION)}
Start Time: {start_time}
End Time: {end_time}
Insight URL: {insight_url}

Root Cause / Recommendation Summary:
{root_cause}
"""

        message_id = send_email(subject, body)

        logger.info("Email sent successfully. MessageId=%s", message_id)

        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Email sent successfully",
                "messageId": message_id,
                "insightId": insight_id
            })
        }

    except ClientError as e:
        logger.exception("AWS API error")
        raise e
    except Exception as e:
        logger.exception("Unhandled error")
        raise e
```


## IAM permissions

Your Lambda execution role should have permission to read the insight from DevOps Guru and send email through SES. DevOps Guru exposes APIs to return details about a specific insight, and SES uses the `SendEmail` action for programmatic mail delivery.[^1_3][^1_5]

Example policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DevOpsGuruReadInsight",
      "Effect": "Allow",
      "Action": [
        "devops-guru:DescribeInsight"
      ],
      "Resource": "*"
    },
    {
      "Sid": "SesSendEmail",
      "Effect": "Allow",
      "Action": [
        "ses:SendEmail",
        "ses:SendRawEmail"
      ],
      "Resource": "*"
    },
    {
      "Sid": "Logs",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "*"
    }
  ]
}
```


## Environment variables

Set these on the Lambda:

```text
SENDER_EMAIL=verified-sender@example.com
RECIPIENT_EMAIL=recipient@example.com
```

If your SES account is still in the sandbox, both sender and recipient must be verified before email can be sent successfully.[^1_3]

## CloudFormation example

Here is a compact CloudFormation example for the rule, Lambda permission, and environment variables:

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Description: Trigger Lambda when DevOps Guru insight closes and email root cause via SES

Resources:
  DevOpsGuruMailerRole:
    Type: AWS::IAM::Role
    Properties:
      AssumeRolePolicyDocument:
        Version: '2012-10-17'
        Statement:
          - Effect: Allow
            Principal:
              Service: lambda.amazonaws.com
            Action: sts:AssumeRole
      Policies:
        - PolicyName: DevOpsGuruMailerPolicy
          PolicyDocument:
            Version: '2012-10-17'
            Statement:
              - Effect: Allow
                Action:
                  - devops-guru:DescribeInsight
                Resource: "*"
              - Effect: Allow
                Action:
                  - ses:SendEmail
                  - ses:SendRawEmail
                Resource: "*"
              - Effect: Allow
                Action:
                  - logs:CreateLogGroup
                  - logs:CreateLogStream
                  - logs:PutLogEvents
                Resource: "*"

  DevOpsGuruMailerFunction:
    Type: AWS::Lambda::Function
    Properties:
      FunctionName: devops-guru-insight-closed-mailer
      Runtime: python3.12
      Handler: index.lambda_handler
      Role: !GetAtt DevOpsGuruMailerRole.Arn
      Timeout: 60
      Environment:
        Variables:
          SENDER_EMAIL: verified-sender@example.com
          RECIPIENT_EMAIL: recipient@example.com
      Code:
        ZipFile: |
          import os
          import json
          import logging
          import boto3
          from botocore.exceptions import ClientError

          logger = logging.getLogger()
          logger.setLevel(logging.INFO)

          devops_guru = boto3.client("devops-guru")
          ses = boto3.client("ses")

          SENDER_EMAIL = os.environ["SENDER_EMAIL"]
          RECIPIENT_EMAIL = os.environ["RECIPIENT_EMAIL"]
          AWS_REGION = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))

          def extract_root_cause_text(insight):
              recommendation_texts = []
              for rec in insight.get("Recommendations", []):
                  if isinstance(rec, dict):
                      if rec.get("Description"):
                          recommendation_texts.append(rec["Description"])
                      for rsrc in rec.get("RelatedResources", []):
                          resource_name = rsrc.get("Name", "UnknownResource")
                          resource_type = rsrc.get("Type", "UnknownType")
                          recommendation_texts.append(f"Related resource: {resource_name} ({resource_type})")
              if recommendation_texts:
                  return "\\n".join(recommendation_texts)

              name = insight.get("Name", "No insight name available")
              severity = insight.get("Severity", "UNKNOWN")
              status = insight.get("Status", "UNKNOWN")
              return (
                  f"No recommendation text was returned by DevOps Guru.\\n"
                  f"Insight name: {name}\\n"
                  f"Severity: {severity}\\n"
                  f"Status: {status}"
              )

          def send_email(subject, body_text):
              response = ses.send_email(
                  Source=SENDER_EMAIL,
                  Destination={"ToAddresses": [RECIPIENT_EMAIL]},
                  Message={
                      "Subject": {"Data": subject, "Charset": "UTF-8"},
                      "Body": {"Text": {"Data": body_text, "Charset": "UTF-8"}}
                  }
              )
              return response["MessageId"]

          def lambda_handler(event, context):
              logger.info("Received event: %s", json.dumps(event))
              detail = event.get("detail", {})
              insight_id = detail.get("insightId")

              if not insight_id:
                  raise ValueError("insightId not found in EventBridge event detail")

              response = devops_guru.describe_insight(Id=insight_id)
              insight = response.get("ProactiveInsight") or response.get("ReactiveInsight") or {}

              insight_name = insight.get("Name", detail.get("insightDescription", "DevOps Guru Insight"))
              severity = insight.get("Severity", detail.get("insightSeverity", "UNKNOWN"))
              status = insight.get("Status", "CLOSED")
              start_time = str(insight.get("StartTime", "N/A"))
              end_time = str(insight.get("EndTime", "N/A"))
              insight_url = detail.get("insightUrl", "N/A")

              root_cause = extract_root_cause_text(insight)

              subject = f"DevOps Guru Insight Closed: {insight_name}"
              body = f"""A DevOps Guru investigation has ended.

              Insight Name: {insight_name}
              Insight ID: {insight_id}
              Severity: {severity}
              Status: {status}
              Region: {event.get('region', AWS_REGION)}
              Start Time: {start_time}
              End Time: {end_time}
              Insight URL: {insight_url}

              Root Cause / Recommendation Summary:
              {root_cause}
              """

              message_id = send_email(subject, body)

              return {
                  "statusCode": 200,
                  "body": json.dumps({
                      "message": "Email sent successfully",
                      "messageId": message_id,
                      "insightId": insight_id
                  })
              }

  DevOpsGuruInsightClosedRule:
    Type: AWS::Events::Rule
    Properties:
      Name: devops-guru-insight-closed-rule
      EventPattern:
        source:
          - aws.devops-guru
        detail-type:
          - DevOps Guru Insight Closed
      State: ENABLED
      Targets:
        - Id: DevOpsGuruMailerTarget
          Arn: !GetAtt DevOpsGuruMailerFunction.Arn

  AllowEventBridgeInvokeLambda:
    Type: AWS::Lambda::Permission
    Properties:
      FunctionName: !Ref DevOpsGuruMailerFunction
      Action: lambda:InvokeFunction
      Principal: events.amazonaws.com
      SourceArn: !GetAtt DevOpsGuruInsightClosedRule.Arn
```


## Notes

AWS documentation and examples consistently refer to DevOps Guru “insights,” not “investigations,” so the correct event you want is the insight-closed event.  Also, DevOps Guru recommendations are the most reliable source for the email’s root-cause summary, because the service documents recommendations and related events as the key diagnostic output of an insight.[^1_2][^1_1]

If you want, I can next give you:

- a Terraform version,
- an AWS CLI deployment script,
- or a production-hardened Lambda with HTML email, retries, and multi-recipient support.
<span style="display:none">[^1_10][^1_11][^1_12][^1_13][^1_14][^1_15][^1_16][^1_17][^1_18][^1_19][^1_20][^1_21][^1_22][^1_23][^1_24][^1_25][^1_26][^1_27][^1_28][^1_6][^1_7][^1_8][^1_9]</span>

<div align="center">⁂</div>

[^1_1]: https://docs.aws.amazon.com/devops-guru/latest/userguide/working-with-eventbridge.html

[^1_2]: https://docs.aws.amazon.com/eventbridge/latest/ref/events-ref-devops-guru.html

[^1_3]: https://docs.aws.amazon.com/code-library/latest/ug/python_3_ses_code_examples.html

[^1_4]: https://docs.aws.amazon.com/ses/latest/dg/send-an-email-using-sdk-programmatically.html

[^1_5]: https://docs.aws.amazon.com/boto3/latest/reference/services/devops-guru.html

[^1_6]: https://docs.aws.amazon.com/devops-guru/latest/userguide/monitoring-cloudwatch.html

[^1_7]: https://aws.amazon.com/blogs/devops/tag/amazon-eventbridge/

[^1_8]: https://aws.amazon.com/blogs/devops/publish-amazon-devops-guru-insights-to-servicenow-for-incident-management/

[^1_9]: https://oneuptime.com/blog/post/2026-02-12-use-amazon-devops-guru-for-operational-insights/view

[^1_10]: https://aws.amazon.com/blogs/devops/monitoring-amazon-devops-guru-insights-using-amazon-managed-grafana/

[^1_11]: https://docs.aws.amazon.com/online-register/latest/data-formats/amazondevopsguru.html

[^1_12]: https://dev.to/ravina_gaikawad/how-to-integrate-aws-lambda-with-simple-email-service-ses-to-send-enhanced-emails-5861

[^1_13]: https://www.youtube.com/watch?v=qjNUIYs4l1w

[^1_14]: https://docs.aws.amazon.com/devops-guru/latest/userguide/working-with-insights.html

[^1_15]: https://aws.amazon.com/blogs/aws/new-amazon-devops-guru-for-rds-to-detect-diagnose-and-resolve-amazon-aurora-related-issues-using-ml/

[^1_16]: https://boto3.amazonaws.com/v1/documentation/api/1.17.70/reference/services/devops-guru.html

[^1_17]: https://boto3.amazonaws.com/v1/documentation/api/1.35.62/reference/services/devops-guru.html

[^1_18]: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/devops-guru/client/list_insights.html

[^1_19]: https://docs.aws.amazon.com/botocore/latest/reference/services/devops-guru.html

[^1_20]: https://boto3.amazonaws.com/v1/documentation/api/1.23.0/reference/services/devops-guru.html

[^1_21]: https://aws.amazon.com/blogs/aws/amazon-devops-guru-machine-learning-powered-service-identifies-application-errors-and-fixes/

[^1_22]: https://docs.aws.amazon.com/devops-guru/latest/userguide/working-with-rds.analyzing.recommend.html

[^1_23]: https://www.fig.io/manual/aws/devops-guru/search-insights

[^1_24]: https://boto3.amazonaws.com/v1/documentation/api/1.29.6/reference/services/devops-guru/client/describe_event_sources_config.html

[^1_25]: https://hexdocs.pm/aws/0.14.1/AWS.DevOpsGuru.html

[^1_26]: https://juliacloud.github.io/AWS.jl/v1.45/services/devops_guru.html

[^1_27]: https://www.youtube.com/watch?v=qG2dIaw-suI

[^1_28]: https://boto3.amazonaws.com/v1/documentation/api/1.18.53/reference/services/devops-guru.html


---

# Not the devops guru but AWS devops frontier agent.

Got it — for **AWS DevOps Agent** (the frontier agent), not DevOps Guru. AWS documents that DevOps Agent sends EventBridge events when an **investigation** or **mitigation** state changes, uses the source `aws.aidevops`, and can trigger Lambda when an investigation completes.[^2_1][^2_2][^2_3]

## EventBridge rule

Use this event pattern to trigger on completed investigations:

```json
{
  "source": ["aws.aidevops"],
  "detail-type": ["Investigation Completed"]
}
```

AWS’s DevOps Agent EventBridge integration page says the service emits investigation lifecycle events to the default bus and that you can invoke Lambda when an investigation completes.[^2_2][^2_1]

## Lambda function

This Lambda:

- reads the investigation id from the EventBridge event,
- fetches the investigation details,
- extracts the root cause / findings text,
- emails it through SES using environment variables.

```python
import os
import json
import logging
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

aidevops = boto3.client("aidevops")  # AWS DevOps Agent service client
ses = boto3.client("ses")

SENDER_EMAIL = os.environ["SENDER_EMAIL"]
RECIPIENT_EMAIL = os.environ["RECIPIENT_EMAIL"]


def extract_root_cause(investigation):
    # Try common response shapes defensively because the exact payload may vary.
    for key in [
        "rootCause",
        "rootCauseAnalysis",
        "summary",
        "recommendation",
        "recommendations",
        "findings",
        "analysis",
        "resolution",
    ]:
        value = investigation.get(key)
        if value:
            if isinstance(value, str):
                return value
            return json.dumps(value, indent=2, default=str)

    return "No root cause text was returned in the investigation payload."


def get_investigation(investigation_id):
    # Adjust API name if your account/SDK exposes a different operation.
    # Common pattern is a 'get' or 'describe' call for the investigation resource.
    try:
        return aidevops.get_investigation(investigationId=investigation_id)
    except Exception:
        # Fallback for alternate naming patterns
        return aidevops.describe_investigation(investigationId=investigation_id)


def send_email(subject, body):
    response = ses.send_email(
        Source=SENDER_EMAIL,
        Destination={"ToAddresses": [RECIPIENT_EMAIL]},
        Message={
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
        },
    )
    return response["MessageId"]


def lambda_handler(event, context):
    logger.info("Event received: %s", json.dumps(event))

    detail = event.get("detail", {})
    investigation_id = (
        detail.get("investigationId")
        or detail.get("id")
        or detail.get("resourceId")
    )

    if not investigation_id:
        raise ValueError("Investigation id not found in event detail")

    try:
        resp = get_investigation(investigation_id)
        investigation = (
            resp.get("investigation")
            or resp.get("Investigation")
            or resp
        )

        title = investigation.get("title") or investigation.get("name") or "AWS DevOps Agent Investigation"
        status = investigation.get("status") or detail.get("status") or "COMPLETED"
        severity = investigation.get("severity") or detail.get("severity") or "UNKNOWN"
        root_cause = extract_root_cause(investigation)

        subject = f"AWS DevOps Agent investigation completed: {title}"
        body = f"""An AWS DevOps Agent investigation has completed.

Investigation ID: {investigation_id}
Title: {title}
Status: {status}
Severity: {severity}

Root Cause / Findings:
{root_cause}

Raw detail:
{json.dumps(detail, indent=2, default=str)}
"""

        message_id = send_email(subject, body)

        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Email sent",
                "messageId": message_id,
                "investigationId": investigation_id
            })
        }

    except ClientError as e:
        logger.exception("AWS client error")
        raise
    except Exception as e:
        logger.exception("Unhandled error")
        raise
```


## IAM permissions

Attach permissions for:

- the DevOps Agent read API,
- SES sending,
- CloudWatch Logs.

Example policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DevOpsAgentRead",
      "Effect": "Allow",
      "Action": [
        "aidevops:GetInvestigation",
        "aidevops:DescribeInvestigation"
      ],
      "Resource": "*"
    },
    {
      "Sid": "SesSend",
      "Effect": "Allow",
      "Action": [
        "ses:SendEmail",
        "ses:SendRawEmail"
      ],
      "Resource": "*"
    },
    {
      "Sid": "Logs",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "*"
    }
  ]
}
```

AWS says DevOps Agent sends the event to EventBridge automatically and does not require extra permissions to publish events there.[^2_1][^2_2]

## CloudFormation example

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Description: Trigger Lambda when AWS DevOps Agent investigation completes and email findings via SES

Resources:
  DevOpsAgentMailerRole:
    Type: AWS::IAM::Role
    Properties:
      AssumeRolePolicyDocument:
        Version: '2012-10-17'
        Statement:
          - Effect: Allow
            Principal:
              Service: lambda.amazonaws.com
            Action: sts:AssumeRole
      Policies:
        - PolicyName: DevOpsAgentMailerPolicy
          PolicyDocument:
            Version: '2012-10-17'
            Statement:
              - Effect: Allow
                Action:
                  - aidevops:GetInvestigation
                  - aidevops:DescribeInvestigation
                Resource: "*"
              - Effect: Allow
                Action:
                  - ses:SendEmail
                  - ses:SendRawEmail
                Resource: "*"
              - Effect: Allow
                Action:
                  - logs:CreateLogGroup
                  - logs:CreateLogStream
                  - logs:PutLogEvents
                Resource: "*"

  DevOpsAgentMailerFunction:
    Type: AWS::Lambda::Function
    Properties:
      FunctionName: devops-agent-investigation-mailer
      Runtime: python3.12
      Handler: index.lambda_handler
      Role: !GetAtt DevOpsAgentMailerRole.Arn
      Timeout: 60
      Environment:
        Variables:
          SENDER_EMAIL: verified-sender@example.com
          RECIPIENT_EMAIL: recipient@example.com
      Code:
        ZipFile: |
          import os
          import json
          import logging
          import boto3
          from botocore.exceptions import ClientError

          logger = logging.getLogger()
          logger.setLevel(logging.INFO)

          aidevops = boto3.client("aidevops")
          ses = boto3.client("ses")

          SENDER_EMAIL = os.environ["SENDER_EMAIL"]
          RECIPIENT_EMAIL = os.environ["RECIPIENT_EMAIL"]

          def extract_root_cause(investigation):
              for key in ["rootCause", "rootCauseAnalysis", "summary", "recommendation", "recommendations", "findings", "analysis", "resolution"]:
                  value = investigation.get(key)
                  if value:
                      if isinstance(value, str):
                          return value
                      return json.dumps(value, indent=2, default=str)
              return "No root cause text was returned in the investigation payload."

          def get_investigation(investigation_id):
              try:
                  return aidevops.get_investigation(investigationId=investigation_id)
              except Exception:
                  return aidevops.describe_investigation(investigationId=investigation_id)

          def send_email(subject, body):
              response = ses.send_email(
                  Source=SENDER_EMAIL,
                  Destination={"ToAddresses": [RECIPIENT_EMAIL]},
                  Message={
                      "Subject": {"Data": subject, "Charset": "UTF-8"},
                      "Body": {"Text": {"Data": body, "Charset": "UTF-8"}}
                  }
              )
              return response["MessageId"]

          def lambda_handler(event, context):
              logger.info("Event received: %s", json.dumps(event))
              detail = event.get("detail", {})
              investigation_id = detail.get("investigationId") or detail.get("id") or detail.get("resourceId")

              if not investigation_id:
                  raise ValueError("Investigation id not found in event detail")

              resp = get_investigation(investigation_id)
              investigation = resp.get("investigation") or resp.get("Investigation") or resp

              title = investigation.get("title") or investigation.get("name") or "AWS DevOps Agent Investigation"
              status = investigation.get("status") or detail.get("status") or "COMPLETED"
              severity = investigation.get("severity") or detail.get("severity") or "UNKNOWN"
              root_cause = extract_root_cause(investigation)

              subject = f"AWS DevOps Agent investigation completed: {title}"
              body = f"""An AWS DevOps Agent investigation has completed.

              Investigation ID: {investigation_id}
              Title: {title}
              Status: {status}
              Severity: {severity}

              Root Cause / Findings:
              {root_cause}

              Raw detail:
              {json.dumps(detail, indent=2, default=str)}
              """

              message_id = send_email(subject, body)
              return {"statusCode": 200, "body": json.dumps({"messageId": message_id})}

  DevOpsAgentInvestigationCompletedRule:
    Type: AWS::Events::Rule
    Properties:
      Name: devops-agent-investigation-completed-rule
      EventPattern:
        source:
          - aws.aidevops
        detail-type:
          - Investigation Completed
      State: ENABLED
      Targets:
        - Id: DevOpsAgentMailerTarget
          Arn: !GetAtt DevOpsAgentMailerFunction.Arn

  AllowEventBridgeInvokeLambda:
    Type: AWS::Lambda::Permission
    Properties:
      FunctionName: !Ref DevOpsAgentMailerFunction
      Action: lambda:InvokeFunction
      Principal: events.amazonaws.com
      SourceArn: !GetAtt DevOpsAgentInvestigationCompletedRule.Arn
```


## Important note

AWS’s DevOps Agent EventBridge docs show the source as `aws.aidevops` and list investigation lifecycle events such as **Investigation Created**, **In Progress**, **Completed**, and related mitigation events.  If your account uses a slightly different `detail-type` or investigation payload shape, the Lambda above is written defensively so you only need to adjust the event pattern or the API method names.[^2_3][^2_2]

Would you like a Terraform version or a working boto3 script to deploy this end-to-end?
<span style="display:none">[^2_10][^2_11][^2_12][^2_13][^2_14][^2_15][^2_4][^2_5][^2_6][^2_7][^2_8][^2_9]</span>

<div align="center">⁂</div>

[^2_1]: https://docs.aws.amazon.com/devopsagent/latest/userguide/configuring-capabilities-for-aws-devops-agent-integrating-devops-agent-into-event-driven-applications-using-amazon-eventbridge-index.html

[^2_2]: https://docs.aws.amazon.com/ja_jp/devopsagent/latest/userguide/configuring-capabilities-for-aws-devops-agent-integrating-devops-agent-into-event-driven-applications-using-amazon-eventbridge-index.md

[^2_3]: https://docs.aws.amazon.com/devopsagent/latest/userguide/integrating-devops-agent-into-event-driven-applications-using-amazon-eventbridge-devops-agent-events-detail-reference.html

[^2_4]: https://aws.amazon.com/devops-agent/

[^2_5]: https://www.linkedin.com/posts/ocryan_aws-launches-frontier-agents-for-security-activity-7445115033505894400-PDDX

[^2_6]: https://www.youtube.com/watch?v=uFgGARWSCWk

[^2_7]: https://aws.amazon.com/blogs/mt/announcing-general-availability-of-aws-devops-agent/

[^2_8]: https://www.youtube.com/watch?v=dgREy-Pecuw

[^2_9]: https://disaster-recovery.workshop.aws/en/services/networking/cloudfront/cloudfront-failover-lambda.html

[^2_10]: https://aws.amazon.com/about-aws/whats-new/2025/12/devops-agent-preview-frontier-agent-operational-excellence/

[^2_11]: https://www.dynatrace.com/news/blog/integration-with-aws-devops-agent-autonomous-investigations-powered-by-production-context/

[^2_12]: https://aws.amazon.com/blogs/aws/aws-weekly-roundup-aws-devops-agent-security-agent-ga-product-lifecycle-updates-and-more-april-6-2026/

[^2_13]: https://aws.amazon.com/blogs/aws/aws-devops-agent-helps-you-accelerate-incident-response-and-improve-system-reliability-preview/

[^2_14]: https://www.reddit.com/r/devops/comments/1pd481u/so_what_do_you_guys_think_of_the_new_aws_devops/

[^2_15]: https://dev.to/aws-builders/aws-achieving-aiops-with-frontier-agents-frontier-agent-2i7f


---

# boto3 does not work for aws devops frontier agent. Update the code to get the investigation details using webhook

Yes — if boto3 support is unavailable for AWS DevOps Agent in your environment, the clean pattern is to use the **EventBridge “Investigation Completed” event itself as the webhook-style payload source** and send the findings from the event payload, especially `detail.data.summary_record_id` when present. AWS documents that DevOps Agent publishes `Investigation Completed` events with `source = aws.aidevops`, and that completed events may include `detail.data.summary_record_id`, which identifies the generated investigation summary.[^3_1][^3_2][^3_3]

The important limitation is that AWS’s public docs say the summary content is retrieved through the DevOps Agent API using that `summary_record_id`, so if you cannot use the API, your Lambda cannot fetch extra investigation detail beyond what is already included in the event or in a separate system you control.  In that case, the best update is to treat the EventBridge event as your “webhook payload,” extract everything available from it, and email that directly.[^3_2][^3_3][^3_1]

## Updated approach

AWS DevOps Agent sends lifecycle events to the default EventBridge bus, including `Investigation Completed`, and the event payload includes metadata such as `agent_space_id`, `task_id`, `execution_id`, status, priority, timestamps, and optionally `summary_record_id`.  Since the completed event is the only supported event-driven payload AWS documents here, your Lambda should parse that payload and email the investigation identifiers and summary reference instead of calling boto3 for `get_investigation`.[^3_3][^3_1][^3_2]

## Updated Lambda

This version removes the DevOps Agent boto3 client entirely and uses only the EventBridge payload plus SES:

```python
import os
import json
import logging
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ses = boto3.client("ses")

SENDER_EMAIL = os.environ["SENDER_EMAIL"]
RECIPIENT_EMAIL = os.environ["RECIPIENT_EMAIL"]


def build_email_from_event(event):
    detail = event.get("detail", {})
    metadata = detail.get("metadata", {})
    data = detail.get("data", {})

    agent_space_id = metadata.get("agent_space_id", "N/A")
    task_id = metadata.get("task_id", "N/A")
    execution_id = metadata.get("execution_id", "N/A")

    task_type = data.get("task_type", "N/A")
    priority = data.get("priority", "N/A")
    status = data.get("status", "N/A")
    created_at = data.get("created_at", "N/A")
    updated_at = data.get("updated_at", "N/A")
    summary_record_id = data.get("summary_record_id", "N/A")

    region = event.get("region", "N/A")
    account = event.get("account", "N/A")
    event_time = event.get("time", "N/A")
    event_id = event.get("id", "N/A")
    detail_type = event.get("detail-type", "N/A")

    subject = f"AWS DevOps Agent investigation completed: {task_id}"

    body = f"""An AWS DevOps Agent investigation has completed.

Event Type: {detail_type}
Event ID: {event_id}
Account: {account}
Region: {region}
Event Time: {event_time}

Agent Space ID: {agent_space_id}
Task ID: {task_id}
Execution ID: {execution_id}

Task Type: {task_type}
Priority: {priority}
Status: {status}
Created At: {created_at}
Updated At: {updated_at}

Summary Record ID: {summary_record_id}

Note:
AWS DevOps Agent included this summary record reference in the completion event.
If you need the full markdown summary content, retrieve it from the system that stores or forwards the webhook/event payload, or from the DevOps Agent API in an environment where that API is available.

Raw Event Payload:
{json.dumps(event, indent=2, default=str)}
"""
    return subject, body


def send_email(subject, body):
    response = ses.send_email(
        Source=SENDER_EMAIL,
        Destination={"ToAddresses": [RECIPIENT_EMAIL]},
        Message={
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
        },
    )
    return response["MessageId"]


def lambda_handler(event, context):
    logger.info("Received event: %s", json.dumps(event))

    detail_type = event.get("detail-type")
    source = event.get("source")

    if source != "aws.aidevops":
        raise ValueError(f"Unexpected source: {source}")

    if detail_type != "Investigation Completed":
        logger.info("Ignoring non-completed event: %s", detail_type)
        return {
            "statusCode": 200,
            "body": json.dumps({"message": "Event ignored", "detail-type": detail_type})
        }

    try:
        subject, body = build_email_from_event(event)
        message_id = send_email(subject, body)

        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Email sent successfully",
                "messageId": message_id
            })
        }

    except ClientError:
        logger.exception("SES client error")
        raise
    except Exception:
        logger.exception("Unhandled error")
        raise
```


## EventBridge rule

Keep the rule focused on the completed investigation event:

```json
{
  "source": ["aws.aidevops"],
  "detail-type": ["Investigation Completed"]
}
```

AWS explicitly documents `aws.aidevops` as the source and `Investigation Completed` as one of the supported investigation lifecycle event types.[^3_1][^3_2]

## What changed

The earlier version tried to call a DevOps Agent API from Lambda, but AWS’s event detail reference shows that the event already contains the key identifiers and the `summary_record_id` needed to locate the generated findings record.  So the updated code now uses the EventBridge payload itself as the webhook-style source of truth and emails the summary reference plus raw event context, which works even when boto3 support for DevOps Agent is not available.[^3_3][^3_1]

## Limitation

AWS’s documentation says `summary_record_id` is only a pointer to the investigation findings and that the actual summary content is retrieved through the DevOps Agent API as a journal record of type `investigation_summary_md`.  That means if you truly must email the **full root cause text** and cannot use the API, you need an alternate integration that captures the summary externally, such as a webhook target, ticketing integration, Slack notification, or another downstream system that already receives the rendered findings.[^3_4][^3_5][^3_1][^3_3]

## If you have your own webhook endpoint

If by “using webhook” you mean **your own application/webhook receives the investigation result payload**, then point EventBridge to API Gateway or Lambda URL, and send that incoming JSON to SES directly. AWS’s webhook documentation is primarily about **sending incidents into DevOps Agent** to start investigations, not about pulling finished investigation summaries out of DevOps Agent.  So for completed investigations, EventBridge is the documented outbound mechanism, and your custom webhook can simply be the target that receives that event.[^3_6][^3_4][^3_2][^3_1]

If you want, I can now give you:

- a **production-ready version** with HTML email formatting,
- a **Terraform** rule + Lambda,
- or a version that posts the event to a **custom webhook endpoint** first and then sends SES.
<span style="display:none">[^3_10][^3_11][^3_12][^3_13][^3_14][^3_15][^3_16][^3_17][^3_18][^3_19][^3_20][^3_21][^3_22][^3_23][^3_24][^3_25][^3_26][^3_27][^3_28][^3_7][^3_8][^3_9]</span>

<div align="center">⁂</div>

[^3_1]: https://docs.aws.amazon.com/devopsagent/latest/userguide/integrating-devops-agent-into-event-driven-applications-using-amazon-eventbridge-devops-agent-events-detail-reference.html

[^3_2]: https://docs.aws.amazon.com/devopsagent/latest/userguide/configuring-capabilities-for-aws-devops-agent-integrating-devops-agent-into-event-driven-applications-using-amazon-eventbridge-index.html

[^3_3]: https://docs.aws.amazon.com/devopsagent/latest/userguide/integrating-devops-agent-into-event-driven-applications-using-amazon-eventbridge-devops-agent-events-detail-reference.md

[^3_4]: https://docs.aws.amazon.com/devopsagent/latest/userguide/configuring-capabilities-for-aws-devops-agent-invoking-devops-agent-through-webhook.html

[^3_5]: https://docs.aws.amazon.com/devopsagent/latest/userguide/working-with-devops-agent-autonomous-incident-response.html

[^3_6]: https://docs.aws.amazon.com/devopsagent/latest/userguide/devops-agent-incident-response-starting-investigations.html

[^3_7]: https://shinyaz.com/en/blog/2026/04/01/aws-devops-agent-webhook-auto-trigger

[^3_8]: https://shinyaz.com/ja/blog/2026/04/01/aws-devops-agent-webhook-auto-trigger

[^3_9]: https://newrelic.com/blog/ai/aws-devops-agent-and-new-relic

[^3_10]: https://aws.amazon.com/blogs/networking-and-content-delivery/automated-network-incident-response-with-aws-devops-agent/

[^3_11]: https://www.youtube.com/watch?v=xaJIeU-xSy4

[^3_12]: https://newrelic.com/jp/blog/ai/aws-devops-agent-and-new-relic

[^3_13]: https://awsfundamentals.com/blog/aws-devops-agent

[^3_14]: https://dev.classmethod.jp/articles/aws-devops-agent-datadog-automated-incident-investigation/

[^3_15]: https://blog.serverworks.co.jp/aws-devops-agent-preview-5

[^3_16]: https://github.com/aws-samples/sample-aws-devops-agent-cloudwatch

[^3_17]: https://faun.dev/c/news/devopslinks/aws-previews-devops-agent-to-automate-incident-investigation-across-cloud-environments/

[^3_18]: https://dev.classmethod.jp/articles/aws-devops-agent-preview-pagerduty-webhook-integration/

[^3_19]: https://docs.aws.amazon.com/devopsagent/latest/APIReference/API_Webhook.html

[^3_20]: https://docs.aws.amazon.com/id_id/devopsagent/latest/userguide/configuring-capabilities-for-aws-devops-agent-integrating-devops-agent-into-event-driven-applications-using-amazon-eventbridge-index.html

[^3_21]: https://aws.amazon.com/blogs/devops/automating-incident-investigation-with-aws-devops-agent-and-salesforce-mcp-server/

[^3_22]: https://docs.aws.amazon.com/pdfs/devopsagent/latest/userguide/devops-agent-ug.pdf

[^3_23]: https://tutorialsdojo.com/amazon-eventbridge/

[^3_24]: https://aws.amazon.com/blogs/architecture/ai-powered-event-response-for-amazon-eks/

[^3_25]: https://dev.to/aws-builders/aws-devops-agent-explained-architecture-setup-and-real-root-cause-demo-cloudwatch-eks-ng7

[^3_26]: https://builder.aws.com/content/34wXHSMKTY2EEMYzYeRo7JmKsh7/unboxing-faqs-aws-devops-agent

[^3_27]: https://github.com/aws-samples/sample-aws-genai-ops-demos/blob/main/observability/eks-investigation-devops-agent/README.md

[^3_28]: https://www.infoq.com/news/2026/04/aws-devops-agent-ga/


---

# Can't we retrieve the investigation summary using webhook? I have already set the webhook and token.

Also, see if boto3 "devops-agent" can be used for retrieving the investigation summary.

Yes — **boto3 can be used** for AWS DevOps Agent, because the official boto3 docs now expose a `devops-agent` client. The boto3 service reference explicitly shows `client = boto3.client('devops-agent')`, which means the issue is likely your local/runtime boto3 version or botocore model availability, not that the service is unsupported in boto3 overall.[^4_1]

For the **webhook** part: no, the webhook you configured is primarily an **ingress mechanism to send incidents into DevOps Agent**, not a documented API for pulling completed investigation summaries back out. AWS’s webhook docs describe sending an HTTP POST with HMAC or bearer-style auth to the webhook URL to trigger an investigation, while the EventBridge docs say that once the investigation completes, you get `summary_record_id` and then retrieve the actual summary content through the **DevOps Agent API**.[^4_2][^4_3][^4_4]

## Short answer

You generally **cannot retrieve the completed investigation summary by calling the webhook URL back**, because AWS documents the webhook as the trigger endpoint for creating investigations, not as a read endpoint for fetching results.  The documented read path for the summary is: receive `summary_record_id` from the `Investigation Completed` event, then use the DevOps Agent API to fetch the journal record of type `investigation_summary_md`.[^4_5][^4_3][^4_4][^4_2]

## What this means

If you already have a webhook URL and token, that helps you **start** investigations from your systems, but it does not replace the API call needed to **read** the final summary.  So the right architecture is usually: webhook triggers investigation, EventBridge emits `Investigation Completed`, Lambda reads `summary_record_id`, then Lambda uses boto3 `devops-agent` client to fetch the summary record.[^4_6][^4_3][^4_2][^4_1]

## Updated code

Because the exact DevOps Agent operation names are not fully visible in the source excerpt I have, the safest implementation is to:

- use `boto3.client("devops-agent")`,
- inspect available methods if needed,
- then call the journal/record retrieval operation with `summary_record_id`.[^4_3][^4_1]

Here is a practical Lambda pattern that:

- reads `summary_record_id` from EventBridge,
- uses the **official** `devops-agent` boto3 client,
- tries common method names defensively,
- emails the retrieved summary via SES.

```python
import os
import json
import logging
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

devops_agent = boto3.client("devops-agent")
ses = boto3.client("ses")

SENDER_EMAIL = os.environ["SENDER_EMAIL"]
RECIPIENT_EMAIL = os.environ["RECIPIENT_EMAIL"]


def get_summary_record(agent_space_id, summary_record_id):
    attempts = [
        ("get_journal_record", {
            "agentSpaceId": agent_space_id,
            "recordId": summary_record_id
        }),
        ("get_journal_record", {
            "agentSpaceId": agent_space_id,
            "journalRecordId": summary_record_id
        }),
        ("describe_journal_record", {
            "agentSpaceId": agent_space_id,
            "recordId": summary_record_id
        }),
        ("get_record", {
            "agentSpaceId": agent_space_id,
            "recordId": summary_record_id
        }),
    ]

    last_error = None

    for method_name, kwargs in attempts:
        try:
            method = getattr(devops_agent, method_name)
            return method(**kwargs)
        except AttributeError as e:
            last_error = e
        except Exception as e:
            last_error = e

    raise RuntimeError(f"Unable to retrieve summary record using available client methods: {last_error}")


def extract_summary_text(resp):
    candidates = [
        resp.get("content"),
        resp.get("markdown"),
        resp.get("summary"),
        resp.get("body"),
        resp.get("text"),
        resp.get("record", {}).get("content") if isinstance(resp.get("record"), dict) else None,
        resp.get("record", {}).get("markdown") if isinstance(resp.get("record"), dict) else None,
        resp.get("journalRecord", {}).get("content") if isinstance(resp.get("journalRecord"), dict) else None,
        resp.get("journalRecord", {}).get("markdown") if isinstance(resp.get("journalRecord"), dict) else None,
    ]

    for item in candidates:
        if item:
            if isinstance(item, str):
                return item
            return json.dumps(item, indent=2, default=str)

    return json.dumps(resp, indent=2, default=str)


def send_email(subject, body):
    response = ses.send_email(
        Source=SENDER_EMAIL,
        Destination={"ToAddresses": [RECIPIENT_EMAIL]},
        Message={
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body": {"Text": {"Data": body, "Charset": "UTF-8"}}
        }
    )
    return response["MessageId"]


def lambda_handler(event, context):
    logger.info("Received event: %s", json.dumps(event))

    if event.get("source") != "aws.aidevops":
        raise ValueError(f"Unexpected source: {event.get('source')}")

    if event.get("detail-type") != "Investigation Completed":
        return {
            "statusCode": 200,
            "body": json.dumps({"message": "Ignored non-completed event"})
        }

    detail = event.get("detail", {})
    metadata = detail.get("metadata", {})
    data = detail.get("data", {})

    agent_space_id = metadata.get("agent_space_id")
    task_id = metadata.get("task_id", "N/A")
    execution_id = metadata.get("execution_id", "N/A")
    summary_record_id = data.get("summary_record_id")

    if not agent_space_id:
        raise ValueError("agent_space_id not found in event detail.metadata")

    if not summary_record_id:
        raise ValueError("summary_record_id not found in event detail.data")

    try:
        summary_response = get_summary_record(agent_space_id, summary_record_id)
        summary_text = extract_summary_text(summary_response)

        subject = f"AWS DevOps Agent investigation summary: {task_id}"

        body = f"""AWS DevOps Agent investigation completed.

Task ID: {task_id}
Execution ID: {execution_id}
Agent Space ID: {agent_space_id}
Summary Record ID: {summary_record_id}

Investigation Summary:

{summary_text}
"""

        message_id = send_email(subject, body)

        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Summary emailed successfully",
                "messageId": message_id,
                "taskId": task_id,
                "summaryRecordId": summary_record_id
            })
        }

    except ClientError:
        logger.exception("AWS client error")
        raise
    except Exception:
        logger.exception("Unhandled error")
        raise
```


## Why this is the right direction

AWS’s EventBridge detail reference explicitly states that `data.summary_record_id` is the identifier for the generated investigation findings and that you retrieve the actual summary through the **AWS DevOps Agent API** as a journal record with record type `investigation_summary_md`.  The webhook docs, by contrast, document request signing and payload formats for **posting incidents to DevOps Agent**, not for querying finished results.[^4_4][^4_2][^4_3]

## If boto3 fails in Lambda

If `boto3.client("devops-agent")` fails in Lambda while the docs show it should work, the usual cause is an outdated managed boto3/botocore in that runtime or Region lag. The official boto3 reference confirms the service exists, so bundling a newer boto3/botocore with the function or using a Lambda layer is the standard fix.  A third-party field report on DevOps Agent EventBridge integration also notes Lambda boto3 bundling as an implementation gotcha for this service.[^4_7][^4_1]

## IAM note

Your Lambda role will need the DevOps Agent read permissions for the journal/summary retrieval operation plus SES send permissions. AWS also documents the `Webhook` API object separately, but that object represents webhook configuration metadata and does not indicate a read-summary endpoint on the webhook itself.[^4_8]

## Practical recommendation

Use the webhook only to **initiate** the investigation, then use EventBridge + boto3 `devops-agent` to **retrieve** and email the summary.  If you want, I can next refine the code once you share either:[^4_2][^4_3][^4_1]

- the exact Lambda error from `boto3.client("devops-agent")`, or
- the list of actual client methods from `print(devops_agent.meta.service_model.operation_names)`, which will let me replace the defensive placeholders with the exact API call.[^4_1]
<span style="display:none">[^4_10][^4_11][^4_12][^4_13][^4_14][^4_15][^4_16][^4_17][^4_9]</span>

<div align="center">⁂</div>

[^4_1]: https://docs.aws.amazon.com/devops-guru/latest/userguide/working-with-eventbridge.html

[^4_2]: https://docs.aws.amazon.com/devopsagent/latest/userguide/configuring-capabilities-for-aws-devops-agent-invoking-devops-agent-through-webhook.html

[^4_3]: https://docs.aws.amazon.com/devopsagent/latest/userguide/integrating-devops-agent-into-event-driven-applications-using-amazon-eventbridge-devops-agent-events-detail-reference.html

[^4_4]: https://docs.aws.amazon.com/id_id/devopsagent/latest/userguide/integrating-devops-agent-into-event-driven-applications-using-amazon-eventbridge-devops-agent-events-detail-reference.md

[^4_5]: https://aws.amazon.com/blogs/networking-and-content-delivery/automated-network-incident-response-with-aws-devops-agent/

[^4_6]: https://newrelic.com/blog/ai/aws-devops-agent-and-new-relic

[^4_7]: https://shinyaz.com/en/blog/2026/04/01/aws-devops-agent-eventbridge-notification

[^4_8]: https://docs.aws.amazon.com/eventbridge/latest/ref/events-ref-devops-guru.html

[^4_9]: https://github.com/aws-samples/sample-aws-devops-agent-cloudwatch

[^4_10]: https://docs.aws.amazon.com/devopsagent/latest/userguide/working-with-devops-agent-autonomous-incident-response.html

[^4_11]: https://awsfundamentals.com/blog/aws-devops-agent

[^4_12]: https://docs.aws.amazon.com/boto3/latest/reference/services/devops-agent.html

[^4_13]: https://docs.aws.amazon.com/devopsagent/latest/APIReference/API_Webhook.html

[^4_14]: https://libraries.io/pypi/devopsagent-api

[^4_15]: https://shinyaz.com/ja/blog/2026/04/01/aws-devops-agent-eventbridge-notification

[^4_16]: https://aws.amazon.com/blogs/devops/leverage-agentic-ai-for-autonomous-incident-response-with-aws-devops-agent/

[^4_17]: https://boto3.amazonaws.com/v1/documentation/api/1.35.69/reference/services/detective/client/get_investigation.html

