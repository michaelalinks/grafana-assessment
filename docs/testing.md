# Automated testing

CI renders every Kustomize directory on pull requests and main pushes. It
requires no cloud credentials and checks pytest test discovery without
executing live tests. Live CRD/schema acceptance was separately
checked with server dry runs during deployment; rendering alone does not
prove API acceptance.

Live integration suite prerequisites: Python 3, pip, kubectl and dig;
authenticated kubeconfig for the assessment cluster; internet access.
Run from the repository root:

```sh
python3 -m pip install -r tests/requirements.txt
python3 -m pytest tests/ -v
```

The suite checks Flux/Helm readiness, deployment rollout, public HTTPS health,
all seven metric queries, Loki logs from both demo applications, scrape
targets up, anonymous read-only
permissions, HTTP redirect, public DNS and every
delegated authoritative nameserver against the current central Gateway IP. DNS and health retry for
up to 300 seconds. Override TEST_TIMEOUT, GRAFANA_HOST or DNS_ZONE via the
environment when necessary.

The tests do not read secrets, create probe pods, or require Grafana
administrator credentials. Use only the intended assessment kubeconfig.
Tests return nonzero on failure.

These are integration tests implemented with pytest, rather than
unit tests of custom application logic. No custom application logic exists.
PR validation does not contact the live cluster. Pod replacement/persistence
and full infrastructure recreation remain separate procedures; this suite does not
restart application pods or destroy infrastructure.

Verification (2026-10-06): the original eight live integration tests passed against
GKE/main. The exact-revision gate also passed against main. All ten
Kustomize directories rendered successfully. Network isolation tests and their
probe fixture have since been removed along with the application policies;
the current suite contains seven checks including Loki ingestion.

## GitHub live integration workflow

Live integration tests runs on pushes to main and can be dispatched manually
on main. It waits until every Flux Kustomization is Ready at the triggering
commit (EXPECTED_REVISION), then runs the actual suite. The newest main run
cancels an older one; job timeouts bound interrupted runs. PR validation continues to run without cloud credentials.

Authentication uses GitHub OIDC, GCP Workload Identity Federation and the
existing grafana-assessment service account. No service-account key is required. GKE uses its IAM-protected DNS endpoint. Federation
is restricted to immutable repository/owner IDs, main, this exact workflow
and push/manual events. PR workflows cannot authenticate.

One-time setup: apply the ignored Terraform changes before merging. They
configure GitHub federation and grant the existing shared service account
roles/container.developer. This built-in PoC role permits broad Kubernetes
resource access, including Secrets and deployment writes, across the project.
No custom IAM role or test-specific Kubernetes RBAC is used. Controller RBAC
from Helm charts and ExternalDNS ListenerSet permissions remain necessary.

Workflow identifiers are supplied by GitHub repository secrets:
GCP_PROJECT_ID, GCP_WORKLOAD_IDENTITY_PROVIDER, GCP_SERVICE_ACCOUNT,
GKE_CLUSTER_NAME, GKE_CLUSTER_LOCATION. These identifiers are configuration,
not service-account keys. Authentication remains keyless. The local Terraform
output github_workload_identity_provider provides the provider identifier.

Terraform injects GCP_PROJECT_ID and GCP_SERVICE_ACCOUNT into the bootstrap
root Kustomization. Root substitution passes them into the relevant child
Kustomizations, which substitute controller annotations and project settings.
No project/account identifier is stored in committed manifests. No manually
created Kubernetes config Secret or extra secret-manager dependency is needed.

Terraform validation/plan, Kustomize rendering, and local tests are checked
before merge. Full GitHub federation and IAM authorization still require
verification after Terraform apply and merge. For a future project/cluster
recreation, update the GitHub secrets from the new Terraform outputs.
Official action guidance:
- <https://github.com/google-github-actions/auth>
- <https://github.com/google-github-actions/auth/blob/main/docs/SECURITY_CONSIDERATIONS.md>
- <https://github.com/google-github-actions/get-gke-credentials>

