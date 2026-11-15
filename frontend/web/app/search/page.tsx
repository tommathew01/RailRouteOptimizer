import type { Metadata } from "next";
import { Suspense } from "react";

import { TrainSelection } from "./TrainSelection";

export const metadata: Metadata = { title: "Choose trains" };

export default function SearchPage() {
  return (
    <Suspense fallback={<div className="card h-64 animate-pulse" aria-hidden="true" />}>
      <TrainSelection />
    </Suspense>
  );
}
