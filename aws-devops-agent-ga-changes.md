# AWS DevOps Agent: What Changed Since General Availability

## Overview
AWS announced the general availability (GA) of AWS DevOps Agent on March 30, 2026, and positioned the release as an expansion of the preview feature set based on customer feedback.[cite:1] The GA release emphasizes more scalable and flexible incident response, broader integration support, stronger operational visibility, and tighter controls around chat and access patterns.[cite:1][cite:43]

## What Changed at GA
The GA release introduced several platform-level additions beyond the public preview: Amazon EventBridge integration for investigation lifecycle events, updated AWS CLI and SDK support, and broader operational toolchain compatibility including Azure DevOps integration.[cite:1] AWS also documented a migration path from preview to GA, including IAM updates and security-related behavioral changes that affect some preview-era artifacts.[cite:43]

### GA additions called out by AWS
- Amazon EventBridge integration for investigation and mitigation lifecycle events.[cite:1][cite:42]
- Updated AWS CLI, AWS SDK, and AWS MCP Server support.[cite:1]
- Azure DevOps integration for tracking deployments and code changes in Azure environments.[cite:1]
- Expanded operational documentation around vended logs, metrics, private connectivity, and capability configuration.[cite:1][cite:32]

## Chat Experience
AWS DevOps Agent includes a chat capability that can be used for on-demand operational analysis within an Agent Space.[cite:32] AWS publishes the `ConsumedChatRequests` metric in the `AWS/AIDevOps` CloudWatch namespace every five minutes, which means chat usage is now directly monitorable and alarmable at the Agent Space level.[cite:32]

A notable GA-era change affects historical data retention from preview. AWS states that on-demand chat histories created during the public preview period before March 30, 2026 are no longer accessible after GA because of additional security hardening, while investigation journals and findings from preview remain available.[cite:43]

### What matters operationally
- Chat consumption is measurable with the `ConsumedChatRequests` CloudWatch metric.[cite:32]
- Chat is tied to Agent Space usage rather than being a separate standalone service construct.[cite:32]
- Preview-era on-demand chat history is not retained post-GA, so teams should not rely on preview chat transcripts for long-term operational records.[cite:43]

## Log Delivery
One of the clearest GA-era documentation additions is vended log delivery for AWS DevOps Agent.[cite:32] AWS documents that the service can now deliver `APPLICATION_LOGS` to Amazon CloudWatch Logs, Amazon S3, or Amazon Data Firehose by using CloudWatch Logs delivery infrastructure.[cite:32]

The supported log events include agent inbound events, dropped events, outbound communication failures, topology lifecycle events, resource discovery failures, service registration failures, webhook validation failures, and association validation state changes.[cite:32] AWS also separates configuration between service-level logs and Agent Space-level logs, which is important for organizations that want centralized platform observability but also per-space troubleshooting controls.[cite:32]

### Destinations and scope
| Item | Details |
|---|---|
| Supported destinations | CloudWatch Logs, Amazon S3, Amazon Data Firehose.[cite:32] |
| Supported log type | `APPLICATION_LOGS`.[cite:32] |
| Scope options | Service registration level and Agent Space level.[cite:32] |
| API model | `DeliverySource`, `DeliveryDestination`, and `Delivery` objects in CloudWatch Logs APIs.[cite:32] |
| Key permission | `aidevops:AllowVendedLogDeliveryForResource` plus CloudWatch Logs delivery permissions.[cite:32] |

### Related metrics
AWS also publishes built-in CloudWatch metrics for DevOps Agent, including `ConsumedChatRequests`, `ConsumedInvestigationTime`, `ConsumedEvaluationTime`, and `TopologyCompletionCount` under the `AWS/AIDevOps` namespace.[cite:32] Customers with Agent Spaces created before March 13, 2026 may need to manually create the `AWSServiceRoleForAIDevOps` service-linked role to enable CloudWatch metric publication in their account.[cite:32]

## EventBridge Integration
EventBridge is one of the most important GA changes for teams that want automated workflows around investigations and mitigation.[cite:1][cite:42] AWS DevOps Agent now sends lifecycle events to the EventBridge default event bus when investigation or mitigation state changes occur, allowing downstream automation through native AWS event routing.[cite:42]

AWS documents several examples for using these events: invoking Lambda when an investigation completes, sending SNS notifications on failures or timeouts, updating ticketing systems when investigations are created, and starting Step Functions workflows when mitigation actions finish.[cite:42] The event model uses the `aws.aidevops` source, and lifecycle-specific `detail-type` values identify investigation and mitigation events.[cite:42][cite:47]

### Common automation patterns
- Lambda processing for completed investigations.[cite:42]
- SNS notifications for failed or timed-out workflows.[cite:42]
- Ticket synchronization with ITSM platforms when investigations are created or updated.[cite:42]
- Step Functions orchestration after mitigation completion.[cite:42]

## Integration with Other AWS Services
GA makes AWS DevOps Agent fit more naturally into the broader AWS operational ecosystem.[cite:1][cite:33] The most important AWS-native integrations documented in the GA window are CloudWatch, EventBridge, CloudTrail, Lambda, SNS, and Step Functions.[cite:32][cite:42][cite:33]

### AWS-native integration points
| AWS service | How DevOps Agent integrates |
|---|---|
| Amazon CloudWatch | Publishes vended metrics automatically and can deliver vended logs through CloudWatch Logs infrastructure.[cite:32] |
| Amazon EventBridge | Emits investigation and mitigation lifecycle events to the default event bus for rule-based automation.[cite:42] |
| AWS CloudTrail | Captures agent activities in the hosting AWS account for auditability.[cite:33] |
| AWS Lambda | Common target for EventBridge rules that process investigation results.[cite:42] |
| Amazon SNS | Common target for EventBridge rules that send operational notifications.[cite:42] |
| AWS Step Functions | Can be triggered from EventBridge when mitigation actions complete.[cite:42] |

## Security and Governance Changes
AWS explicitly calls out stronger security measures in the migration documentation for GA, especially around access controls for on-demand chat history.[cite:43] AWS also states that agent activities are captured by AWS CloudTrail and that detailed journals preserve reasoning steps and actions, which strengthens auditability for regulated operational environments.[cite:33]

The log delivery model also introduces clear permission boundaries. Enabling delivery requires both AWS DevOps Agent authorization (`aidevops:AllowVendedLogDeliveryForResource`) and CloudWatch Logs delivery permissions, which means organizations can separately control agent operation and log export configuration.[cite:32]

## Practical Impact for Testing
For post-GA validation, the most important areas to test are the new integration and observability paths rather than only root-cause quality.[cite:1][cite:32] A strong regression plan should validate chat metering, EventBridge event emission, CloudWatch metric publication, log delivery activation, and IAM behavior for upgraded preview environments.[cite:32][cite:42][cite:43]

### Suggested validation checklist
- Verify `ConsumedChatRequests` appears in CloudWatch after using chat.[cite:32]
- Confirm EventBridge receives `aws.aidevops` events for investigation lifecycle changes.[cite:42][cite:47]
- Validate log delivery to CloudWatch Logs, S3, and Firehose where required.[cite:32]
- Confirm CloudTrail captures agent activity in the account.[cite:33]
- If migrating from preview, verify IAM updates and confirm expected loss of preview-era on-demand chat history.[cite:43]

## Bottom Line
Since GA, AWS DevOps Agent has become more operationally complete: it now has documented event-driven automation through EventBridge, formal vended logs and metrics, clearer AWS-native observability hooks, and tighter controls around chat history and access.[cite:1][cite:32][cite:42][cite:43] For most platform teams, the biggest practical change is that the service is no longer just an investigation interface; it is now easier to treat as a monitored, automated, and auditable part of the broader AWS operations stack.[cite:1][cite:32][cite:33]
