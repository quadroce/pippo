import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * A UTF-8 byte order mark at the start of a file is invisible and breaks things: Postgres rejects a migration
 * that starts with one, Prisma cannot read a `migration_lock.toml` that starts with one, and `JSON.parse`
 * fails on the seed data. It crept in through PowerShell's `Set-Content -Encoding utf8`; this keeps it out.
 */
const ROOTS = ["web", "agent", "docs"].map((d) => join(__dirname, "..", "..", d));
const SKIP = new Set(["node_modules", ".next", ".venv", "__pycache__", "models", "reports", "discovery", "profiles", "logs", ".git", "pips-cache"]);
const TEXT = /\.(ts|tsx|js|mjs|json|md|sql|toml|yaml|yml|py|ps1|prisma|css|txt|env|example)$/i;

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    if (SKIP.has(name)) continue;
    const full = join(dir, name);
    if (statSync(full).isDirectory()) walk(full, out);
    else if (TEXT.test(name)) out.push(full);
  }
  return out;
}

describe("source files", () => {
  it("never start with a UTF-8 byte order mark", () => {
    const withBom = ROOTS.flatMap((r) => walk(r)).filter((f) => {
      const head = readFileSync(f).subarray(0, 3);
      return head[0] === 0xef && head[1] === 0xbb && head[2] === 0xbf;
    });
    expect(withBom).toEqual([]);
  });

  it("keeps the Prisma migration lock readable", () => {
    const lock = readFileSync(join(__dirname, "..", "prisma", "migrations", "migration_lock.toml"), "utf8");
    expect(lock).toMatch(/^provider = "postgresql"\s*$/m);
    expect(lock.charCodeAt(0)).not.toBe(0xfeff);
  });

  it("keeps the seed data parseable as JSON", () => {
    expect(() => JSON.parse(readFileSync(join(__dirname, "..", "prisma", "countries.json"), "utf8"))).not.toThrow();
  });
});
