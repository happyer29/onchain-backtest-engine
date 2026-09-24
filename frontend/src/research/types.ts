// Display-only graph contracts preserve exact row ordinals and decimal counters.
export type Row = Record<string, string>;
export type Pair = Row & { row_id: string; signer_a: string; signer_b: string; shared_mints: string; a_first: string; b_first: string; same_transaction: string };
export type GraphData = { rows: Pair[]; wallets: string[]; bytes?: number };
export type GroupLink = { key: string; a: number; b: number; indices: number[] };
export type Group = { id: number; members: number[]; internal: number[]; links: GroupLink[] };
export type Model = GraphData & {
  lookup: Map<string, number>; left: Uint16Array; right: Uint16Array; weight: Float64Array; strength: Float64Array; adjacent: number[][];
  groups: Group[]; groupOf: Uint16Array; links: GroupLink[]; internal: number; external: number; passes: number; stable: boolean; policy: string;
};
export type Projection = { members: number[]; indices: number[]; centre?: number; extra?: number; incident?: number };
export type View = { kind: 'overview' } | { kind: 'group'; key: number } | { kind: 'wallet'; key: string } | { kind: 'page' };
