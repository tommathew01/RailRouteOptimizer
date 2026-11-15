/** Shareable URL state for a journey search: /search?from=TIR&to=TVC&date=…&classes=3A,SL */
import { z } from "zod";

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
});

export type JourneyQuery = z.infer<typeof JourneyQuerySchema>;

export function parseJourneyQuery(params: URLSearchParams): JourneyQuery | null {
  const result = JourneyQuerySchema.safeParse(Object.fromEntries(params.entries()));
  return result.success ? result.data : null;
}

export function journeyQueryString(query: JourneyQuery): string {
  const params = new URLSearchParams({
    from: query.from,
    to: query.to,
    date: query.date,
    classes: query.classes.join(","),
    rac: query.rac ? "1" : "0",
    wl: query.wl ? "1" : "0",
  });
  return params.toString();
}
