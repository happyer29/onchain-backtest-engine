// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { buildDisplayGraph, filterPairs, visibleIndices } from './sigma-data';
import algorithms from './research-graph-model';
import type { GraphData, Pair } from './types';
const pair = (row_id: string, signer_a: string, signer_b: string, shared_mints = '2'): Pair => ({row_id,signer_a,signer_b,shared_mints,a_first:'1',b_first:'0',same_transaction:'1'});
export const fixture = (): GraphData => ({wallets:['A','B','C','D','E','F'],rows:[pair('9007199254740993','A','B','10'),pair('1','A','C','10'),pair('2','B','C','10'),pair('3','C','D'),pair('4','D','E','10'),pair('5','D','F','10'),pair('6','E','F','10')]});
const signal = () => new AbortController().signal;
describe('real Graphology projection and display filter', () => {
  it('preserves full addresses, every page pair and exact evidence ordinals beyond JS safe integers',async()=>{
    const model=await algorithms.build(fixture(),signal());const {graph}=await buildDisplayGraph(model,{kind:'page'},false,signal());
    expect(graph.order).toBe(6);expect(graph.size).toBe(7);expect(graph.getEdgeAttribute('pair:9007199254740993','index')).toBe(0);expect(graph.extremities('pair:9007199254740993')).toEqual(['wallet:A','wallet:B']);expect(graph.getEdgeAttribute('pair:9007199254740993','weight')).toBe(10);
  });
  it('overview reconciles all groups and crossing pairs without inventing individual evidence',async()=>{
    const model=await algorithms.build(fixture(),signal());const {graph,projection}=await buildDisplayGraph(model,{kind:'overview'},false,signal());
    expect(projection).toBeNull();expect(graph.order).toBe(2);expect(graph.size).toBe(1);expect(graph.getEdgeAttribute(graph.edges()[0],'link')?.indices).toEqual([3]);expect(graph.getEdgeAttribute(graph.edges()[0],'index')).toBeUndefined();expect(model.internal+model.external).toBe(7);
  });
  it('includes complete internal pairs and all wallet neighbours across group boundaries',async()=>{
    const model=await algorithms.build(fixture(),signal());const group=await buildDisplayGraph(model,{kind:'group',key:0},false,signal());
    expect(group.graph.order).toBe(3);expect(group.graph.size).toBe(3);expect(group.graph.hasNode('wallet:D')).toBe(false);
    const wallet=await buildDisplayGraph(model,{kind:'wallet',key:'C'},false,signal());
    expect(wallet.graph.hasNode('wallet:D')).toBe(true);expect(wallet.graph.size).toBe(3);expect(wallet.projection?.extra).toBe(1);expect(wallet.graph.getNodeAttributes('wallet:C')).toMatchObject({x:0,y:0,fixed:true});
  });
  it('optional neighbour edges preserve incident counts and complete induced pairs',async()=>{
    const model=await algorithms.build(fixture(),signal());const {graph,projection}=await buildDisplayGraph(model,{kind:'wallet',key:'C'},true,signal());
    expect(graph.size).toBe(4);expect(projection?.incident).toBe(3);expect(projection?.extra).toBe(1);expect(graph.hasEdge('pair:9007199254740993')).toBe(true);
  });
  it('large projection retains every pair with noncoincident finite deterministic starts',async()=>{
    const wallets=Array.from({length:160},(_,i)=>`w${String(i).padStart(3,'0')}`);const rows:Pair[]=[];
    for(let a=0;a<wallets.length;a++)for(let b=a+1;b<wallets.length;b++)rows.push(pair(String(rows.length),wallets[a],wallets[b]));
    const model=await algorithms.build({wallets,rows},signal());const {graph}=await buildDisplayGraph(model,{kind:'group',key:0},false,signal());
    expect(graph.size).toBe(12720);expect(graph.order).toBe(160);expect(new Set(graph.mapNodes((_,a)=>`${a.x},${a.y}`)).size).toBe(160);expect(graph.everyNode((_,a)=>Number.isFinite(a.x)&&Number.isFinite(a.y))).toBe(true);
  },15000);
  it('aborts a pending build and rejects stale ownership before a renderer can mount',async()=>{
    const model=await algorithms.build(fixture(),signal());const task=new AbortController();const pending=buildDisplayGraph(model,{kind:'overview'},false,task.signal);task.abort();await expect(pending).rejects.toMatchObject({name:'AbortError'});
    await expect(buildDisplayGraph(model,{kind:'page'},false,signal(),()=>false)).rejects.toMatchObject({name:'AbortError'});
    let checkpoints=0;await expect(buildDisplayGraph(model,{kind:'page'},false,signal(),()=>++checkpoints<2)).rejects.toMatchObject({name:'AbortError'});
  });
  it('empty views are explicitly empty and clearing releases nodes and edges',async()=>{
    const model=await algorithms.build({rows:[],wallets:[]},signal());const {graph}=await buildDisplayGraph(model,{kind:'overview'},false,signal());expect(graph.order).toBe(0);expect(graph.size).toBe(0);graph.clear();expect(graph.order).toBe(0);
  });
  it('strength filtering leaves groups/ordinals intact and reconciles shown, hidden and crossing counts',async()=>{
    const model=await algorithms.build(fixture(),signal()), original=Array.from(model.groupOf);
    const all=await filterPairs(model,1,signal()), filtered=await filterPairs(model,5,signal());
    expect(all.shown).toBe(7);expect(filtered.shown).toBe(6);expect(filtered.internal).toBe(6);expect(filtered.external).toBe(0);expect(filtered.links.size).toBe(0);expect(Array.from(filtered.groupInternal)).toEqual([3,3]);
    expect(visibleIndices(model.adjacent[model.lookup.get('C')!],filtered)).toEqual([1,2]);expect(Array.from(model.groupOf)).toEqual(original);expect(model.rows[0].row_id).toBe('9007199254740993');
    expect((await filterPairs(model,10,signal())).shown).toBe(6);expect((await filterPairs(model,11,signal())).shown).toBe(0);expect((await filterPairs(model,1,signal())).shown).toBe(7);
  });
  it('display filter rejects invalid thresholds and aborts instead of returning partial counts',async()=>{
    const model=await algorithms.build(fixture(),signal());for(const value of [0,-1,NaN,Infinity,1.5,2000001])await expect(filterPairs(model,value,signal())).rejects.toThrow();
    const task=new AbortController();task.abort();await expect(filterPairs(model,2,task.signal)).rejects.toMatchObject({name:'AbortError'});
  });
});
