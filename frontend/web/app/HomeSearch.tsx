"use client";

import { useSearchParams } from "next/navigation";

import { JourneySearchForm } from "@/components/JourneySearchForm";
import { parseJourneyQuery } from "@/lib/search-params";

/** The form, pre-filled when arriving from "Modify search" (?from=…&fromName=…). */
export function HomeSearch() {
  const params = useSearchParams();
  const query = parseJourneyQuery(params);
  if (!query) return <JourneySearchForm />;
  return (
    <JourneySearchForm
      initial={{
        from: { code: query.from, name: params.get("fromName") ?? query.from },
        to: { code: query.to, name: params.get("toName") ?? query.to },
        date: query.date,
        classes: query.classes,
        allowRac: query.rac,
        allowWaitlist: query.wl,
      }}
    />
  );
}
