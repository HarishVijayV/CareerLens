{{/*
Shared label helpers.

Consistent labels are not cosmetic in Kubernetes — a Service finds its Pods by label
selector, so a typo in one template silently produces a Service with no endpoints and a
"why is nothing responding" debugging session. Defining them once removes that class of
bug entirely.

The app.kubernetes.io/* names are the standard recommended set, which is what makes
`kubectl get all -l app.kubernetes.io/instance=careerlens` work.
*/}}

{{- define "careerlens.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}

{{/* Per-component selector. MUST stay stable across upgrades: selectors are immutable
     on an existing Deployment, so changing this later forces a delete + recreate. */}}
{{- define "careerlens.selectorLabels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
