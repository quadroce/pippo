import { z } from "zod";

/**
 * Agent API contract (docs/02-ARCHITECTURE.md §3.2). The Python agent mirrors these shapes
 * in agent/pippo/api_client.py; keep both in sync.
 */

const countryCode = z
  .string()
  .regex(/^[A-Za-z]{2}$/, "ISO 3166-1 alpha-2 country code")
  .transform((s) => s.toUpperCase());

export const heartbeatRequest = z.object({
  agentVersion: z.string().min(1).max(40),
  hostname: z.string().max(100).optional(),
  detectedCountry: countryCode.nullable().optional(),
  probe: z.boolean().optional(), // sent by `pippo doctor`
});
export type HeartbeatRequest = z.infer<typeof heartbeatRequest>;

export const heartbeatResponse = z.object({
  activeCountry: z.string().nullable(),
  pollIntervalSec: z.number().int().positive(),
});
export type HeartbeatResponse = z.infer<typeof heartbeatResponse>;

export const createRunRequest = z.object({
  countryCode,
  trigger: z.enum(["scheduled", "on_demand"]),
  detectedCountry: countryCode.nullable().optional(),
  agentVersion: z.string().min(1).max(40),
  jobId: z.string().uuid().optional(),
});
export type CreateRunRequest = z.infer<typeof createRunRequest>;

export const createRunResponse = z.object({
  id: z.string().uuid(),
  status: z.enum(["running", "blocked"]),
});

export const UPLOAD_KINDS = ["screenshot", "raw"] as const;
export const UPLOAD_CONTENT_TYPES = ["image/png", "image/jpeg", "application/json", "application/gzip"] as const;
/** Vercel serverless request bodies are limited to 4.5 MB. */
export const UPLOAD_MAX_BYTES = 4 * 1024 * 1024;

export const uploadQuery = z.object({
  runId: z.string().uuid(),
  kind: z.enum(UPLOAD_KINDS),
  name: z.string().regex(/^[\w.-]{1,80}$/, "letters, digits, dot, dash, underscore"),
});