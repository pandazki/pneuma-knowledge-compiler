import type { ActivityDay } from "./api";

const DAY_MS = 86_400_000;

export interface ActivityCell extends ActivityDay {
  active: boolean;
}

export interface ActivityGrid {
  cells: ActivityCell[];
  weeks: number;
  firstDate: string | null;
  lastDate: string | null;
  maxCount: number;
}

function parseDate(value: string): Date {
  const [year, month, day] = value.split("-").map(Number);
  return new Date(Date.UTC(year!, month! - 1, day!));
}

function dateKey(value: Date): string {
  return value.toISOString().slice(0, 10);
}

function addDays(value: Date, days: number): Date {
  return new Date(value.getTime() + days * DAY_MS);
}

function mondayAtOrBefore(value: Date): Date {
  const weekday = value.getUTCDay();
  return addDays(value, -(weekday === 0 ? 6 : weekday - 1));
}

function sundayAtOrAfter(value: Date): Date {
  const weekday = value.getUTCDay();
  return addDays(value, weekday === 0 ? 0 : 7 - weekday);
}

export function buildActivityGrid(
  days: ActivityDay[],
  { minWeeks = 12, maxWeeks = 18 }: { minWeeks?: number; maxWeeks?: number } = {},
): ActivityGrid {
  if (days.length === 0) {
    return {
      cells: [],
      weeks: 0,
      firstDate: null,
      lastDate: null,
      maxCount: 0,
    };
  }

  const sorted = [...days].sort((left, right) => left.date.localeCompare(right.date));
  const byDate = new Map(sorted.map((day) => [day.date, day]));
  const naturalStart = mondayAtOrBefore(parseDate(sorted[0]!.date));
  const end = sundayAtOrAfter(parseDate(sorted[sorted.length - 1]!.date));
  const naturalDays = Math.round((end.getTime() - naturalStart.getTime()) / DAY_MS) + 1;
  const naturalWeeks = Math.ceil(naturalDays / 7);
  const weeks = Math.max(minWeeks, Math.min(maxWeeks, naturalWeeks));
  const start = addDays(end, -(weeks * 7 - 1));
  const cells = Array.from({ length: weeks * 7 }, (_, index) => {
    const date = dateKey(addDays(start, index));
    const day = byDate.get(date);
    return {
      date,
      count: day?.count ?? 0,
      kinds: day?.kinds ?? {},
      active: day != null,
    };
  });

  return {
    cells,
    weeks,
    firstDate: dateKey(start),
    lastDate: dateKey(end),
    maxCount: Math.max(...days.map((day) => day.count)),
  };
}
