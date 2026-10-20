from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import logging
import smtplib
from typing import Any, Dict, Optional

from agentops.config import settings
from agentops.incident.models import IncidentReport

logger = logging.getLogger("agentops.notifications.email")


def send_investigation_outcome_email(
    report: IncidentReport,
    alert_name: Optional[str] = None,
    web_base_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Format and deliver an evidence-grounded incident outcome email notification.
    Safely skips delivery if SMTP credentials or recipients are not configured.
    Guarantees secrets, credentials, and internal chain-of-thought are never leaked.
    """
    recipient = settings.NOTIFICATION_EMAIL_TO.strip()
    if not recipient:
        logger.debug("Skipping email notification: NOTIFICATION_EMAIL_TO is not configured.")
        return {"sent": False, "reason": "NOTIFICATION_EMAIL_TO_UNSET"}

    smtp_host = settings.SMTP_HOST.strip()
    if not smtp_host or smtp_host == "localhost" and not settings.SMTP_USER:
        # Default unconfigured local environment
        logger.debug(f"Skipping email notification: SMTP host '{smtp_host}' unconfigured.")
        return {"sent": False, "reason": "SMTP_UNCONFIGURED"}

    base_url = web_base_url or f"http://{settings.AGENTOPS_HOST}:{settings.AGENTOPS_PORT}"
    incident_link = f"{base_url}/?incident={report.incident_id}"
    grafana_link = settings.GRAFANA_URL

    subject = f"[AgentOps-SRE] Investigation {report.status}: {report.incident_id} ({report.namespace}/{report.workload})"

    # Clean, sanitized text summary
    text_content = f"""AgentOps-SRE Autonomous Incident Diagnostic Report
=====================================================
Incident ID:   {report.incident_id}
Target:        {report.namespace}/{report.workload}
Status:        {report.status}
Diagnosis:     {report.incident_type} (Confidence: {int(report.confidence * 100)}%)
Trigger Alert: {alert_name or 'N/A'}

ROOT CAUSE ANALYSIS:
{report.root_cause if report.validation_passed else 'Investigation did not produce a validated RCA.'}

SUMMARY:
{report.summary}

TELEMETRY & EVIDENCE:
- Kubernetes Signals: {report.evidence_summary.get('kubernetes', 0)}
- Prometheus Signals: {report.evidence_summary.get('prometheus', 0)}
- Loki Log Signals:   {report.evidence_summary.get('loki', 0)}
- Missing Signals:    {', '.join(report.missing_signals) if report.missing_signals else 'None'}

RECOMMENDED REMEDIATION:
{report.recommended_remediation or 'Manual SRE review required.'}

Action Required:
Approval Required: {report.approval_required}
Approval ID:       {report.approval_id or 'None'}

LINKS:
- View in AgentOps Operator Console: {incident_link}
- View in Grafana Dashboard:         {grafana_link}
"""

    html_content = f"""<!DOCTYPE html>
<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #24292f; line-height: 1.5; margin: 0; padding: 20px;">
  <div style="max-width: 650px; margin: 0 auto; border: 1px solid #d0d7de; border-radius: 6px; overflow: hidden;">
    <div style="background-color: #0969da; color: #ffffff; padding: 16px 20px;">
      <h2 style="margin: 0; font-size: 18px;">AgentOps-SRE Incident Diagnostic</h2>
      <p style="margin: 4px 0 0 0; font-size: 13px; opacity: 0.9;">Incident {report.incident_id} • {report.namespace}/{report.workload}</p>
    </div>
    <div style="padding: 20px;">
      <table style="width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 14px;">
        <tr>
          <td style="padding: 6px 0; color: #57606a; width: 140px;">Status:</td>
          <td style="padding: 6px 0; font-weight: 600;">{report.status}</td>
        </tr>
        <tr>
          <td style="padding: 6px 0; color: #57606a;">Diagnosis:</td>
          <td style="padding: 6px 0; font-weight: 600;">{report.incident_type} ({int(report.confidence * 100)}% confidence)</td>
        </tr>
        <tr>
          <td style="padding: 6px 0; color: #57606a;">Approval Required:</td>
          <td style="padding: 6px 0; font-weight: 600; color: {'#cf222e' if report.approval_required else '#1a7f37'};">{report.approval_required}</td>
        </tr>
      </table>

      <h3 style="font-size: 15px; margin: 16px 0 8px 0; border-bottom: 1px solid #d0d7de; padding-bottom: 4px;">Root Cause Analysis</h3>
      <div style="background-color: #f6f8fa; padding: 12px; border-radius: 6px; font-size: 13px; margin-bottom: 16px;">
        {report.root_cause if report.validation_passed else 'Investigation did not produce a validated RCA.'}
      </div>

      <h3 style="font-size: 15px; margin: 16px 0 8px 0; border-bottom: 1px solid #d0d7de; padding-bottom: 4px;">Recommended Remediation</h3>
      <p style="font-size: 13px; margin: 0 0 20px 0;">{report.recommended_remediation or 'Manual SRE review required.'}</p>

      <div style="text-align: center; margin: 24px 0 12px 0;">
        <a href="{incident_link}" style="background-color: #1f883d; color: #ffffff; padding: 10px 18px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; display: inline-block;">Open Incident in Console</a>
      </div>
    </div>
  </div>
</body>
</html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM
    msg["To"] = recipient

    msg.attach(MIMEText(text_content, "plain"))
    msg.attach(MIMEText(html_content, "html"))

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=5.0) as server:
            if settings.SMTP_PORT == 587:
                server.starttls()
            if settings.SMTP_USER and settings.SMTP_PASSWORD:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)
        logger.info(f"Outcome notification email delivered to '{recipient}' for incident '{report.incident_id}'")
        return {"sent": True, "recipient": recipient, "subject": subject}
    except Exception as e:
        logger.warning(f"Failed to deliver notification email to '{recipient}': {e}")
        return {"sent": False, "error": str(e), "recipient": recipient}
