# Flux bootstrap on GKE

Cluster: grafana-assessment, ${GCP_PROJECT_ID}, europe-west2-a.
Operator chart: 0.61.0. Flux controllers: 2.9.6.
Git source: public https://github.com/michaelalinks/grafana-assessment.git
Branch: main. Path: flux.
No Git authentication secret is required for this public repository.

## Bootstrap and credentials

Run Terraform apply from the ignored terraform-local directory. It installs
Flux and injects environment-specific identifiers into root substitution.
Retrieve the cluster credentials using the command from:

```sh
terraform -chdir=terraform-local output -raw get_credentials_command
```

Do not apply the standalone FluxInstance file directly: Terraform supplies
its environment-specific root substitution patch.

If the auth plugin is not on PATH, add the Google Cloud SDK bin directory
printed by gcloud info to PATH, or set its absolute exec-command in the
GKE kubeconfig user entry. No credentials belong in the Git repository.

The ignored Terraform now owns Flux Operator and FluxInstance bootstrap.
Its Helm releases make the manual bootstrap commands above unnecessary on
new clusters. Flux builds flux/kustomization.yaml. Four controllers are
installed; image automation controllers are omitted because the assignment
does not require them. The temporary iso-flux-test namespace was used to
verify Git-to-Kustomize reconciliation and then removed.

## Verification

```sh
kubectl -n flux-system get fluxinstances,gitrepositories,kustomizations
kubectl -n flux-system get deployments
```

Ready=True on the FluxInstance, GitRepository and Flux Kustomization
confirms successful reconciliation.
FluxInstance owns the initial sync resources. Do not create duplicate
GitRepository/Kustomization objects for the same root path.

The cluster watches main. Merge the bootstrap PR before expecting the
flux/ path to reconcile successfully from main. Delete the implementation
branch only after verifying main reconciliation.
Terraform and local state are excluded by .gitignore.
