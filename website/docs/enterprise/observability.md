---
title: "Observability"
description: "Runtime logs, corporate audit events, SIEM webhook export, and current telemetry coverage in Maia."
---

# Observability

Maia has runtime logs for operations and an audit trail for governance-sensitive decisions.

Runtime logs:

```text
<MAIA_HOME>/logs/agent.log
<MAIA_HOME>/logs/errors.log
<MAIA_HOME>/logs/gateway.log
```

Audit log:

```text
<MAIA_HOME>/logs/audit.jsonl
```

Use:

```bash
maia logs audit
```

Audit events currently cover governance file-access denials, knowledge approval requests and decisions, cron authorization requests/decisions, dashboard access requests/approvals/denials/revocations/restores, dashboard channel-token issuance and denials, dashboard login/logout, dashboard role denials, and mutating dashboard API calls such as config, secret, plugin, cron, and policy changes.

```yaml
observability:
  enabled: true
  audit_log_enabled: true
  audit_log_path: ""
  redact_sensitive_values: true
  siem_webhook_url: ""
  siem_timeout_seconds: 2
  retention_days: 180
```

Optional Langfuse tracing remains useful for model/tool debugging. Metrics dashboards and OpenTelemetry export are separate future work and should not be mixed with the compliance audit trail.
