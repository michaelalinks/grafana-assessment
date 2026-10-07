# Loki logging integration

Loki 3.7.8 uses handwritten manifests, one process, TSDB v13 indexes and
filesystem storage on a 5Gi standard-rwo PVC. The compactor removes logs
older than 72 hours (asynchronously); retention is not a hard disk-size cap.
This is demonstration storage, not replicated or backed up. Recreate avoids
overlapping disk writers. Loki has an internal ClusterIP Service, no route,
no cloud identity and no Kubernetes API token. Its API uses single-tenant
mode without authentication, relying on the chosen internal-only topology.

Grafana Alloy chart 1.13.0 runs image v1.20.1, the latest stable application
release verified when configured. The chart's appVersion is v1.20.0, hence
the explicit image tag. Its official HTTP chart repository is used because
the candidate Grafana GHCR OCI endpoint did not serve this chart.

Alloy runs as one Deployment and tails container logs through Kubernetes'
API. There are no host filesystem mounts or privileged containers. Chart
RBAC is scoped to grafana/monitoring and pods/pods-log reads. Unused PodLogs
CRDs are disabled. Discovery selects only app=grafana or app=prometheus,
so unrelated application/controller logs are not published to anonymous
reviewers. Labels namespace, pod, container and app make queries readable.
The collector forwards logs to Loki's internal /loki/api/v1/push endpoint.

Flux installs Loki after Prometheus creates the monitoring namespace, then
Alloy after Loki is Ready. Grafana depends on Loki and provisions its data
source (UID loki). Its overview dashboard adds a log panel using
{app=~"grafana|prometheus"}. There is no UI configuration or new secret.

Added CPU requests: Loki 50m, Alloy 25m, chart reloader default 10m = 85m.
The existing node had 104m scheduling headroom. Memory limits are 512Mi for
Loki and 256Mi for Alloy. Alloy uses Recreate to avoid surge reservations on
this small node. No node upgrade or Terraform change is needed.

## Verification

Run python3 -m pytest tests/ -v. The suite now also queries Loki through
Grafana and waits for nonempty real log streams from each demo application.
The dashboard API must contain eight panels. Pod/API collection restarts
may replay recent lines; no exactly-once or lossless delivery guarantee is
claimed. Full storage teardown/recreation and long-running retention tests
are not part of this verification.

## References

- <https://grafana.com/docs/loki/latest/configure/examples/configuration-examples/>
- <https://grafana.com/docs/loki/latest/operations/storage/retention/>
- <https://grafana.com/docs/alloy/latest/collect/logs-in-kubernetes/>
- <https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.kubernetes/>
- <https://github.com/grafana/helm-charts/tree/main/charts/alloy>

## Recorded live verification (2026-10-06)

Flux reconciled the feature revision and all seven pytest checks passed,
including nonempty Loki streams for app=grafana and app=prometheus through
Grafana's anonymous datasource proxy. The dashboard has eight provisioned
panels; its seven metric queries still return data. Alloy's tailers opened
both container log streams. Loki's PVC is Bound and all application pods
are Ready without restarts. CPU requests total 1911m/1930m; only 19m remains
for additional pod scheduling. Memory requests use 51% of the node.

Live startup found that this GKE runtime rejects a pod-level primary group
without an explicit user override when creating its sandbox. Applying the
primary group at container level fixes this for Loki and Grafana while
retaining their pinned image UID defaults and volume fsGroup permissions.
A Kubernetes server dry run cannot detect that runtime constraint.
