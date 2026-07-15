import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { createServer } from "node:http";
import { extname, isAbsolute, relative as relativePath, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { handleMarketData, healthPayload } from "../src/market-data.js";

const root = resolve(fileURLToPath(new URL("../public", import.meta.url)));
const port = Number(process.env.PORT || 4173);
const types = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".webmanifest": "application/manifest+json; charset=utf-8",
  ".svg": "image/svg+xml; charset=utf-8",
};

async function sendWebResponse(response, res) {
  res.statusCode = response.status;
  response.headers.forEach((value, key) => res.setHeader(key, value));
  res.end(Buffer.from(await response.arrayBuffer()));
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url || "/", `http://${req.headers.host || `localhost:${port}`}`);
  if (url.pathname === "/api/market-data") {
    await sendWebResponse(await handleMarketData(new Request(url), url), res);
    return;
  }
  if (url.pathname === "/api/health") {
    res.setHeader("content-type", "application/json; charset=utf-8");
    res.end(JSON.stringify(healthPayload()));
    return;
  }
  const relative = url.pathname === "/" ? "index.html" : decodeURIComponent(url.pathname).replace(/^\/+/, "");
  const path = resolve(root, relative);
  const pathFromRoot = relativePath(root, path);
  if (pathFromRoot.startsWith("..") || isAbsolute(pathFromRoot)) {
    res.statusCode = 403;
    res.end("Forbidden");
    return;
  }
  try {
    const info = await stat(path);
    if (!info.isFile()) throw new Error("not a file");
    res.setHeader("content-type", types[extname(path)] || "application/octet-stream");
    res.setHeader("cache-control", url.pathname.startsWith("/data/") ? "no-store" : "no-cache");
    createReadStream(path).pipe(res);
  } catch {
    res.statusCode = 404;
    res.end("Not found");
  }
});

server.listen(port, "127.0.0.1", () => {
  console.log(`Taiwan Stock Smart Picker dev server: http://127.0.0.1:${port}`);
});
