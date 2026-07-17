const AUDIT_FIELDS = Object.freeze([
  "model_version",
  "feature_schema_hash",
  "cost_profile_version",
  "training_end_date",
  "source_dates",
  "latest_available_at",
  "data_quality_status",
  "reason_codes",
]);

export function createStockAuditSection() {
  const rows = AUDIT_FIELDS.map(
    (field) => `<div><dt>${field}</dt><dd>—</dd></div>`,
  ).join("");
  return `
    <details class="audit-details">
      <summary>技術稽核資訊</summary>
      <dl class="audit-list">${rows}</dl>
    </details>`;
}
