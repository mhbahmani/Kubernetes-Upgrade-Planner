# Istio and custom Envoy builds

- Support matrix: https://istio.io/latest/docs/releases/supported-releases/.
  Each minor supports about 4-5 Kubernetes minors, and there is no LTS.
- Upgrade path: https://istio.io/latest/docs/setup/upgrade/. More than two
  minors in one step is not tested. With in-place upgrades (no revisions),
  go one minor at a time.
- Every Istio minor ships a new Envoy minor. For each step:
  - Envoy Go filter plugins (`.so`, `envoy.extensions.filters.http.golang`) are
    tied to the exact Envoy version: bump `github.com/envoyproxy/envoy` in go.mod
    and rebuild.
  - Custom proxy images `FROM istio/proxyv2:<ver>` need rebuilding.
  - Retest EnvoyFilters (`networking.istio.io/v1alpha3`, the only version). Flag
    any without a `proxyVersion` match; they apply to every proxy version.
  - Lua filters rarely break, but test them.
- CRD versions: move `networking.istio.io/v1alpha3` and `v1beta1`
  VirtualService, DestinationRule, ServiceEntry and Gateway to `v1`. Check IaC
  repos that generate them too.
- Kiali follows the Istio version.
- Native sidecars (`ENABLE_NATIVE_SIDECARS`) rely on sidecar containers, which
  are GA in 1.33; retest injection order and Job termination.
- CI images pinned to a kubectl version (for example `alpine/k8s:1.31.x`) must
  follow the cluster (kubectl skew is ±1 minor).
