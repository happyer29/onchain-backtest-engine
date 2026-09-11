// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { buildCanvas } from './canvas';
import algorithms from './research-graph-model';
import type { GraphData, Pair } from './types';
const pair = (row_id: string, signer_a: string, signer_b: string, shared_mints = '2'): Pair => ({row_id,signer_a,signer_b,shared_mints,a_first:'1',b_first:'0',same_transaction:'1'});
const fixture = (): GraphData => ({wallets:['A','B','C','D','E','F'],rows:[pair('9007199254740993','A','B','10'),pair('1','A','C','10'),pair('2','B','C','10'),pair('3','C','D'),pair('4','D','E','10'),pair('5','D','F','10'),pair('6','E','F','10')]});
const signal = () => new AbortController().signal;
describe('real pinned Cytoscape projection', () => {
  it('page nodes and edges preserve complete addresses and exact evidence ordinals',async()=>{
    const model=await algorithms.build(fixture(),signal());const {graph}=await buildCanvas(model,{kind:'page'},false,signal(),()=>true);
    try {expect(graph.nodes().length).toBe(6);expect(graph.edges().length).toBe(7); const edge=graph.getElementById('pair:9007199254740993');expect(edge.data('index')).toBe(0);expect(edge.hasClass('page-pair')).toBe(true);expect(edge.data('shared')).toBe('10');expect(edge.source().data('wallet')).toBe('A');expect(edge.target().data('wallet')).toBe('B');} finally {graph.destroy();}
  });
  it('overview accounts for every group and all crossing pairs without inventing evidence',async()=>{
    const model=await algorithms.build(fixture(),signal());const {graph,projection}=await buildCanvas(model,{kind:'overview'},false,signal(),()=>true);
    try {expect(projection).toBeNull();expect(graph.nodes().length).toBe(2);expect(graph.edges().length).toBe(1);expect(graph.edges()[0].data('link').indices).toEqual([3]);expect(graph.edges()[0].data('index')).toBeUndefined();expect(model.internal+model.external).toBe(7);}finally{graph.destroy();}
  });
  it('groups include all internal edges and wallet focus crosses groups',async()=>{
    const model=await algorithms.build(fixture(),signal());
    const group=await buildCanvas(model,{kind:'group',key:0},false,signal(),()=>true);
    try {expect(group.graph.nodes().length).toBe(3);expect(group.graph.edges().length).toBe(3);expect(group.graph.getElementById('wallet:D').length).toBe(0);}finally{group.graph.destroy();}
    const wallet=await buildCanvas(model,{kind:'wallet',key:'C'},false,signal(),()=>true);
    try {expect(wallet.graph.getElementById('wallet:D').length).toBe(1);expect(wallet.graph.edges().length).toBe(3);expect(wallet.projection?.extra).toBe(1);expect(wallet.graph.getElementById('wallet:C').position()).toEqual({x:0,y:0});}finally{wallet.graph.destroy();}
  });
  it('optional neighbour links preserve incident counts and add the whole induced set',async()=>{
    const model=await algorithms.build(fixture(),signal());const {graph,projection}=await buildCanvas(model,{kind:'wallet',key:'C'},true,signal(),()=>true);
    try {expect(graph.edges().length).toBe(4);expect(projection?.incident).toBe(3);expect(projection?.extra).toBe(1);expect(graph.getElementById('pair:9007199254740993').length).toBe(1);}finally{graph.destroy();}
  });
  it('large groups retain every pair and have finite geometric positions',async()=>{
    const wallets=Array.from({length:160},(_,i)=>`w${String(i).padStart(3,'0')}`);const rows:Pair[]=[];
    for(let a=0;a<wallets.length;a++)for(let b=a+1;b<wallets.length;b++)rows.push(pair(String(rows.length),wallets[a],wallets[b]));
    const model=await algorithms.build({wallets,rows},signal());const {graph}=await buildCanvas(model,{kind:'group',key:0},false,signal(),()=>true);
    try {expect(graph.edges().length).toBe(12720);expect(graph.nodes().length).toBe(160);expect(graph.nodes().toArray().every(node=>Number.isFinite(node.position().x)&&Number.isFinite(node.position().y))).toBe(true);}finally{graph.destroy();}
  },15000);
  it('construction cancellation and ownership replacement reject before mounting',async()=>{
    const model=await algorithms.build(fixture(),signal());const task=new AbortController();const pending=buildCanvas(model,{kind:'overview'},false,task.signal,()=>true);task.abort();await expect(pending).rejects.toMatchObject({name:'AbortError'});
    await expect(buildCanvas(model,{kind:'page'},false,signal(),()=>false)).rejects.toMatchObject({name:'AbortError'});
    // A newer user selection during the yielded edge-batch phase retires the private candidate.
    let checkpoints=0;await expect(buildCanvas(model,{kind:'page'},false,signal(),()=>++checkpoints<2)).rejects.toMatchObject({name:'AbortError'});
  });
  it('empty views remain explicitly empty and disposal releases the graph',async()=>{
    const model=await algorithms.build({rows:[],wallets:[]},signal());const {graph}=await buildCanvas(model,{kind:'overview'},false,signal(),()=>true);expect(graph.elements().length).toBe(0);graph.destroy();expect(graph.destroyed()).toBe(true);
  });
});
