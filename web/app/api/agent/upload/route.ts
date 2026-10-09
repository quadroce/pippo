import { put } from "@vercel/blob";
import { NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { checkAgentAuth } from "@/lib/agent-route";
import { UPLOAD_CONTENT_TYPES, UPLOAD_MAX_BYTES, uploadQuery } from "@/lib/schemas/agent";

export const dynamic = "force-dynamic";

/**
 * Stores a screenshot or raw event buffer in Vercel Blob (private access).
 * `POST /api/agent/upload?runId=<uuid>&kind=screenshot|raw&name=<file>` with the file as the body.
 *
 * Deviation from the architecture doc ("signed upload URL"): the agent streams the bytes
 * through this endpoint (max 4 MB, the serverless body limit) which keeps the Python client
 * simple. Large raw buffers must be gzipped; revisit with client uploads if that is not enough.
 */
export async function POST(req: Request) {
  const denied = checkAgentAuth(req);
  if (denied) return denied;

  const q = uploadQuery.safeParse(Object.fromEntries(new URL(req.url).searchParams));
  if (!q.success) {
    return NextResponse.json({ error: "invalid request", issues: q.error.issues }, { status: 400 });
  }

  const contentType = (req.headers.get("content-type") ?? "").split(";")[0].trim();
  if (!(UPLOAD_CONTENT_TYPES as readonly string[]).includes(contentType)) {
    return NextResponse.json({ error: `unsupported content-type ${contentType || "(none)"}` }, { status: 415 });
  }

  const declared = Number(req.headers.get("content-length") ?? "0");
  if (declared > UPLOAD_MAX_BYTES) {
    return NextResponse.json({ error: "file too large" }, { status: 413 });
  }
  const bytes = await req.arrayBuffer();
  if (bytes.byteLength === 0) return NextResponse.json({ error: "empty body" }, { status: 400 });
  if (bytes.byteLength > UPLOAD_MAX_BYTES) return NextResponse.json({ error: "file too large" }, { status: 413 });

  const run = await prisma.run.findUnique({ where: { id: q.data.runId }, select: { id: true } });
  if (!run) return NextResponse.json({ error: "unknown run" }, { status: 404 });

  const blob = await put(`runs/${run.id}/${q.data.kind}/${q.data.name}`, Buffer.from(bytes), {
    access: "private",
    contentType,
    addRandomSuffix: true,
  });
  return NextResponse.json({ url: blob.url, pathname: blob.pathname }, { status: 201 });
}