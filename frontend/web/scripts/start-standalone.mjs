// Runs the production standalone server exactly like the Docker image does:
// static assets and public/ are copied next to server.js, then server.js is started.
import { cpSync, existsSync } from "node:fs";
import { spawn } from "node:child_process";

const root = new URL("..", import.meta.url).pathname;
const standalone = `${root}.next/standalone`;
if (!existsSync(`${standalone}/server.js`)) {
  console.error("No standalone build found. Run `npm run build` first.");
  process.exit(1);
}
cpSync(`${root}.next/static`, `${standalone}/.next/static`, { recursive: true });
cpSync(`${root}public`, `${standalone}/public`, { recursive: true });

const child = spawn(process.execPath, [`${standalone}/server.js`], {
  stdio: "inherit",
  env: { NEXT_TELEMETRY_DISABLED: "1", ...process.env },
});
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => child.kill(signal));
child.on("exit", (code) => process.exit(code ?? 0));
