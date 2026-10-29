// The owner password: picked on the Setup page, stored only as a salted scrypt hash, and required for every write from
// the public dashboard (joining or leaving the Hive). Wrong passwords are counted per client address; too many and the
// gate locks for that address for a while, so it cannot be guessed from the page, and a stranger guessing cannot lock
// the owner out.
import { randomBytes, scryptSync, timingSafeEqual } from "node:crypto";
import type { IncomingMessage, ServerResponse } from "node:http";
import { log } from "./log.js";
import { clientAddr } from "./visitors.js";

const MAX_BAD = 8;
const LOCKOUT_MS = 15 * 60_000;
/** Addresses with wrong tries remembered at once; past this the oldest unlocked ones are forgotten. */
const MAX_ADDRS = 10_000;
export const MIN_PASSWORD = 8;
export const MAX_PASSWORD = 200;

// scrypt cost: N=2^15, r=8, p=1 (about 32 MB and ~50 ms per check). Stored with the hash so it can change later.
const N = 1 << 15;
const R = 8;
const P = 1;
const KEYLEN = 32;
const maxmem = 128 * N * R * 2;

/** "scrypt$N$r$p$<salt b64>$<hash b64>". */
export function hashPassword(password: string): string {
  const salt = randomBytes(16);
  const hash = scryptSync(password.normalize("NFKC"), salt, KEYLEN, { N, r: R, p: P, maxmem });
  return ["scrypt", N, R, P, salt.toString("base64"), hash.toString("base64")].join("$");
}

export function verifyPassword(password: string, stored: string): boolean {
  const [kind, n, r, p, salt, hash] = stored.split("$");
  if (kind !== "scrypt" || !salt || !hash) return false;
  const want = Buffer.from(hash, "base64");
  // A truncated or empty stored hash must never match (an empty digest would compare equal to anything).
  if (want.length < 16 || !(Number(n) >= 1024 && Number(r) >= 1 && Number(p) >= 1)) return false;
  try {
    const got = scryptSync(password.normalize("NFKC"), Buffer.from(salt, "base64"), want.length, { N: Number(n), r: Number(r), p: Number(p), maxmem: 128 * Number(n) * Number(r) * 2 });
    return got.length === want.length && timingSafeEqual(got, want);
  } catch {
    return false;
  }
}

export class PasswordGate {
  private tries = new Map<string, { bad: number; lockedUntil: number }>();

  /** `hash` is read on every check (null = no owner password set). `what` names the gate in the lockout log line. */
  constructor(
    private header: string,
    private hash: () => string | null,
    private what: string,
    private now: () => number = Date.now,
  ) {}

  /** Whether this request's client address is locked out. */
  lockedFor(req: IncomingMessage): boolean {
    return this.now() < (this.tries.get(addrOf(req))?.lockedUntil ?? 0);
  }

  get set(): boolean {
    return this.hash() !== null;
  }

  check(req: IncomingMessage): "ok" | "bad" | "locked" | "unset" {
    const addr = addrOf(req);
    if (this.lockedFor(req)) return "locked";
    const h = this.hash();
    if (!h) return "unset";
    const given = String(req.headers[this.header] ?? "");
    // Headers are latin-1 on the wire: the page sends the password URI-encoded so any character survives.
    let pw = given;
    try {
      pw = decodeURIComponent(given);
    } catch {
      /* not encoded: use as is */
    }
    if (pw.length >= MIN_PASSWORD && pw.length <= MAX_PASSWORD && verifyPassword(pw, h)) {
      this.tries.delete(addr);
      return "ok";
    }
    const t = this.tries.get(addr) ?? this.remember(addr);
    if (++t.bad >= MAX_BAD) {
      t.bad = 0;
      t.lockedUntil = this.now() + LOCKOUT_MS;
      log.warn(`${this.what} locked for 15 minutes for one address after repeated wrong passwords`);
    }
    return "bad";
  }

  private remember(addr: string) {
    if (this.tries.size >= MAX_ADDRS) {
      const now = this.now();
      for (const [a, t] of this.tries) if (t.lockedUntil <= now) this.tries.delete(a);
      // Still full: every entry is a live lockout. Forget the oldest rather than grow without bound.
      if (this.tries.size >= MAX_ADDRS) this.tries.delete(this.tries.keys().next().value!);
    }
    const t = { bad: 0, lockedUntil: 0 };
    this.tries.set(addr, t);
    return t;
  }
}

const addrOf = (req: IncomingMessage) => clientAddr(req.headers["x-forwarded-for"], req.socket.remoteAddress);

export function send(res: ServerResponse, status: number, body: unknown) {
  res.writeHead(status, { "content-type": "application/json", "cache-control": "no-store" });
  res.end(JSON.stringify(body));
}

export async function readJson(req: IncomingMessage, maxBytes: number): Promise<unknown> {
  let size = 0;
  const chunks: Buffer[] = [];
  for await (const c of req) {
    size += (c as Buffer).length;
    if (size > maxBytes) throw new Error("body too large");
    chunks.push(c as Buffer);
  }
  return chunks.length ? JSON.parse(Buffer.concat(chunks).toString("utf8")) : {};
}
