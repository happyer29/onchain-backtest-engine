// @vitest-environment node
import { describe, expect, it, vi } from 'vitest';
import forceAtlas2 from 'graphology-layout-forceatlas2';
import { buildDisplayGraph } from './sigma-data';
import { applyCoordinates, iterations, layoutInput, layoutOutput, layoutPolicy, layoutSettings, layoutStep, validateInput } from './layout-core';
import { runLayout, type WorkerLike } from './layout-client';
import { ViewMemory } from './navigation';
import algorithms from './research-graph-model';
const signal = () => new AbortController().signal;
async function graph() {const model=await algorithms.build({wallets:['A','B','C','D'],rows:[['A','B','7'],['B','C','2'],['A','D','9']].map(([signer_a,signer_b,shared_mints],i)=>({row_id:String(i),signer_a,signer_b,shared_mints,a_first:'0',b_first:'0',same_transaction:shared_mints}))},signal());return (await buildDisplayGraph(model,{kind:'wallet',key:'A'},true,signal())).graph;}
describe('bounded worker layout and coordinate navigation',()=>{
  it('matches the pinned public ForceAtlas2 oracle byte for byte with a fixed centre',async()=>{
    const actual=await graph(),expected=actual.copy();const input=await layoutInput(actual,signal());validateInput(input);
    for(let i=0;i<iterations;i++)layoutStep(input);applyCoordinates(actual,layoutOutput(input).coordinates);
    forceAtlas2.assign(expected,{iterations,settings:layoutSettings(expected.order)});
    expect(actual.mapNodes((_,a)=>[a.x,a.y])).toEqual(expected.mapNodes((_,a)=>[a.x,a.y]));expect(actual.getNodeAttributes('wallet:A')).toMatchObject({x:0,y:0});
  });
  it('rejects invalid matrix topology and nonfinite coordinates',()=>{
    expect(()=>validateInput({nodes:new Float32Array(50010),edges:new Float32Array()})).toThrow();expect(()=>validateInput({nodes:new Float32Array(20),edges:new Float32Array([0,30,1])})).toThrow();expect(()=>layoutOutput({nodes:Float32Array.from([NaN,0,0,0,0,0,1,1,1,0]),edges:new Float32Array()})).toThrow();
  });
  it('retains at most eight camera/coordinate snapshots without graph or edge copies',async()=>{
    const g=await graph(),memory=new ViewMemory(),camera={x:.2,y:.7,ratio:.4,angle:0};memory.save('first',g,camera);g.setNodeAttribute('wallet:A','x',42);
    expect(memory.read('first',g.order)?.coordinates[0]).not.toBe(42);expect(memory.read('first',g.order)?.camera).toEqual(camera);expect(memory.read('first',100)).toBeUndefined();
    for(let i=0;i<8;i++)memory.save(String(i),g,camera);expect(memory.size).toBe(8);expect(memory.read('first',g.order)).toBeUndefined();memory.clear();expect(memory.size).toBe(0);
  });
  it('worker completion validates exact coordinates and terminates before resolving',async()=>{
    const g=await graph();let fake: WorkerLike;
    fake={onmessage:null,onerror:null,onmessageerror:null,terminate:vi.fn(),postMessage:()=>{queueMicrotask(()=>fake.onmessage?.({data:{type:'done',policy:layoutPolicy,iterations,coordinates:new Float32Array(g.order*2)}} as MessageEvent));}};
    expect((await runLayout(g,signal(),()=>{},()=>fake)).length).toBe(g.order*2);expect(fake.terminate).toHaveBeenCalledOnce();expect(fake.onmessage).toBeNull();
  });
  it('worker abort, malformed output and runtime errors never complete a view',async()=>{
    const g=await graph();const task=new AbortController();let started:()=>void=()=>{};const pendingStart=new Promise<void>(resolve=>started=resolve);
    const fake:WorkerLike={onmessage:null,onerror:null,onmessageerror:null,terminate:vi.fn(),postMessage:()=>started()};
    const pending=runLayout(g,task.signal,()=>{},()=>fake);await pendingStart;const stale=fake.onmessage;task.abort();await expect(pending).rejects.toMatchObject({name:'AbortError'});expect(fake.terminate).toHaveBeenCalledOnce();stale?.({data:{type:'done',policy:layoutPolicy,iterations,coordinates:new Float32Array(g.order*2)}} as MessageEvent);
    for(const data of [null,{type:'done',policy:layoutPolicy,iterations,coordinates:new Float32Array(1)},{type:'error'}]){const bad:WorkerLike={onmessage:null,onerror:null,onmessageerror:null,terminate:vi.fn(),postMessage:()=>queueMicrotask(()=>bad.onmessage?.({data} as MessageEvent))};await expect(runLayout(g,signal(),()=>{},()=>bad)).rejects.toThrow();expect(bad.terminate).toHaveBeenCalledOnce();}
  });
});
