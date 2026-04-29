<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# Create a Python SDK script to list all ECS services, tasks and respective cluster with last restarted date. Add details like task definition, running count etc. as well.

Export should be in csv format.

Yes — below is a ready-to-use Python boto3 script that exports ECS clusters, services, and tasks to CSV, including cluster name, service name, task definition, desired/running/pending counts, task status fields, and a practical “last restarted” reference. ECS exposes service deployment timestamps via `describe_services` and task lifecycle timestamps such as `createdAt`, `startedAt`, and `stoppedAt` via `describe_tasks`, so the script uses the primary deployment `createdAt` as the best service-level restart indicator and task `startedAt` as the best task-level restart indicator.[^1_1][^1_2]

## Python script

```python
#!/usr/bin/env python3
import argparse
import csv
from datetime import timezone
import boto3
from botocore.config import Config


def dt(v):
    if not v:
        return ""
    if hasattr(v, "astimezone"):
        return v.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return str(v)


def short_name_from_arn(arn: str) -> str:
    if not arn:
        return ""
    return arn.split("/")[-1]


def chunked(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def get_service_last_restart(service):
    deployments = service.get("deployments", []) or []
    primary = next((d for d in deployments if d.get("status") == "PRIMARY"), None)
    if primary:
        return primary.get("createdAt"), "service_primary_deployment_createdAt"

    events = service.get("events", []) or []
    if events:
        return events[^1_0].get("createdAt"), "latest_service_event_createdAt"

    return None, ""


def main():
    parser = argparse.ArgumentParser(description="Export ECS services and tasks to CSV")
    parser.add_argument("--profile", help="AWS profile name")
    parser.add_argument("--region", help="AWS region name")
    parser.add_argument("--clusters", nargs="*", help="Optional cluster names or ARNs")
    parser.add_argument(
        "--output",
        default="ecs_services_tasks_inventory.csv",
        help="Output CSV path",
    )
    args = parser.parse_args()

    session_kwargs = {}
    if args.profile:
        session_kwargs["profile_name"] = args.profile
    if args.region:
        session_kwargs["region_name"] = args.region

    session = boto3.Session(**session_kwargs)
    ecs = session.client("ecs", config=Config(retries={"max_attempts": 10, "mode": "standard"}))
    sts = session.client("sts")

    account_id = sts.get_caller_identity()["Account"]
    region_name = session.region_name or ecs.meta.region_name

    cluster_arns = []
    if args.clusters:
        cluster_arns = args.clusters
    else:
        paginator = ecs.get_paginator("list_clusters")
        for page in paginator.paginate():
            cluster_arns.extend(page.get("clusterArns", []))

    rows = []

    for cluster in cluster_arns:
        service_arns = []
        paginator = ecs.get_paginator("list_services")
        for page in paginator.paginate(cluster=cluster):
            service_arns.extend(page.get("serviceArns", []))

        service_map = {}
        for service_chunk in chunked(service_arns, 10):
            resp = ecs.describe_services(cluster=cluster, services=service_chunk)
            for svc in resp.get("services", []):
                service_map[svc["serviceArn"]] = svc

        task_arns = []
        paginator = ecs.get_paginator("list_tasks")
        for page in paginator.paginate(cluster=cluster):
            task_arns.extend(page.get("taskArns", []))

        task_rows_by_service = {}
        standalone_tasks = []

        for task_chunk in chunked(task_arns, 100):
            resp = ecs.describe_tasks(cluster=cluster, tasks=task_chunk)
            for task in resp.get("tasks", []):
                group = task.get("group", "") or ""
                service_name = group.split(":", 1)[^1_1] if group.startswith("service:") else ""

                task_info = {
                    "task_arn": task.get("taskArn", ""),
                    "task_id": short_name_from_arn(task.get("taskArn", "")),
                    "task_definition_arn": task.get("taskDefinitionArn", ""),
                    "task_definition": short_name_from_arn(task.get("taskDefinitionArn", "")),
                    "task_last_status": task.get("lastStatus", ""),
                    "task_desired_status": task.get("desiredStatus", ""),
                    "task_health_status": task.get("healthStatus", ""),
                    "task_launch_type": task.get("launchType", ""),
                    "task_capacity_provider": task.get("capacityProviderName", ""),
                    "task_started_by": task.get("startedBy", ""),
                    "task_created_at": dt(task.get("createdAt")),
                    "task_started_at": dt(task.get("startedAt")),
                    "task_stopping_at": dt(task.get("stoppingAt")),
                    "task_stopped_at": dt(task.get("stoppedAt")),
                    "task_restart_reference": dt(task.get("startedAt") or task.get("createdAt")),
                    "task_restart_reference_basis": "task_startedAt_or_createdAt",
                    "task_stop_code": task.get("stopCode", ""),
                    "task_stopped_reason": task.get("stoppedReason", ""),
                    "availability_zone": task.get("availabilityZone", ""),
                    "platform_version": task.get("platformVersion", ""),
                    "platform_family": task.get("platformFamily", ""),
                    "cpu": task.get("cpu", ""),
                    "memory": task.get("memory", ""),
                    "group": group,
                }

                if service_name:
                    task_rows_by_service.setdefault(service_name, []).append(task_info)
                else:
                    standalone_tasks.append(task_info)

        for service_arn, svc in service_map.items():
            service_name = svc.get("serviceName", "")
            last_restart_at, last_restart_basis = get_service_last_restart(svc)
            related_tasks = task_rows_by_service.get(service_name, [])

            base_service_data = {
                "account_id": account_id,
                "region": region_name,
                "cluster_arn": svc.get("clusterArn", cluster),
                "cluster_name": short_name_from_arn(svc.get("clusterArn", cluster)),
                "service_arn": service_arn,
                "service_name": service_name,
                "service_status": svc.get("status", ""),
                "service_launch_type": svc.get("launchType", ""),
                "service_scheduling_strategy": svc.get("schedulingStrategy", ""),
                "service_deployment_controller": (svc.get("deploymentController") or {}).get("type", ""),
                "desired_count": svc.get("desiredCount", ""),
                "running_count": svc.get("runningCount", ""),
                "pending_count": svc.get("pendingCount", ""),
                "service_task_definition_arn": svc.get("taskDefinition", ""),
                "service_task_definition": short_name_from_arn(svc.get("taskDefinition", "")),
                "service_created_at": dt(svc.get("createdAt")),
                "service_last_restart_at": dt(last_restart_at),
                "service_last_restart_basis": last_restart_basis,
                "deployment_count": len(svc.get("deployments", []) or []),
                "primary_deployment_id": next(
                    (d.get("id", "") for d in (svc.get("deployments", []) or []) if d.get("status") == "PRIMARY"),
                    "",
                ),
                "primary_deployment_status": next(
                    (
                        d.get("rolloutState", d.get("status", ""))
                        for d in (svc.get("deployments", []) or [])
                        if d.get("status") == "PRIMARY"
                    ),
                    "",
                ),
            }

            if not related_tasks:
                row = dict(base_service_data)
                row.update({
                    "task_arn": "",
                    "task_id": "",
                    "task_definition_arn": "",
                    "task_definition": "",
                    "task_last_status": "",
                    "task_desired_status": "",
                    "task_health_status": "",
                    "task_launch_type": "",
                    "task_capacity_provider": "",
                    "task_started_by": "",
                    "task_created_at": "",
                    "task_started_at": "",
                    "task_stopping_at": "",
                    "task_stopped_at": "",
                    "task_restart_reference": "",
                    "task_restart_reference_basis": "",
                    "task_stop_code": "",
                    "task_stopped_reason": "",
                    "availability_zone": "",
                    "platform_version": "",
                    "platform_family": "",
                    "cpu": "",
                    "memory": "",
                    "group": "",
                })
                rows.append(row)
            else:
                for task_info in related_tasks:
                    row = dict(base_service_data)
                    row.update(task_info)
                    rows.append(row)

        for task_info in standalone_tasks:
            row = {
                "account_id": account_id,
                "region": region_name,
                "cluster_arn": cluster,
                "cluster_name": short_name_from_arn(cluster),
                "service_arn": "",
                "service_name": "",
                "service_status": "",
                "service_launch_type": "",
                "service_scheduling_strategy": "",
                "service_deployment_controller": "",
                "desired_count": "",
                "running_count": "",
                "pending_count": "",
                "service_task_definition_arn": "",
                "service_task_definition": "",
                "service_created_at": "",
                "service_last_restart_at": "",
                "service_last_restart_basis": "",
                "deployment_count": "",
                "primary_deployment_id": "",
                "primary_deployment_status": "",
            }
            row.update(task_info)
            rows.append(row)

    fieldnames = [
        "account_id",
        "region",
        "cluster_arn",
        "cluster_name",
        "service_arn",
        "service_name",
        "service_status",
        "service_launch_type",
        "service_scheduling_strategy",
        "service_deployment_controller",
        "desired_count",
        "running_count",
        "pending_count",
        "service_task_definition_arn",
        "service_task_definition",
        "service_created_at",
        "service_last_restart_at",
        "service_last_restart_basis",
        "deployment_count",
        "primary_deployment_id",
        "primary_deployment_status",
        "task_arn",
        "task_id",
        "task_definition_arn",
        "task_definition",
        "task_last_status",
        "task_desired_status",
        "task_health_status",
        "task_launch_type",
        "task_capacity_provider",
        "task_started_by",
        "task_created_at",
        "task_started_at",
        "task_stopping_at",
        "task_stopped_at",
        "task_restart_reference",
        "task_restart_reference_basis",
        "task_stop_code",
        "task_stopped_reason",
        "availability_zone",
        "platform_version",
        "platform_family",
        "cpu",
        "memory",
        "group",
    ]

    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
```


## How it works

`describe_services` returns service-level fields such as `desiredCount`, `runningCount`, `pendingCount`, `taskDefinition`, `createdAt`, `deployments`, and `events`, while `describe_tasks` returns task-level fields such as `taskDefinitionArn`, `createdAt`, `startedAt`, `startedBy`, `stoppedAt`, and status metadata.[^1_2][^1_1]

Because ECS does not expose a single explicit universal field called “last restarted date” for a service, the script uses the primary deployment’s `createdAt` as the best service restart proxy and labels the basis in a separate column; for each task, it uses `startedAt` when present, falling back to `createdAt`.[^1_1][^1_2]

## Run it

Save the script as `ecs_inventory_export.py`, install boto3 if needed, and run one of these commands. The script can scan all clusters with `list_clusters`, enumerate services with `list_services`, and enumerate tasks with `list_tasks`, then write a CSV file.[^1_2][^1_1]

```bash
pip install boto3
python ecs_inventory_export.py --region ap-south-1
```

```bash
python ecs_inventory_export.py --profile myprofile --region ap-south-1 --output ecs_report.csv
```

```bash
python ecs_inventory_export.py --profile myprofile --region ap-south-1 --clusters cluster-a cluster-b --output ecs_report.csv
```


## CSV columns

The export includes service details like cluster, service, deployment controller, service task definition, desired/running/pending counts, plus task details like task ARN, task definition ARN, task status, start/stop timestamps, CPU, memory, and task group. Those fields are all directly available from ECS service and task describe APIs.[^1_1][^1_2]

Two especially useful columns are `service_last_restart_at` and `task_restart_reference`, and each has a matching `*_basis` column so you can tell whether the timestamp came from a deployment creation time, a service event time, or a task start/create time.[^1_2][^1_1]

## Important note

If by “last restarted date” you mean the exact last time someone manually forced a new deployment, ECS service events/history is the closest source, but event messages are not guaranteed to be a perfect long-term audit log through this API response alone. A more precise audit view would typically require CloudTrail lookup of `UpdateService` calls or EventBridge/CloudWatch event history in addition to ECS API data.[^1_3][^1_4][^1_1]

If you want, I can also give you:

- a version that exports one row per service with aggregated task counts,
- a multi-account version using `assume_role`,
- or a pandas-based version that creates both CSV and XLSX.
<span style="display:none">[^1_10][^1_11][^1_12][^1_13][^1_14][^1_15][^1_5][^1_6][^1_7][^1_8][^1_9]</span>

<div align="center">⁂</div>

[^1_1]: https://github.com/boto/boto3/issues/2533

[^1_2]: https://stackoverflow.com/questions/34840137/how-do-i-deploy-updated-docker-images-to-amazon-ecs-tasks

[^1_3]: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/viewing-state-events.html

[^1_4]: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs_service_events.html

[^1_5]: https://docs.aws.amazon.com/boto3/latest/reference/services/ecs/client/describe_task_sets.html

[^1_6]: https://github.com/boto/botocore/issues/1129

[^1_7]: https://stackoverflow.com/questions/42735328/aws-ecs-restart-service-with-the-same-task-definition-and-image-with-no-downtime

[^1_8]: https://github.com/s7anley/aws-ecs-service-stop-lambda/blob/master/main.py

[^1_9]: https://docs.aws.amazon.com/boto3/latest/reference/services/ecs/client/describe_tasks.html

[^1_10]: https://boto3.amazonaws.com/v1/documentation/api/1.35.8/reference/services/ecs/client/describe_services.html

[^1_11]: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ecs/client/describe_tasks.html

[^1_12]: https://stackoverflow.com/questions/60276223/why-does-boto3-clientecs-describe-tasks-not-always-have-a-stopcode

[^1_13]: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ecs/client/describe_services.html

[^1_14]: https://boto3.amazonaws.com/v1/documentation/api/1.35.9/reference/services/ecs/client/describe_tasks.html

[^1_15]: https://www.javierinthecloud.com/solving-the-ecs-task-definition-update-challenge-in-codepipeline-deployments/

