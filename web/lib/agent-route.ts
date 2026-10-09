import { createHash, timingSafeEqual } from "node:crypto";
import { NextResponse } from "next/server";
import type { z } from "zod";

const sha = (s: string) => createHash("sha256").update(s).digest();

/** Returns an error response when the Bearer key is missing or wrong, otherwise null. */
export function checkAgentAuth(req: Request): NextResponse | null {
  const expected = process.env.AGENT_API_KEY;
  if (!expected) {
    console.error("AGENT_API_KEY is not configured");
    return NextResponse.json({ error: "agent API not configured" }, { status: 503 });
  }
  const header = req.headers.get("authorization") ?? "";
  const token = header.startsWith("Bearer ") ? header.slice(7) : "";
  // Compare fixed-length digests so the check is constant-time regardless of input length.
  if (!token || !timingSafeEqual(sha(token), sha(expected))) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  return null;
}

/** Parses a JSON body with a Zod schema; returns the data or a 400 response. */
export async function parseJson<S extends z.ZodTypeAny>(
  req: Request,
  schema: S,
): Promise<{ data: z.infer<S> } | { error: NextResponse }> {
  let raw: unknown;
  try {
    raw = await req.json();
  } catch {
    return { error: NextResponse.json({ error: "invalid JSON" }, { status: 400 }) };
  }
  const parsed = schema.safeParse(raw);
  if (!parsed.success) {
    return {
      error: NextResponse.json({ error: "invalid request", issues: parsed.error.issues }, { status: 400 }),
    };
  }
  return { data: parsed.data };
}