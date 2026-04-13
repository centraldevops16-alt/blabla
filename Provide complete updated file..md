<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# Provide complete updated file.

I can’t attach the file from this session because the sandbox/file-sharing environment isn’t initialized right now.

Below is the **complete updated document** in full so you can copy it directly into a `.md` file.

# AWS DevOps Agent: What Changed Since General Availability

## Overview

AWS announced the general availability (GA) of AWS DevOps Agent on March 30, 2026, and positioned the release as an expansion of the preview feature set based on customer feedback.  The GA release emphasizes more scalable and flexible incident response, broader integration support, stronger operational visibility, and tighter controls around chat and access patterns.[^1][^2]

## What Changed at GA

The GA release introduced several platform-level additions beyond the public preview: Amazon EventBridge integration for investigation lifecycle events, updated AWS CLI and SDK support, and broader operational toolchain compatibility including Azure DevOps integration.  AWS also documented a migration path from preview to GA, including IAM updates and security-related behavioral changes that affect some preview-era artifacts.[^2][^1]

### GA additions called out by AWS

- Amazon EventBridge integration for investigation and mitigation lifecycle events.[^3][^1]
- Updated AWS CLI, AWS SDK, and AWS MCP Server support.[^1]
- Azure DevOps integration for tracking deployments and code changes in Azure environments.[^1]
- Expanded operational documentation around vended logs, metrics, private connectivity, and capability configuration.[^4][^1]


## Chat Experience

AWS DevOps Agent includes a chat capability that can be used for on-demand operational analysis within an Agent Space.  AWS publishes the `ConsumedChatRequests` metric in the `AWS/AIDevOps` CloudWatch namespace every five minutes, which means chat usage is now directly monitorable and alarmable at the Agent Space level.[^4]

A notable GA-era change affects historical data retention from preview. AWS states that on-demand chat histories created during the public preview period before March 30, 2026 are no longer accessible after GA because of additional security hardening, while investigation journals and findings from preview remain available.[^2]

### What matters operationally

- Chat consumption is measurable with the `ConsumedChatRequests` CloudWatch metric.[^4]
- Chat is tied to Agent Space usage rather than being a separate standalone service construct.[^4]
- Preview-era on-demand chat history is not retained post-GA, so teams should not rely on preview chat transcripts for long-term operational records.[^2]


## Log Delivery

One of the clearest GA-era documentation additions is vended log delivery for AWS DevOps Agent.  AWS documents that the service can now deliver `APPLICATION_LOGS` to Amazon CloudWatch Logs, Amazon S3, or Amazon Data Firehose by using CloudWatch Logs delivery infrastructure.[^4]

The supported log events include agent inbound events, dropped events, outbound communication failures, topology lifecycle events, resource discovery failures, service registration failures, webhook validation failures, and association validation state changes.  AWS also separates configuration between service-level logs and Agent Space-level logs, which is important for organizations that want centralized platform observability but also per-space troubleshooting controls.[^4]

### Destinations and scope

| Item | Details |
| :-- | :-- |
| Supported destinations | CloudWatch Logs, Amazon S3, Amazon Data Firehose. [^4] |
| Supported log type | `APPLICATION_LOGS`. [^4] |
| Scope options | Service registration level and Agent Space level. [^4] |
| API model | `DeliverySource`, `DeliveryDestination`, and `Delivery` objects in CloudWatch Logs APIs. [^4] |
| Key permission | `aidevops:AllowVendedLogDeliveryForResource` plus CloudWatch Logs delivery permissions. [^4] |

### Related metrics

AWS also publishes built-in CloudWatch metrics for DevOps Agent, including `ConsumedChatRequests`, `ConsumedInvestigationTime`, `ConsumedEvaluationTime`, and `TopologyCompletionCount` under the `AWS/AIDevOps` namespace.  Customers with Agent Spaces created before March 13, 2026 may need to manually create the `AWSServiceRoleForAIDevOps` service-linked role to enable CloudWatch metric publication in their account.[^4]

## EventBridge Integration

EventBridge is one of the most important GA changes for teams that want automated workflows around investigations and mitigation.  AWS DevOps Agent now sends lifecycle events to the EventBridge default event bus when investigation or mitigation state changes occur, allowing downstream automation through native AWS event routing.[^3][^1]

AWS documents several examples for using these events: invoking Lambda when an investigation completes, sending SNS notifications on failures or timeouts, updating ticketing systems when investigations are created, and starting Step Functions workflows when mitigation actions finish.  The event model uses the `aws.aidevops` source, and lifecycle-specific `detail-type` values identify investigation and mitigation events.[^5][^3]

### Common automation patterns

- Lambda processing for completed investigations.[^3]
- SNS notifications for failed or timed-out workflows.[^3]
- Ticket synchronization with ITSM platforms when investigations are created or updated.[^3]
- Step Functions orchestration after mitigation completion.[^3]


## On-Demand DevOps Tasks

On-Demand DevOps Tasks is a generative AI-powered conversational assistant in AWS DevOps Agent that lets operations teams query application architecture, analyze system health, and access investigation insights using natural language.[^6][^7]

### Key capabilities

- Resource queries: ask about AWS resources such as Lambda, DynamoDB, EKS, and certificates with filters like runtime, environment, or expiry windows.[^6]
- System health analysis: ask about alarms, errors, latency, and utilization trends across the services in the Agent Space.[^6]
- Investigation insights: query historical incidents and identify recurring causes, affected services, or common mitigation paths.[^6]
- Investigation steering: guide an active investigation with follow-up prompts such as focusing on a service, dependency, or hypothesis.[^6]
- Artifacts: generate outputs such as health summaries and error reports, with support for editing and version-aware iteration.[^6]
- Recommendation filtering: query prevention recommendations by service, issue category, or operational concern.[^6]


### Access and context

AWS documents the chat panel as persistent in the web application and context-aware to the page a user is on, such as topology or incident response.  AWS also documents that chat history is retained for 90 days per user per Agent Space, and that users can start a fresh thread with the “+ New chat” action.[^6]

### Why it matters after GA

This capability is important after GA because AWS DevOps Agent is no longer only an incident-investigation tool; it also supports ad hoc SRE and operational analysis work through natural-language interaction.  AWS also exposes chat consumption through the `ConsumedChatRequests` metric, which makes on-demand usage monitorable for capacity and governance purposes.[^1][^4][^6]

### Sample prompts

| Category | Examples |
| :-- | :-- |
| Artifacts | “Generate a weekly health summary”, “Create a 4xx/5xx error report”. [^6] |
| Resources | “Which DynamoDB tables use on-demand mode?”, “Show production EKS clusters”. [^6] |
| Health | “What Lambda errors occurred in the payment service?”, “Show ECS CPU utilization trends”. [^6] |
| Steering | “Focus on database throttling”, “Check whether the deployment changed before the incident”. [^6] |

## Integration with Other AWS Services

GA makes AWS DevOps Agent fit more naturally into the broader AWS operational ecosystem.  The most important AWS-native integrations documented in the GA window are CloudWatch, EventBridge, CloudTrail, Lambda, SNS, and Step Functions.[^8][^1][^3][^4]

### AWS-native integration points

| AWS service | How DevOps Agent integrates |
| :-- | :-- |
| Amazon CloudWatch | Publishes vended metrics automatically and can deliver vended logs through CloudWatch Logs infrastructure. [^4] |
| Amazon EventBridge | Emits investigation and mitigation lifecycle events to the default event bus for rule-based automation. [^3] |
| AWS CloudTrail | Captures agent activities in the hosting AWS account for auditability. [^8] |
| AWS Lambda | Common target for EventBridge rules that process investigation results. [^3] |
| Amazon SNS | Common target for EventBridge rules that send operational notifications. [^3] |
| AWS Step Functions | Can be triggered from EventBridge when mitigation actions complete. [^3] |

## Security and Governance Changes

AWS explicitly calls out stronger security measures in the migration documentation for GA, especially around access controls for on-demand chat history.  AWS also states that agent activities are captured by AWS CloudTrail and that detailed journals preserve reasoning steps and actions, which strengthens auditability for regulated operational environments.[^8][^2]

The log delivery model also introduces clear permission boundaries. Enabling delivery requires both AWS DevOps Agent authorization (`aidevops:AllowVendedLogDeliveryForResource`) and CloudWatch Logs delivery permissions, which means organizations can separately control agent operation and log export configuration.[^4]

## Practical Impact for Testing

For post-GA validation, the most important areas to test are the new integration and observability paths rather than only root-cause quality.  A strong regression plan should validate chat metering, EventBridge event emission, CloudWatch metric publication, log delivery activation, and IAM behavior for upgraded preview environments.[^2][^1][^3][^4]

### Suggested validation checklist

- Verify `ConsumedChatRequests` appears in CloudWatch after using chat.[^4]
- Confirm EventBridge receives `aws.aidevops` events for investigation lifecycle changes.[^5][^3]
- Validate log delivery to CloudWatch Logs, S3, and Firehose where required.[^4]
- Confirm CloudTrail captures agent activity in the account.[^8]
- If migrating from preview, verify IAM updates and confirm expected loss of preview-era on-demand chat history.[^2]


## Bottom Line

Since GA, AWS DevOps Agent has become more operationally complete: it now has documented event-driven automation through EventBridge, formal vended logs and metrics, clearer AWS-native observability hooks, and tighter controls around chat history and access.  For most platform teams, the biggest practical change is that the service is no longer just an investigation interface; it is now easier to treat as a monitored, automated, and auditable part of the broader AWS operations stack.[^8][^1][^2][^3][^4]

If you want, I can also format this into:

- a **clean internal wiki version**
- a **test-plan version**
- or a **release-notes comparison table: Preview vs GA**[^1][^2]

<div align="center">⁂</div>

[^1]: https://aws.amazon.com/blogs/mt/announcing-general-availability-of-aws-devops-agent/

[^2]: https://docs.aws.amazon.com/devopsagent/latest/userguide/configuring-capabilities-for-aws-devops-agent-migrating-from-public-preview-to-general-availability.html

[^3]: https://docs.aws.amazon.com/devopsagent/latest/userguide/configuring-capabilities-for-aws-devops-agent-integrating-devops-agent-into-event-driven-applications-using-amazon-eventbridge-index.html

[^4]: https://docs.aws.amazon.com/devopsagent/latest/userguide/configuring-capabilities-for-aws-devops-agent-vended-logs-and-metrics.html

[^5]: https://docs.aws.amazon.com/devopsagent/latest/userguide/integrating-devops-agent-into-event-driven-applications-using-amazon-eventbridge-devops-agent-events-detail-reference.html

[^6]: https://docs.aws.amazon.com/devopsagent/latest/userguide/working-with-devops-agent-on-demand-devops-tasks.html

[^7]: https://aws.amazon.com/devops-agent/

[^8]: https://aws.amazon.com/devops-agent/faqs/

