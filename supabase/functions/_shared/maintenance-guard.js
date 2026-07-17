export const MAINTENANCE_SKIP_REASON = "maintenance";
export const MAINTENANCE_GUARD_ERROR_REASON = "maintenance_guard_unavailable";

export async function maintenanceDisposition(rest) {
  try {
    const { data } = await rest("rpc/twss_is_maintenance", {
      method: "POST",
      body: {},
    });
    if (data === true) {
      return { blocked: true, status: 202, reason: MAINTENANCE_SKIP_REASON };
    }
    if (data === false) return { blocked: false, status: 200, reason: null };
    throw new Error("maintenance RPC returned a non-boolean value");
  } catch (error) {
    console.error("[maintenance-guard] fail-closed", {
      name: error?.name || "Error",
      message: String(error?.message || error).slice(0, 180),
    });
    return { blocked: true, status: 503, reason: MAINTENANCE_GUARD_ERROR_REASON };
  }
}

export function maintenanceSkipPayload(disposition) {
  return {
    ok: false,
    status: "skipped",
    reason: disposition?.reason || MAINTENANCE_SKIP_REASON,
  };
}
