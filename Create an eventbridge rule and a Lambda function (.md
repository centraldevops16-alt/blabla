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

