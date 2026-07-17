import {
  MAINTENANCE_RETRY_AFTER_SECONDS,
  maintenanceDocument,
  maintenancePayload,
} from "../src/maintenance-mode.js";

export default function handler(request, response) {
  const state = { enabled: true, phase: "maintenance" };
  response.setHeader("Cache-Control", "no-store, no-cache, max-age=0, must-revalidate");
  response.setHeader("Retry-After", String(MAINTENANCE_RETRY_AFTER_SECONDS));
  response.setHeader("X-Robots-Tag", "noindex, nofollow");
  response.setHeader("X-Maintenance-Phase", state.phase);

  if (request.headers.accept?.includes("text/html")) {
    response.setHeader("Content-Type", "text/html; charset=utf-8");
    return response.status(503).send(maintenanceDocument(state));
  }

  return response.status(503).json(maintenancePayload(state));
}
