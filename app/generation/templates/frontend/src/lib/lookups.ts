import type { SelectOption } from '../components/ui/Field';

export type Lookup = Record<string, string>;
export type Lookups = Record<string, Lookup>;

export function buildLookup<T extends { id: string }>(items: readonly T[] | undefined, label: (item: T) => string): Lookup {
  return Object.fromEntries((items ?? []).map((i) => [i.id, label(i)]));
}

export function toOptions<T extends { id: string }>(items: readonly T[] | undefined, label: (item: T) => string): SelectOption[] {
  return (items ?? []).map((i) => ({ value: i.id, label: label(i) }));
}
