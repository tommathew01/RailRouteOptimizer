"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useState, type KeyboardEvent } from "react";

import { stationSearchQuery } from "@/lib/api/queries";
import type { Station } from "@/lib/api/schemas";

export type StationValue = Pick<Station, "code" | "name">;

function display(station: StationValue): string {
  return `${station.name} (${station.code})`;
}

function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(value), delayMs);
    return () => window.clearTimeout(id);
  }, [value, delayMs]);
  return debounced;
}

type Props = {
  label: string;
  value: StationValue | null;
  onChange: (station: StationValue | null) => void;
  minLength: number;
  error?: string;
  placeholder?: string;
};

/** ARIA 1.2 combobox backed by the (cached, debounced) station search endpoint. */
export function StationAutocomplete({ label, value, onChange, minLength, error, placeholder }: Props) {
  const id = useId();
  const listId = `${id}-listbox`;
  const statusId = `${id}-status`;
  const errorId = `${id}-error`;

  const [text, setText] = useState(value ? display(value) : "");
  const [previous, setPrevious] = useState(value);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);

  // Keep the text in sync when the value changes from outside (e.g. the swap button).
  if (value !== previous) {
    setPrevious(value);
    setText(value ? display(value) : "");
  }

  const query = useDebouncedValue(text.trim(), 300);
  const showingSelection = value !== null && text === display(value);
  const enabled = open && !showingSelection && query.length >= minLength;
  const { data, isFetching, isError } = useQuery({ ...stationSearchQuery(query), enabled });
  const options = enabled ? (data?.items ?? []) : [];
  const expanded = open && options.length > 0;

  function choose(station: StationValue) {
    onChange(station);
    setText(display(station));
    setOpen(false);
    setActive(-1);
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setOpen(true);
      setActive((i) => (options.length ? (i + 1) % options.length : -1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((i) => (options.length ? (i <= 0 ? options.length - 1 : i - 1) : -1));
    } else if (event.key === "Enter" && expanded && active >= 0) {
      event.preventDefault();
      choose(options[active]);
    } else if (event.key === "Escape") {
      setOpen(false);
      setActive(-1);
    }
  }

  let status = "";
  if (open && !showingSelection) {
    if (text.trim().length < minLength) status = `Type at least ${minLength} characters.`;
    else if (isFetching) status = "Searching stations…";
    else if (isError) status = "Station search is unavailable right now.";
    else if (enabled && data && options.length === 0) status = "No matching stations.";
    else if (options.length) status = `${options.length} stations found.`;
  }

  return (
    <div className="relative">
      <label htmlFor={id} className="field-label">
        {label}
      </label>
      <input
        id={id}
        type="text"
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={expanded}
        aria-controls={listId}
        aria-activedescendant={expanded && active >= 0 ? `${id}-option-${active}` : undefined}
        aria-invalid={error ? true : undefined}
        aria-describedby={[statusId, error ? errorId : null].filter(Boolean).join(" ")}
        autoComplete="off"
        spellCheck={false}
        placeholder={placeholder}
        className="field-input"
        value={text}
        onChange={(event) => {
          setText(event.target.value);
          setOpen(true);
          setActive(-1);
          if (value) onChange(null);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => window.setTimeout(() => setOpen(false), 120)}
        onKeyDown={onKeyDown}
      />
      <ul
        id={listId}
        role="listbox"
        aria-label={`${label} suggestions`}
        className={`absolute z-20 mt-1 max-h-72 w-full overflow-auto rounded-lg border border-border bg-surface py-1 shadow-lg ${expanded ? "" : "hidden"}`}
      >
        {options.map((station, index) => (
          <li
            key={station.code}
            id={`${id}-option-${index}`}
            role="option"
            aria-selected={index === active}
            className={`flex cursor-pointer items-center justify-between gap-3 px-3 py-2 text-sm ${index === active ? "bg-brand text-brand-contrast" : "hover:bg-surface-muted"}`}
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => choose(station)}
          >
            <span>
              {station.name}
              {station.city && station.city !== station.name ? (
                <span className="opacity-75"> · {station.city}</span>
              ) : null}
            </span>
            <span className="font-mono text-xs font-semibold">{station.code}</span>
          </li>
        ))}
      </ul>
      <p
        id={statusId}
        aria-live="polite"
        className={status && !expanded ? "mt-1 text-xs text-muted" : "sr-only"}
      >
        {status}
      </p>
      {error ? (
        <p id={errorId} className="field-error">
          {error}
        </p>
      ) : null}
    </div>
  );
}
