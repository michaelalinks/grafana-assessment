# Portable monitoring demo

This directory deploys Grafana, Prometheus, Loki and Alloy to an existing Kubernetes cluster using local Kustomize manifests. All application manifests are handwritten. Extract the ZIP and deploy its files directly; no source repository or controller bootstrap is required.

Prerequisites: a working Kubernetes cluster, an authenticated admin `kubectl` context, Python 3 and Make. Nodes need access to the public container registries. Running tests also requires access to PyPI to install pytest.

## Deploy

In the extracted directory containing this README and Makefile:

```sh
make deploy
make forward
```

Open **http://localhost:3000** while the forward runs. Anonymous viewing is enabled; administrator access remains password protected. The forward binds only to loopback. Stop it with Ctrl-C.

`deploy` creates a random admin-password Secret directly in Kubernetes, applies the local manifests with `kubectl apply -k`, and waits for all four Deployments. Rerunning preserves the existing password and data in running pods. It refuses an unrelated monitoring namespace. After editing configuration, rerun `make deploy` to apply it; configuration is not automatically reconciled.

This uses the current kubeconfig, including `KUBECONFIG` if set. Check `kubectl config current-context` before deploying. The Makefile provides convenient commands; `python3 bootstrap.py deploy` performs the same deployment.

## Data and secrets

The portable PoC uses `emptyDir` storage, so it needs no StorageClass. Replacing a pod loses that application's local database/history; the provisioned dashboard and data sources are loaded from the mounted configuration. This keeps it usable on a cluster without a storage provisioner.

The generated administrator password is not written to a file. It is reused on subsequent deployments. If you need admin access, retrieve it yourself from your terminal:

```sh
kubectl -n monitoring get secret grafana-admin -o jsonpath='{.data.admin-password}' | base64 --decode
```

Alloy's namespaced Role permits reading only pods and pod logs in monitoring. It selects only the Grafana/Prometheus applications, then sends those logs to Loki. Other applications do not mount Kubernetes API tokens. Grafana, Prometheus and Loki have internal ClusterIP Services. There are no application NetworkPolicies in this setup.

## Test

```sh
make test
```

This creates a local Python environment with pinned pytest and runs five live integration tests. A fixture opens a temporary loopback-only port-forward on an available port and closes it even on failure. The suite checks health, eight provisioned dashboard panels, seven metric queries, both scrape targets, real logs from both applications, denied anonymous administrator access and internal Service types. No public DNS/TLS or cloud authentication is needed beyond the kubeconfig used to access the cluster.

`make render` prints the generated Kubernetes manifests. Expected live status: four Deployments Available and all five tests passing. Validated on a fresh kind cluster: all five integration tests passed. Grafana uses a 1 GiB memory limit after the initial 512 MiB limit caused an out-of-memory restart during dashboard loading.

## Remove

```sh
make clean
```

This checks namespace ownership, then deletes the monitoring namespace and its application resources, including the password Secret. A subsequent deploy generates a new password. Deleting the entire cluster is separate; use its infrastructure tooling.

Pinned applications: Grafana 13.2.3, Prometheus 3.15.0, Loki 3.7.8 and Alloy 1.20.1. The dashboard demonstrates application metrics and logs; no cluster-wide or business metrics are claimed.
