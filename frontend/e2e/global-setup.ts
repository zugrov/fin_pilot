import { execSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

export default function globalSetup(): void {
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
  const port = process.env.TEST_PG_PORT ?? "5432";
  execSync("uv run python -m tests.e2e.prepare", {
    cwd: path.join(root, "backend"),
    stdio: "inherit",
    env: { ...process.env, TEST_PG_PORT: port },
  });
}
