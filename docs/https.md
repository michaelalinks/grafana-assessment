# Shared Gateway and application HTTPS

One Envoy Gateway and one cloud load balancer serve all applications.
Gateway public in envoy-gateway-system owns the shared HTTP listener and
accepts ListenerSets from namespaces labelled:
  healthtech.michaelalinks.com/gateway: public
The central Gateway contains no application hostnames or TLS certificates.

Each application's ListenerSet attaches to Gateway public and declares its
HTTPS hostname and local TLS Secret. Its HTTPS HTTPRoute references that
local ListenerSet, which shares the central Gateway's IP and data plane.
The application also owns its HTTP-to-HTTPS redirect route, referencing the
central Gateway's HTTP listener. No wildcard certificate is required.

## Compact configuration

flux/installs/cert-manager/cert-manager.yaml groups the namespace, chart
source, Helm release and ESO email reference. The cert-manager Flux
Kustomization waits for both the Helm release and email synchronization.
config/issuer.yaml uses Flux substitution from Secret acme-email. It waits
for cert-manager before registering the Cloud DNS ACME issuer.
flux/installs/grafana/networking.yaml groups Grafana's namespace, Certificate,
ListenerSet and redirect route. The actual Grafana deployment and backend
HTTPRoute will be added to this application folder in the next task.
The certificate and its TLS Secret now belong to the grafana namespace.
An explicit Certificate avoids enabling extra cert-manager shim features.

## Identity and DNS

cert-manager, ESO and ExternalDNS use the same GCP service account through
GKE Workload Identity; there are no JSON keys. ESO retrieves email-account
from Google Secret Manager. Its actual value stays outside Git but appears
in the live Secret and ClusterIssuer as required by cert-manager.
cert-manager generates private keys inside Kubernetes and renews certificates.
ExternalDNS supports ListenerSet parents via --gateway-listener-sets and
read-only ListenerSet RBAC. It resolves their shared Gateway's public IP.
No additional Gateway, load balancer or secret-copying controller is needed.

## Verification

```sh
kubectl -n flux-system get kustomizations
kubectl -n grafana get certificates,listenersets,httproutes
kubectl get gateways -A
curl -I http://grafana.healthtech.michaelalinks.com
curl -I https://grafana.healthtech.michaelalinks.com
```
Expect one Gateway, a Ready certificate, a Programmed ListenerSet, HTTP 301
and trusted HTTPS. HTTPS returns 404 until Grafana's backend is installed.
After merging, the ignored Terraform apply restores Flux sync to main.

Verified on 2026-10-04: all Flux Kustomizations Ready, one Gateway and one
LoadBalancer Service, local Certificate Ready and ListenerSet Programmed.
A temporary application HTTPRoute attached to the local ListenerSet served
a 302 over trusted HTTPS and was removed. The persistent HTTP route returned
301 to HTTPS. The obsolete central certificate Secret was removed.
