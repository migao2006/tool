import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { readDailyReport } from "../src/daily-market-report.js";

const root = resolve(fileURLToPath(new URL("..", import.meta.url)));
const output = resolve(root, "public/data/daily-report.json");
const report = await readDailyReport({ force: true });

await mkdir(dirname(output), { recursive: true });
await writeFile(output, `${JSON.stringify(report, null, 2)}\n`, "utf8");

console.log(JSON.stringify({
  message: "Daily market report updated",
  dataDate: report.dataDate,
  generatedAt: report.generatedAt,
  mode: report.mode,
}));
