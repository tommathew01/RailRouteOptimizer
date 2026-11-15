import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BookingGuidance, CoverageNotice, RecommendationCard } from "@/components/Results";
import { StationAutocomplete } from "@/components/StationAutocomplete";
import { AvailabilityBadge, PredictionIndicator } from "@/components/StatusBits";
import { JourneySearchSchema } from "@/lib/api/schemas";

import fixture from "../../test/fixtures/journey-search.json";

const search = JourneySearchSchema.parse(fixture);

function withQueryClient(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{node}</QueryClientProvider>;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("AvailabilityBadge", () => {
  it("communicates status in text, not colour alone", () => {
    render(<AvailabilityBadge status="WAITLIST" text="WL 27" />);
    expect(screen.getByText("Waitlist")).toBeInTheDocument();
    expect(screen.getByText("· WL 27")).toBeInTheDocument();
  });
});

describe("PredictionIndicator", () => {
  it("labels the provider estimate and explains it is not a guarantee", async () => {
    render(
      <PredictionIndicator
        prediction={{ provider: "RAILKIT", label: "RailKit prediction", text: "73% Chance", percentage: 73, percentage_source: "FIELD" }}
      />,
    );
    expect(screen.getByText("RailKit prediction:")).toBeInTheDocument();
    expect(screen.getByText("73%")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /about the railkit prediction/i }));
    expect(screen.getByRole("note")).toHaveTextContent(/not a guarantee/i);
  });

  it("says so when there is no estimate", () => {
    render(<PredictionIndicator prediction={null} />);
    expect(screen.getByText("No provider estimate")).toBeInTheDocument();
  });
});

describe("RecommendationCard", () => {
  it("shows every segment with status, and booking steps on demand", async () => {
    const rec = search.recommendations[0];
    render(<RecommendationCard recommendation={rec} staleAfter={300} />);
    expect(screen.getByRole("heading", { name: new RegExp(rec.train_number) })).toBeInTheDocument();
    expect(screen.getAllByRole("listitem").length).toBeGreaterThanOrEqual(rec.segment_count);
    await userEvent.click(screen.getByRole("button", { name: /how to book/i }));
    expect(screen.getByText(new RegExp(`Ticket 1 of ${rec.segment_count}`))).toBeInTheDocument();
  });

  it("never shows a partial sum as the total fare", () => {
    const rec = { ...search.recommendations[0], total_fare: null, fare_complete: false };
    render(<RecommendationCard recommendation={rec} staleAfter={300} />);
    expect(screen.getByText("Total fare unavailable")).toBeInTheDocument();
  });
});

describe("Coverage and guidance", () => {
  it("explains partial searches honestly", () => {
    const partial = { ...search, search_completeness: "NO_PATH_FOUND_PARTIAL", recommendations: [] };
    render(<CoverageNotice search={partial} />);
    expect(screen.getByText(/no combination found in the segments checked/i)).toBeInTheDocument();
    expect(screen.getByText(/does not mean none exist/i)).toBeInTheDocument();
  });

  it("lists separate-ticket warnings and links to an authorized platform", () => {
    render(<BookingGuidance warnings={search.warnings} />);
    expect(screen.getByText(/separate reservation/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "irctc.co.in" })).toHaveAttribute("rel", "noopener noreferrer");
  });
});

describe("StationAutocomplete", () => {
  it("searches after the minimum length and selects with the keyboard", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () =>
      new Response(
        JSON.stringify({
          items: [
            { code: "TIR", name: "Tirur", city: "Tirur", latitude: null, longitude: null },
            { code: "TRVL", name: "Tiruvalla", city: null, latitude: null, longitude: null },
          ],
          data_mode: "DEMO",
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const onChange = vi.fn();
    render(withQueryClient(<StationAutocomplete label="From" value={null} onChange={onChange} minLength={3} />));

    const input = screen.getByRole("combobox", { name: "From" });
    await userEvent.type(input, "ti");
    expect(screen.getByText("Type at least 3 characters.")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();

    await userEvent.type(input, "r");
    await waitFor(() => expect(screen.getAllByRole("option")).toHaveLength(2));
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/stations/search?q=tir");
    expect(input).toHaveAttribute("aria-expanded", "true");

    await userEvent.keyboard("{ArrowDown}{Enter}");
    expect(onChange).toHaveBeenLastCalledWith({ code: "TIR", name: "Tirur", city: "Tirur", latitude: null, longitude: null });
  });
});
