/** Runtime schemas mirroring the backend's public API (backend remains authoritative). */
import { z } from "zod";

export const ErrorEnvelopeSchema = z.object({
  error: z.object({
    code: z.string(),
    message: z.string(),
    request_id: z.string().nullable().optional(),
    details: z.record(z.string(), z.unknown()).nullable().optional(),
  }),
});

export const DataModeSchema = z.enum(["DEMO", "LIVE"]);
export type DataMode = z.infer<typeof DataModeSchema>;

// --- Quotas ----------------------------------------------------------------------------------
export const QuotaCodeSchema = z.enum(["GN", "TQ"]);
export type QuotaCode = z.infer<typeof QuotaCodeSchema>;

export const EligibilityStateSchema = z.enum([
  "NOT_APPLICABLE",
  "NOT_YET_OPEN",
  "OPENS_TODAY",
  "OPEN",
  "OPENING_PASSED",
  "JOURNEY_DATE_PASSED",
  "CLASS_CATEGORY_UNKNOWN",
  "UNDETERMINED",
  "PROVIDER_UNSUPPORTED",
]);

/** Whether the backend may ask the provider for a quota. Never an availability status. */
export const QuotaEligibilitySchema = z.object({
  quota: QuotaCodeSchema,
  state: EligibilityStateSchema,
  queryable: z.boolean(),
  class_category: z.enum(["AC", "NON_AC"]).nullable(),
  train_origin_date: z.string().nullable(),
  opens_at: z.string().nullable(),
  message: z.string(),
});

export const QuotaOptionSchema = z.object({
  code: QuotaCodeSchema,
  label: z.string(),
  default: z.boolean(),
  provider_supported: z.boolean(),
  opening_rule: z
    .object({
      reference: z.literal("TRAIN_ORIGIN_DATE"),
      days_before: z.number().int(),
      ac_opens_at: z.string(),
      non_ac_opens_at: z.string(),
      timezone: z.literal("Asia/Kolkata"),
    })
    .nullable(),
  note: z.string().nullable().optional(),
});

export const QuotaSummarySchema = z.object({
  quota: QuotaCodeSchema,
  quota_label: z.string(),
  provider_supported: z.boolean(),
  queried: z.boolean(),
  combinations_eligible: z.number().int(),
  combinations_not_queried: z.number().int(),
  next_opening_at: z.string().nullable(),
  not_queried: z.array(
    z.object({
      state: EligibilityStateSchema,
      combinations: z.number().int(),
      travel_classes: z.array(z.string()),
      opens_at: z.string().nullable(),
      message: z.string(),
    }),
  ),
  recommendations: z.number().int(),
});

// --- Meta ------------------------------------------------------------------------------------
export const ClassOptionSchema = z.object({
  code: z.string(),
  label: z.string(),
  category: z.enum(["AC", "NON_AC"]).nullable().optional(),
});

export const MetaSchema = z.object({
  app_name: z.string(),
  api_version: z.literal("v1"),
  data_mode: DataModeSchema,
  provider: z.string(),
  quota: z.object({ code: z.literal("GN"), label: z.string(), editable: z.boolean() }),
  quotas: z.array(QuotaOptionSchema).default([]),
  supported_classes: z.array(ClassOptionSchema),
  limits: z.object({
    max_segments: z.number().int(),
    max_trains_per_search: z.number().int(),
    max_availability_requests_per_search: z.number().int(),
    max_advance_booking_days: z.number().int(),
  }),
  station_search_min_query_length: z.number().int(),
  stale_after_seconds: z.number().int(),
  availability_date_policy: z.string(),
  availability_date_policy_verified: z.boolean(),
  disclaimers: z.array(z.string()),
});

// --- Catalog ---------------------------------------------------------------------------------
export const StationSchema = z.object({
  code: z.string(),
  name: z.string(),
  city: z.string().nullable(),
  latitude: z.number().nullable(),
  longitude: z.number().nullable(),
});

export const StationSearchResponseSchema = z.object({
  items: z.array(StationSchema),
  data_mode: DataModeSchema,
});

export const TrainSchema = z.object({
  train_number: z.string(),
  train_name: z.string().nullable(),
  boards_at: z.string(),
  boards_at_name: z.string().nullable(),
  alights_at: z.string(),
  alights_at_name: z.string().nullable(),
  serves_requested_stations: z.boolean(),
  departure_time: z.string().nullable(),
  arrival_time: z.string().nullable(),
  duration_minutes: z.number().int().nullable(),
  running_days: z.string().nullable(),
  origin_station_code: z.string().nullable(),
  terminus_station_code: z.string().nullable(),
  distance_km: z.number().int().nullable(),
  halts: z.number().int().nullable(),
});

export const TrainSearchResponseSchema = z.object({
  source: z.string(),
  destination: z.string(),
  journey_date: z.string(),
  trains: z.array(TrainSchema),
  data_mode: DataModeSchema,
  provider: z.string(),
});

export const RouteStopSchema = z.object({
  sequence: z.number().int(),
  station_code: z.string(),
  station_name: z.string().nullable(),
  arrival: z.string().nullable(),
  departure: z.string().nullable(),
  day_offset: z.number().int().nullable(),
  halt_minutes: z.number().int().nullable(),
  distance_km: z.number().nullable(),
  platform: z.string().nullable(),
});

export const TrainRouteResponseSchema = z.object({
  train_number: z.string(),
  train_name: z.string().nullable(),
  stops: z.array(RouteStopSchema),
  route_verified: z.boolean(),
  issues: z.array(z.string()),
  classes: z.array(z.string()).nullable(),
  running_days: z.string().nullable(),
  fetched_at: z.string(),
  data_mode: DataModeSchema,
});

// --- Journeys --------------------------------------------------------------------------------
export const AvailabilityStatusSchema = z.enum([
  "CONFIRMED",
  "AVAILABLE",
  "RAC",
  "WAITLIST",
  "NOT_AVAILABLE",
  "UNKNOWN",
]);
export type AvailabilityStatus = z.infer<typeof AvailabilityStatusSchema>;

export const PredictionSchema = z.object({
  provider: z.string(),
  label: z.string(),
  text: z.string().nullable(),
  percentage: z.number().nullable(),
  percentage_source: z.enum(["FIELD", "TEXT"]).nullable(),
});

export const FareSchema = z.object({
  amount: z.string(),
  currency: z.string(),
  basis: z.string().nullable().optional(),
});

export const SegmentSchema = z.object({
  sequence: z.number().int(),
  source: z.string(),
  source_name: z.string().nullable(),
  destination: z.string(),
  destination_name: z.string().nullable(),
  departure: z.string().nullable(),
  arrival: z.string().nullable(),
  provider_query_date: z.string(),
  boards_on_later_date: z.boolean(),
  status: AvailabilityStatusSchema,
  availability_text: z.string().nullable(),
  raw_status: z.string().nullable(),
  waitlist_type: z.string().nullable(),
  waitlist_number: z.number().int().nullable(),
  rac_number: z.number().int().nullable(),
  available_count: z.number().int().nullable(),
  can_book: z.boolean().nullable(),
  prediction: PredictionSchema.nullable(),
  fare: FareSchema.nullable(),
  checked_at: z.string(),
  cached: z.boolean(),
  observation_id: z.string(),
});

export const RecommendationSchema = z.object({
  rank: z.number().int(),
  train_number: z.string(),
  train_name: z.string().nullable(),
  travel_class: z.string(),
  travel_class_label: z.string(),
  quota: QuotaCodeSchema,
  quota_label: z.string().default("General"),
  train_start_date: z.string(),
  segment_count: z.number().int(),
  status_tier: z.number().int(),
  status_tier_label: z.string(),
  segments: z.array(SegmentSchema),
  total_fare: FareSchema.nullable(),
  fare_complete: z.boolean(),
  prediction_summary: z.object({
    kind: z.literal("MINIMUM_SEGMENT_ESTIMATE"),
    minimum_percentage: z.number().nullable(),
    segments_with_estimate: z.number().int(),
    segments_needing_estimate: z.number().int(),
    note: z.string(),
  }),
  explanation: z.array(z.string()),
  booking_steps: z.array(z.string()),
  oldest_checked_at: z.string(),
});

export const ClassEvaluationSchema = z.object({
  travel_class: z.string(),
  quota: QuotaCodeSchema.default("GN"),
  quota_label: z.string().default("General"),
  state: z.enum([
    "SOLVED",
    "EXHAUSTED",
    "STOPPED",
    "ACTIVE",
    "NOT_OFFERED",
    "NOT_EVALUATED",
    "NOT_YET_OPEN",
    "QUOTA_NOT_SUPPORTED",
    "NOT_QUERIED",
  ]),
  queried: z.boolean().default(true),
  depth_reached: z.number().int(),
  best_status_tier: z.number().int().nullable(),
  recommendations: z.number().int(),
  eligibility: QuotaEligibilitySchema.nullable().optional(),
});

export const TrainEvaluationSchema = z.object({
  train_number: z.string(),
  train_name: z.string().nullable(),
  evaluation: z.enum([
    "EVALUATED",
    "ROUTE_UNVERIFIED",
    "ROUTE_UNAVAILABLE",
    "DIFFERENT_STATIONS",
    "NOT_IN_TRAIN_SEARCH",
    "SKIPPED_TRAIN_LIMIT",
  ]),
  route_issues: z.array(z.string()),
  departure: z.string().nullable(),
  arrival: z.string().nullable(),
  intermediate_stops_total: z.number().int(),
  intermediate_stops_considered: z.number().int(),
  classes: z.array(ClassEvaluationSchema),
});

export const SearchStatusSchema = z.enum(["QUEUED", "RUNNING", "COMPLETED", "FAILED"]);

export const JourneySearchSchema = z.object({
  search_id: z.string(),
  status: SearchStatusSchema,
  status_url: z.string(),
  data_mode: DataModeSchema,
  provider: z.string(),
  request: z.object({
    source: z.string(),
    destination: z.string(),
    journey_date: z.string(),
    classes: z.array(z.string()),
    quota: QuotaCodeSchema,
    quotas: z.array(QuotaCodeSchema).default(["GN"]),
    filters: z.object({ allow_rac: z.boolean(), allow_waitlist: z.boolean() }),
    max_segments: z.number().int(),
    train_numbers: z.array(z.string()).nullable(),
  }),
  search_completeness: z.string().nullable(),
  incomplete_reason: z.string().nullable(),
  coverage: z
    .object({
      trains_found: z.number().int(),
      trains_evaluated: z.number().int(),
      combinations_evaluated: z.number().int(),
      combinations_not_queried: z.number().int().default(0),
      availability_requests_planned: z.number().int(),
      availability_requests_made: z.number().int(),
      request_budget: z.number().int(),
      cache_hits: z.number().int(),
      segments_checked: z.number().int(),
      segments_unknown: z.number().int(),
      segments_failed: z.number().int(),
    })
    .nullable(),
  trains: z.array(TrainEvaluationSchema),
  quotas: z.array(QuotaSummarySchema).default([]),
  recommendations: z.array(RecommendationSchema),
  warnings: z.array(z.string()),
  error: z.object({ code: z.string(), message: z.string() }).nullable().optional(),
  stale_after_seconds: z.number().int(),
  created_at: z.string(),
  started_at: z.string().nullable(),
  completed_at: z.string().nullable(),
});

export const SearchAcceptedSchema = z.object({
  search_id: z.string(),
  status: SearchStatusSchema,
  status_url: z.string(),
});

export const OptimizeResultSchema = z.union([JourneySearchSchema, SearchAcceptedSchema]);

export type Meta = z.infer<typeof MetaSchema>;
export type QuotaOption = z.infer<typeof QuotaOptionSchema>;
export type QuotaSummary = z.infer<typeof QuotaSummarySchema>;
export type QuotaEligibility = z.infer<typeof QuotaEligibilitySchema>;
export type ClassEvaluation = z.infer<typeof ClassEvaluationSchema>;
export type ClassOption = z.infer<typeof ClassOptionSchema>;
export type Station = z.infer<typeof StationSchema>;
export type Train = z.infer<typeof TrainSchema>;
export type TrainRoute = z.infer<typeof TrainRouteResponseSchema>;
export type RouteStop = z.infer<typeof RouteStopSchema>;
export type Prediction = z.infer<typeof PredictionSchema>;
export type Fare = z.infer<typeof FareSchema>;
export type Segment = z.infer<typeof SegmentSchema>;
export type Recommendation = z.infer<typeof RecommendationSchema>;
export type TrainEvaluation = z.infer<typeof TrainEvaluationSchema>;
export type JourneySearch = z.infer<typeof JourneySearchSchema>;
