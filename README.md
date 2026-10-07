# Grafana assessment

Two implementations demonstrate Grafana with Prometheus metrics and Loki logs:

- **GKE deployment:** [`flux/`](flux/) provides a publicly accessible, continuously reconciled installation at [grafana.healthtech.michaelalinks.com](https://grafana.healthtech.michaelalinks.com).
- **Local bootstrap:** [`grafana-bootstrap/`](grafana-bootstrap/README.md) is a self-contained ZIP-friendly installation for kind or another Kubernetes cluster, accessed through port-forwarding.

## GKE setup and design

Local, ignored Terraform provisions a small single-node GKE Standard cluster, networking, a Cloud DNS zone, IAM/Workload Identity bindings and the initial Flux installation. Infrastructure is applied separately; Terraform files, state and credentials are not part of the submission. Project and service-account settings are supplied to Flux through bootstrap substitutions rather than hardcoded into application manifests.

Flux reads `flux/` from the repository's main branch. Its Kustomizations order dependent installations, wait for readiness and prune resources removed from configuration. Application changes therefore roll out from merged commits without another Terraform apply. Grafana, Prometheus and Loki use handwritten manifests; supporting controllers and Alloy use pinned published Helm charts managed by Flux.

| Component | Design choice |
| --- | --- |
| External Secrets Operator (ESO) | Reads the Grafana administrator password and ACME contact email from GCP Secret Manager into Kubernetes Secrets. Secret values stay outside source control. |
| Workload Identity | Lets ESO, ExternalDNS and cert-manager authenticate to GCP without storing service-account keys. A shared GCP service account keeps this PoC small; separate identities would provide stronger isolation for a larger deployment. |
| ExternalDNS | Watches Gateway API HTTPRoutes and maintains Cloud DNS records for the delegated `healthtech.michaelalinks.com` zone. Domain and zone filters constrain its scope; TXT records identify the records it manages. |
| Envoy Gateway | Provides one central public Gateway and load balancer. Grafana owns its HTTPRoutes and HTTPS ListenerSet in its namespace, so the central Gateway needs no wildcard hostname. Namespace labels control which namespaces can attach. |
| cert-manager | Obtains and renews the Grafana HTTPS certificate through Let's Encrypt DNS-01 validation in Cloud DNS. HTTP redirects to HTTPS. |
| Prometheus, Loki and Alloy | Prometheus scrapes Grafana and itself; Alloy collects their pod logs and sends them to Loki. Data sources and the eight-panel dashboard are provisioned from configuration. |

Grafana permits anonymous viewing while administrator access remains password protected. Prometheus and Loki use internal ClusterIP Services; only Grafana has a public route. This controls public exposure but does not provide network isolation between workloads inside the cluster.

Initial manual steps are applying Terraform, adding Secret Manager values, and delegating the child DNS zone at the domain registrar using its Cloud DNS nameservers. GitHub live tests also require the configured federation settings in Actions secrets. Controllers manage subsequent DNS, certificate and application reconciliation.

## Durability compared with the bootstrap

The GKE deployment uses `standard-rwo` PersistentVolumeClaims: 2 GiB for Grafana, 10 GiB for Prometheus and 5 GiB for Loki. Data survives pod replacement while the claims and disks remain. Git-backed configuration and Secret Manager also allow the desired application setup and credentials to be restored after redeployment.

The bootstrap applies local files directly, generates its password in Kubernetes and uses `emptyDir` storage. It needs no cloud services or source repository, but configuration changes require rerunning `make deploy`, and replacing pods loses their local history. Running the bootstrap on GKE does not change that storage behaviour.

The cloud version is more durable, but remains a single-node, single-replica PoC. Persistent disks are not backups; deleting claims can delete their disks, and node outages or rollouts can interrupt service. High availability and backup/recovery testing would be additional work.

## Validation

PR checks render Kustomize configurations and collect tests. The GKE live workflow runs after pushes to main or a manual trigger, authenticates through GitHub federation, and checks reconciliation, DNS, HTTPS, dashboard metrics, logs and anonymous access restrictions. Its tests are in [`tests/`](tests/).

For the bootstrap's kind setup, deployment commands, five local integration tests and implementation challenges, see its [installation guide](grafana-bootstrap/README.md).
