# Portable monitoring demo

This directory deploys Grafana, Prometheus, Loki and Alloy to an existing Kubernetes cluster using local Kustomize manifests. All application manifests are handwritten. Extract the ZIP and deploy its files directly; no source repository or controller bootstrap is required.

Prerequisites: a working Kubernetes cluster, an authenticated admin `kubectl` context, Python 3 and Make. Nodes need access to the public container registries. Running tests also requires access to PyPI to install pytest.

## Create a local kind cluster

Install Docker, kind and kubectl first, and start Docker before creating the cluster. On macOS, kind and kubectl can be installed with `brew install kind kubectl`. Python 3 and Make must also be available.

```sh
kind create cluster --name grafana-assessment --wait 120s
kubectl config use-context kind-grafana-assessment
kubectl get nodes
```

The node should show `Ready`. These commands create a local cluster; they do not require a cloud account. If this named cluster already exists, skip creation and select its context. See the [official kind quick start](https://kind.sigs.k8s.io/docs/user/quick-start/) for installation on other platforms.

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

## Storage: local kind compared with GKE

| Setup | Storage used | Persistence and limitations |
| --- | --- | --- |
| This standalone directory on kind or GKE | `emptyDir`, backed by node storage | Data survives a container restart within the same pod, but is lost when the pod is removed or replaced. Available node disk space limits history; no persistent capacity is reserved. |
| Separate cloud deployment | PVCs using GKE's `standard-rwo` StorageClass: Grafana 2 GiB, Prometheus 10 GiB, Loki 5 GiB | Persistent Disk storage survives pod replacement while the claims and disks remain. It incurs cloud storage charges; deleting a claim can delete its disk according to the reclaim policy. |

The difference comes from the volume configuration, not simply from running on GKE. Deploying this standalone directory onto GKE still uses ephemeral storage. Its `emptyDir` data survives the container restart seen during the Grafana crash, but not a deployment rollout that replaces the pod. See [Kubernetes volume lifetimes](https://kubernetes.io/docs/concepts/storage/volumes/#emptydir).

kind can also use persistent volumes, but GKE's `standard-rwo` class is not available there. Local persistence requires a suitable local provisioner or explicitly configured volumes. Storage kept inside kind's node containers should not be treated as durable across cluster deletion; preserving data outside the cluster requires a separate host-storage arrangement. For a longer-lived installation, I would add a configurable PVC storage option and backups rather than rely on this demo's ephemeral history. See [GKE persistent volume provisioning and reclaim policies](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/persistent-volumes).

## Challenges and reflection

The first kind deployment appeared to hang while downloading images. Grafana's image took about 68 seconds to pull, and the deployment script buffered rollout output. The script now prints pod status, explains the initial wait and streams each application's rollout progress. This makes startup delays easier to distinguish from failed pods.

Grafana initially had a 512 MiB memory limit. During dashboard loading, Kubernetes reported `OOMKilled` with exit code 137 and restarted the container. That interrupted the port-forward, producing connection-refused errors, a failed application-files page and dashboard requests showing no data. Raising the limit to 1 GiB resolved the observed failure. All five integration tests then passed on kind, and the browser dashboard query endpoint returned all eight panel results without errors. This verifies the demonstrated workload; it is not a sustained load test or a guarantee that 1 GiB fits every Grafana installation.

After a pod restart interrupts forwarding, restart `make forward` and refresh the browser. For diagnosis, use:

```sh
kubectl -n monitoring get pods
kubectl -n monitoring describe pod -l app=grafana
kubectl -n monitoring logs deployment/grafana --previous --tail=50
```

The previous-log command is useful when a container has restarted. In a longer-lived setup, I would measure memory during representative dashboard use before choosing limits, and check restart counts as well as application health. The initial API health checks alone did not prove that the browser workload would fit the memory limit.

### Handwritten manifests compared with Helm charts

Writing the application manifests by hand made every resource and its purpose visible, but required assembling the connections that a maintained chart would normally express through templates and values. Services must select the correct pod labels and ports; configuration files must become the correct ConfigMap keys and appear at the paths each application expects; the generated password Secret must exist before Grafana starts. Grafana also needs separate provisioning configuration for data sources and dashboards. A Deployment reaching Ready does not prove all those connections work, so the integration tests check actual metric queries and collected logs.

Permissions and storage needed particular care. The containers run without root privileges, so writable data directories need compatible volume ownership, while a read-only root filesystem still requires writable mounts for application data and temporary files. Alloy needs its own ServiceAccount and a namespaced Role to read pod logs. Writing these explicitly helped keep access narrow, but also made those details our responsibility to validate.

The Grafana memory crash showed why handwritten configuration needs runtime validation as well as valid YAML. The initial resource limit allowed startup but failed during dashboard use. A chart would still require resource sizing for this workload; adopting one would not by itself establish a suitable memory limit. Similarly, storage defaults must suit the target cluster rather than be copied from the cloud installation.

The benefit is a small, inspectable submission with no application chart dependency. The cost is ongoing maintenance: image upgrades, configuration compatibility, probes, security settings and provisioning behaviour must be reviewed together. For this assignment, that explicit configuration demonstrates the implementation. For a longer-lived service, I would weigh that maintenance effort against using maintained application charts, keep only necessary overrides, and retain the same integration tests whichever deployment method is chosen.

Ephemeral storage was a deliberate portability tradeoff: reviewers can deploy without a cloud-specific StorageClass, but application history is disposable. Configuration and the dashboard are recreated from the supplied manifests, while collected metrics and logs must accumulate again after pod replacement. CPU rate panels also need several scrape samples before they show useful values.

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

This checks namespace ownership, then deletes the monitoring namespace and its application resources, including the password Secret. A subsequent deploy generates a new password. To remove the local kind cluster entirely:

```sh
kind delete cluster --name grafana-assessment
```

This removes the cluster and its local data. For a cloud cluster, use its infrastructure tooling instead.

Pinned applications: Grafana 13.2.3, Prometheus 3.15.0, Loki 3.7.8 and Alloy 1.20.1. The dashboard demonstrates application metrics and logs; no cluster-wide or business metrics are claimed.
