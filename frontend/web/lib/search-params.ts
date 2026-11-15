/** Shareable URL state for a journey search: /search?from=TIR&to=TVC&date=…&classes=3A,SL&quotas=GN,TQ */
import { z } from "zod";

/** Canonical quota order; General is the default and is omitted from URLs when alone. */
export const QUOTA_CODES = ["GN", "TQ"] as const;
export type QuotaCodeParam = (typeof QUOTA_CODES)[number];

function isQuota(value: string): value is QuotaCodeParam {
  return (QUOTA_CODES as readonly string[]).includes(value);
}

/** Dedupe and sort into the canonical GN, TQ order. */
export function canonicalQuotas(values: readonly string[]): QuotaCodeParam[] {
  const wanted = new Set(values.map((v) => v.trim().toUpperCase()));
  return QUOTA_CODES.filter((code) => wanted.has(code));
}

const Code = z
  .string()
  .trim()
  .toUpperCase()
  .regex(/^[A-Z0-9]{1,5}$/);

export const JourneyQuerySchema = z.object({
  from: Code,
  to: Code,
  date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
  classes: z
    .string()
    .transform((v) =>
      v
        .split(",")
        .map((c) => c.trim().toUpperCase())
        .filter(Boolean),
    )
    .pipe(z.array(z.string().regex(/^[0-9A-Z]{2}$/)).min(1).max(8)),
  rac: z
    .enum(["0", "1"])
    .default("0")
    .transform((v) => v === "1"),
  wl: z
    .enum(["0", "1"])
    .default("0")
    .transform((v) => v === "1"),
  quotas: z
    .string()
    .default("GN")
    .transform((v) =>
      v
        .split(",")
        .map((c) => c.trim().toUpperCase())
        .filter(Boolean),
    )
    .pipe(z.array(z.string().refine(isQuota)).min(1).max(2))
    .transform((codes) => canonicalQuotas(codes)),
});

export type JourneyQuery = z.infer<typeof JourneyQuerySchema>;

export function parseJourneyQuery(params: URLSearchParams): JourneyQuery | null {
  const result = JourneyQuerySchema.safeParse(Object.fromEntries(params.entries()));
  return result.success ? result.data : null;
}

/** Input for links: quotas may be omitted (General). */
export type JourneyQueryInput = Omit<JourneyQuery, "quotas"> & { quotas?: readonly string[] };

export function journeyQueryString(query: JourneyQueryInput): string {
  const params = new URLSearchParams({
    from: query.from,
    to: query.to,
    date: query.date,
    classes: query.classes.join(","),
    rac: query.rac ? "1" : "0",
    wl: query.wl ? "1" : "0",
  });
  const quotas = canonicalQuotas(query.quotas ?? ["GN"]);
  if (quotas.length && !(quotas.length === 1 && quotas[0] === "GN")) {
    params.set("quotas", quotas.join(","));
  }
  return params.toString();
}
