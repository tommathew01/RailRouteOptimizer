import { Suspense } from "react";

import { HomeSearch } from "./HomeSearch";

const STEPS = [
  {
    title: "Pick your train journey",
    body: "Choose stations, date and one or more classes. Quota is always General (GN).",
  },
  {
    title: "We check shorter segments",
    body: "RailRoute checks the direct ticket first, then split tickets on the same train, within a strict request budget.",
  },
  {
    title: "Book each ticket yourself",
    body: "Get up to four separate tickets ranked by current availability, with the provider's estimate shown separately.",
  },
];

export default function HomePage() {
  return (
    <div className="space-y-10">
      <section aria-labelledby="hero-title" className="max-w-3xl">
        <h1 id="hero-title" className="text-3xl font-semibold tracking-tight sm:text-4xl">
          Can&apos;t get a direct ticket? Try the same train in segments.
        </h1>
        <p className="mt-3 text-lg text-muted">
          RailRoute checks station-to-station reservations on one train and finds combinations of
          up to four separate tickets that cover your whole journey.
        </p>
      </section>

      <Suspense fallback={<div className="card h-96 animate-pulse" aria-hidden="true" />}>
        <HomeSearch />
      </Suspense>

      <section aria-labelledby="how-title">
        <h2 id="how-title" className="text-xl font-semibold">
          How it works
        </h2>
        <ol className="mt-4 grid gap-4 md:grid-cols-3">
          {STEPS.map((step, index) => (
            <li key={step.title} className="card">
              <p className="text-sm font-semibold text-brand">Step {index + 1}</p>
              <p className="mt-1 font-semibold">{step.title}</p>
              <p className="mt-1 text-sm text-muted">{step.body}</p>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
