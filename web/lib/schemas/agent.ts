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
  // Daily run schedule of the active country (local time, "HH:MM"); null when no country is active.
  schedule: z
    .object({ countryCode: z.string(), runHour: z.string().regex(/^\d{2}:\d{2}$/), timezone: z.string() })
    .nullable(),
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

// --- Results (step 1.3) -------------------------------------------------------------------

export const checkInput = z.object({
  checkId: z.string().min(1).max(80),
  severity: z.enum(["info", "warning", "critical"]),
  passed: z.boolean(),
  value: z.number().nullable().optional(),
  threshold: z.number().nullable().optional(),
  detail: z.string().max(1000).nullable().optional(),
  scope: z.string().max(40).optional(), // e.g. "home", "epg" for page-level checks
});
export type CheckInput = z.infer<typeof checkInput>;

export const channelResultRequest = z.object({
  channel: z.object({
    slug: z.string().regex(/^[\w.-]{1,80}$/),
    name: z.string().min(1).max(200),
    category: z.string().max(100).nullable().optional(),
  }),
  error: z.string().max(500).optional(), // set when the measurement crashed -> status "error"
  metrics: z.record(z.string(), z.unknown()).default({}),
  checks: z.array(checkInput).max(200).default([]),
  measuredAt: z.string().datetime().optional(),
});
export type ChannelResultRequest = z.infer<typeof channelResultRequest>;

export const imagesResultRequest = z.object({
  pages: z.record(
    z.string().max(40),
    z.object({
      url: z.string().max(500),
      metrics: z.record(z.string(), z.unknown()),
      loadError: z.string().nullable().optional(),
    }),
  ),
  checks: z.array(checkInput).max(200),
});
export type ImagesResultRequest = z.infer<typeof imagesResultRequest>;

export const finishRunRequest = z.object({
  status: z.enum(["completed", "failed"]).default("completed"),
  log: z.array(z.object({ level: z.string(), msg: z.string().max(500) })).max(200).optional(),
});