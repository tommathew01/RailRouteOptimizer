import type { Metadata } from "next";
import { Suspense } from "react";

import { ResultsView } from "./ResultsView";

export const metadata: Metadata = { title: "Segment combinations" };

export default function ResultsPage({ params }: PageProps<"/results/[searchId]">) {
  return (
    <Suspense fallback={<div className="card h-64 animate-pulse" aria-hidden="true" />}>
      {params.then(({ searchId }) => (
        <ResultsView searchId={searchId} />
      ))}
    </Suspense>
  );
}
