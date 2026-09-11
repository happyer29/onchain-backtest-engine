// @vitest-environment node
import { createHash } from 'node:crypto';
import { describe, expect, it, vi } from 'vitest';
import { createDemoClient, routeKey } from './client';

const digest=(value:string)=>createHash('sha256').update(value).digest('hex');
const body=JSON.stringify({amount:'9007199254740993001',rows:[]});
const route='/api/v1/research/'+ 'a'.repeat(64)+'/rows/pairs?limit=25';
const base=new URL('https://example.test/project/demo-data/');
function fixture(change:(value:Record<string,any>)=>void=()=>{}) {
  const record={file:`responses/${digest(body)}.json`,sha256:digest(body),bytes:Buffer.byteLength(body)};
  const manifest={schema:'backtest.static-demo/v1',recipe:'synthetic-wallet-groups-and-copy-outcomes/v1',synthetic:true,wallets:60,snapshot:'a'.repeat(64),research:[{id:'b'.repeat(64),mode:'NON_MAYHEM',counts:{pairs:'423'}},{id:'c'.repeat(64),mode:'ALL',counts:{pairs:'426'}}],runs:[{id:'d'.repeat(64),mode:'EXOGENOUS_REPLAY',title:'Strict',summary:{}},{id:'e'.repeat(64),mode:'EXOGENOUS_VIRTUAL_SETTLEMENT',title:'Virtual',summary:{}}],response_bytes:record.bytes,responses:{[route]:record}};
  change(manifest);const raw=JSON.stringify(manifest);
  const fetcher=vi.fn<typeof fetch>(async input=>new Response(String(input).endsWith('manifest.json')?raw:body));
  return {client:createDemoClient(base,digest(raw),fetcher),fetcher,raw};
}
describe('closed demo transport',()=>{
  it('uses project-relative static files and preserves wide amounts exactly',async()=>{
    const {client,fetcher}=fixture();expect(await (await client.request(route)).json()).toEqual(JSON.parse(body));
    expect(fetcher.mock.calls.map(([url])=>String(url))).toEqual([`${base}manifest.json`,`${base}responses/${digest(body)}.json`]);
    expect(fetcher.mock.calls.every(([,init])=>init?.credentials==='omit')).toBe(true);
    await client.request(route);expect(fetcher).toHaveBeenCalledTimes(3);
  });
  it.each(['POST','PUT','DELETE','PATCH'])('rejects %s before reading any file',async method=>{
    const {client,fetcher}=fixture();expect((await client.request(route,{method})).status).toBe(405);expect(fetcher).not.toHaveBeenCalled();
  });
  it('never falls back to the API for unknown keys or invalid inputs',async()=>{
    const {client,fetcher}=fixture();expect((await client.request('/api/v1/missing')).status).toBe(404);expect(fetcher).toHaveBeenCalledTimes(1);
    for(const input of ['https://elsewhere.test/api/v1/jobs','/api/v1/a/../jobs','/api/v1/jobs?limit=1&limit=2',new Request('https://example.test/api/v1/jobs')])expect((await client.request(input)).status).toBe(404);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it('canonicalizes paging parameter order without accepting duplicate keys',()=>{
    expect(routeKey('/api/v1/items?limit=25&cursor=a+b')).toBe('/api/v1/items?cursor=a+b&limit=25');
    expect(()=>routeKey('/api/v1/items?limit=1&limit=2')).toThrow();
  });
  it('detects a changed manifest before trusting any mapping',async()=>{
    const {fetcher,raw}=fixture();const client=createDemoClient(base,digest(raw+' '),fetcher);await expect(client.request(route)).rejects.toThrow('integrity');expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it.each([['changed',body.replace('9007','1007'),'integrity'],['short',body.slice(0,-1),'length'],['large',body+'x','size limit']])('rejects %s response bytes',async(_,bytes,error)=>{
    const {client,fetcher}=fixture();await client.catalog();fetcher.mockResolvedValue(new Response(bytes));await expect(client.request(route)).rejects.toThrow(error);
  });
  it('reports missing files and supports a later explicit retry',async()=>{
    const {client,fetcher,raw}=fixture();fetcher.mockResolvedValueOnce(new Response('',{status:404}));await expect(client.catalog()).rejects.toThrow('unavailable');fetcher.mockResolvedValueOnce(new Response(raw));await expect(client.catalog()).resolves.toHaveProperty('synthetic',true);
    fetcher.mockResolvedValue(new Response('',{status:404}));await expect(client.request(route)).rejects.toThrow('unavailable');
  });
  it.each([
    (m:Record<string,any>)=>m.responses[route].file='../../local.json',
    (m:Record<string,any>)=>m.response_bytes++,
    (m:Record<string,any>)=>m.research[0].counts.pairs='1001',
    (m:Record<string,any>)=>m.synthetic=false,
    (m:Record<string,any>)=>m.responses[route].bytes=2097153,
  ])('rejects invalid corpus contracts',async change=>{const {client,fetcher}=fixture(change);await expect(client.request(route)).rejects.toThrow();expect(fetcher).toHaveBeenCalledTimes(1);});
  it('honors cancellation before I/O and during response loading',async()=>{
    const {client,fetcher}=fixture();const cancelled=AbortSignal.abort();await expect(client.request(route,{signal:cancelled})).rejects.toThrow();expect(fetcher).not.toHaveBeenCalled();
    await client.catalog();fetcher.mockImplementation(async(_input,init)=>new Promise((_resolve,reject)=>init?.signal?.addEventListener('abort',()=>reject(init.signal?.reason),{once:true})));
    const controller=new AbortController(),pending=client.request(route,{signal:controller.signal});await Promise.resolve();controller.abort();await expect(pending).rejects.toThrow();
  });
});
