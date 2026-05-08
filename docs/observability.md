# Observability

Coorporate Hermes has two observability layers:

- runtime logs for operations and debugging;
- a corporate audit trail for governance-sensitive decisions.

## Runtime Logs

Runtime logs live under `<HERMES_HOME>/logs/`:

```text
agent.log
errors.log
gateway.log
mcp-stderr.log
```

Use:

```bash
coorporate logs
coorporate logs errors
coorporate logs gateway --component gateway
```

## Audit Trail

Audit events are append-only JSONL records. The default file is:

```text
<HERMES_HOME>/logs/audit.jsonl
```

The audit trail records:

- governance file-access denials;
- knowledge approval requests, approvals, and denials;
- cron authorization requests;
- cron approvals and denials;
- dashboard login/logout events;
- dashboard channel-token issuance and denials;
- dashboard role denials;
- mutating dashboard API calls such as config, secret, plugin, cron, and policy changes;
- future migration and policy events that need compliance review.

Inspect it with:

```bash
coorporate logs audit
```

or use the dashboard Logs page and select `audit`.

## Configuration

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

`audit_log_path: ""` uses the default path. Relative paths resolve under `HERMES_HOME`; absolute paths are useful for mounted logging volumes.

`siem_webhook_url` posts each audit event as JSON after local write. Keep it empty until the receiving endpoint is private, authenticated at the network layer, and approved for governance metadata.

## Redaction

When `redact_sensitive_values` is true, metadata keys containing token, secret, password, credential, cookie, private key, or API key are replaced with `[REDACTED]`.

## Current Coverage

Before this corporate layer, the project already had operational logs and optional Langfuse tracing. Those are useful for debugging model/tool behavior, but they are not enough for enterprise governance. The audit trail is the corporate control surface for authorization and policy decisions.

The dashboard Analytics page covers model/session usage. The audit log covers governance decisions. Metrics dashboards and OpenTelemetry export are not yet implemented. If the deployment needs SLOs, latency histograms, token-cost dashboards, or trace correlation across services, add those as a separate telemetry pipeline rather than overloading the audit log.
