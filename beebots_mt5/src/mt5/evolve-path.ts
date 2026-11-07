import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

/** `evolve/lib/recovery.py` beside `beebots_mt5` (`/workspace/evolve/...` on the box). Not process.cwd(). */
export function evolveRecoveryScript(): string {
  const here = dirname(fileURLToPath(import.meta.url));
  const candidates = [
    process.env.EVOLVE_ROOT ? join(process.env.EVOLVE_ROOT, "lib", "recovery.py") : "",
    "/workspace/evolve/lib/recovery.py",
    join(here, "../../../evolve/lib/recovery.py"),
  ].filter((p) => p.length > 0);
  const hit = candidates.find((p) => existsSync(p));
  if (!hit) throw new Error(`recovery.py not found (tried ${candidates.join(", ")})`);
  return hit;
}
