export default function handler(_request, response) {
  response.setHeader("Cache-Control", "no-store, max-age=0");
  response.status(503).json({
    ok: false,
    code: "MAINTENANCE",
    message: "系統升級中，請稍後再試。",
  });
}
