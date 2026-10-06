# Portable monitoring demo

This directory deploys Grafana, Prometheus, Loki and Alloy to an existing fresh Kubernetes cluster using Flux and Kustomize. All application manifests are handwritten. No cloud integration, Helm charts, DNS, ingress, certificate controller or external secret controller is installed.

Prerequisites: a working Kubernetes cluster, an authenticated admin `kubectl` context, Python 3 and Make on macOS/Linux (amd64 or arm64). Nodes need outbound access to GitHub and the public container registries. The Git repository must be public; private Git authentication is outside this demonstration.

## Deploy

From the repository root:

```sh
make -C flux-standalone deploy
make -C flux-standalone forward
```

Open **http://localhost:3000** while the forward runs. Anonymous viewing is enabled; administrator access remains password protected. The forward binds only to loopback. Stop it with Ctrl-C.

`deploy` downloads the pinned Flux 2.9.6 CLI and verifies its SHA256 checksum, installs only source-controller and kustomize-controller, creates a random admin-password Secret directly in Kubernetes, then configures Flux to reconcile this directory from Git. It waits for reconciliation. Rerunning preserves the existing password and data in running pods. It refuses a cluster containing another Flux installation or an unrelated monitoring namespace.

To deploy a pushed feature branch or a fork:

```sh
make -C flux-standalone deploy REF=my-branch GIT_URL=https://github.com/example/repository.git
```

This uses the current kubeconfig, including `KUBECONFIG` if set. Check `kubectl config current-context` before deploying. The Makefile is a convenience entry point; it is not required by Kubernetes or Flux. `python3 flux-standalone/bootstrap.py --git-url URL --ref BRANCH` performs the same bootstrap.

## Data and secrets

The portable PoC uses `emptyDir` storage, so it needs no StorageClass. Replacing a pod loses that application's local database/history; the provisioned dashboard/data sources are recreated from Git. This keeps it usable on a cluster without a storage provisioner. The cloud deployment under `flux/` remains separate and retains its PVCs.

The generated administrator password is not written to a file or committed. It is reused on subsequent deployments. If you need admin access, retrieve it yourself from your terminal:

```sh
kubectl -n monitoring get secret grafana-admin -o jsonpath='{.data.admin-password}' | base64 --decode
```

Alloy's namespaced Role permits reading only pods and pod logs in monitoring. It selects only the Grafana/Prometheus applications, then sends those logs to Loki. Other applications do not mount Kubernetes API tokens. Grafana, Prometheus and Loki have internal ClusterIP Services. There are no application NetworkPolicies in this setup.

## Test

```sh
make -C flux-standalone test
```

This creates an ignored local Python environment with pinned pytest and runs five live integration tests. A fixture opens a temporary loopback-only port-forward on an available port and closes it even on failure. The suite checks health, eight provisioned dashboard panels, seven metric queries, both scrape targets, real logs from both applications, denied anonymous administrator access and internal Service types. No public DNS/TLS or GCP authentication is needed beyond the kubeconfig used to access the cluster.

PR CI renders this directory and checks test discovery without contacting a cluster. `make -C flux-standalone render` prints the generated Kubernetes manifests. Expected live status: Flux root Ready, four Deployments Available and the tests passing.

## Remove

```sh
make -C flux-standalone clean
```

Flux prunes the monitoring namespace and its application resources, including the password Secret. Flux controllers remain installed. A subsequent deploy generates a new password. Deleting the entire test cluster is separate; use its infrastructure tooling.

Pinned applications: Grafana 13.2.3, Prometheus 3.15.0, Loki 3.7.8 and Alloy 1.20.1. Configuration follows the existing assessment's metric/log demo; no cluster-wide or business metrics are claimed.
