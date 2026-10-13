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

const historicalRoute = '/api/v1/run-artifacts/' + 'd'.repeat(64) + '/strategy-summary';
function historicalFixture(change: (value: Record<string, any>) => void = () => {}, responseBody = body) {
  const record = { file: `responses/${digest(responseBody)}.json`, sha256: digest(responseBody), bytes: Buffer.byteLength(responseBody) };
  const manifest = {
    schema: 'backtest.static-history/v1', recipe: 'indexer-two-hour-results/v1', synthetic: false, version: '0.2.0',
    source: { name: 'OnchainDivers', start_utc: '2026-09-09T12:00:00Z', end_utc: '2026-09-09T14:00:00Z', duration_seconds: 7200, from_block_ordinal: '9007199254740993000', to_block_ordinal: '9007199254740994000', snapshot_ids: ['a'.repeat(64)] },
    runs: [{ id: 'd'.repeat(64), mode: 'EXOGENOUS_REPLAY', title: 'Historical Sniping', summary: {} }],
    response_bytes: record.bytes, responses: { [historicalRoute]: record },
  };
  change(manifest); const raw = JSON.stringify(manifest);
  const fetcher = vi.fn<typeof fetch>(async input => new Response(String(input).endsWith('manifest.json') ? raw : responseBody));
  return { client: createDemoClient(base, digest(raw), fetcher), fetcher };
}
describe('closed historical transport', () => {
  it('admits a verified two-hour historical catalog without synthetic research', async () => {
    const { client, fetcher } = historicalFixture();
    const catalog = await client.catalog();
    expect(catalog.synthetic).toBe(false);
    if (catalog.synthetic) throw new Error('Expected historical catalog');
    expect(catalog.source.duration_seconds).toBe(7200);
    expect(catalog.source.from_block_ordinal).toBe('9007199254740993000');
    expect(catalog).not.toHaveProperty('research');
    expect(await (await client.request(historicalRoute)).json()).toEqual(JSON.parse(body));
    expect(fetcher.mock.calls.every(([, init]) => init?.credentials === 'omit')).toBe(true);
  });
  it.each([400, 404, 409, 422, 503])('preserves verified API error status %s without falling back', async status => {
    const error = { code: 'CHART_UNAVAILABLE', message: 'Historical chart exceeds its query limit.' };
    const { client, fetcher } = historicalFixture(m => { m.responses[historicalRoute].status = status; }, JSON.stringify(error));
    const response = await client.request(historicalRoute);
    expect(response.status).toBe(status); expect(await response.json()).toEqual(error);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
  it('still rejects execution before reading historical files', async () => {
    const { client, fetcher } = historicalFixture();
    expect((await client.request('/api/v1/jobs', { method: 'POST', body: '{}' })).status).toBe(405);
    expect(fetcher).not.toHaveBeenCalled();
  });
  it.each([
    (m: Record<string, any>) => m.source.end_utc = '2026-09-09T14:00:01Z',
    (m: Record<string, any>) => m.source.start_utc = '2026-09-09T15:00:00+03:00',
    (m: Record<string, any>) => m.source.duration_seconds = 3600,
    (m: Record<string, any>) => m.source.to_block_ordinal = m.source.from_block_ordinal,
    (m: Record<string, any>) => m.source.snapshot_ids.push(m.source.snapshot_ids[0]),
    (m: Record<string, any>) => m.runs.push(m.runs[0]),
    (m: Record<string, any>) => m.runs = [],
    (m: Record<string, any>) => m.runs = Array.from({ length: 17 }, (_, i) => ({ ...m.runs[0], id: i.toString(16).padStart(64, '0') })),
    (m: Record<string, any>) => m.recipe = 'synthetic-wallet-groups-and-copy-outcomes/v1',
    (m: Record<string, any>) => m.synthetic = true,
    (m: Record<string, any>) => m.response_bytes = 256 * 1024 ** 2 + 1,
    (m: Record<string, any>) => m.responses[historicalRoute].status = 302,
    (m: Record<string, any>) => m.source.password = 'unexportable',
  ])('rejects inconsistent historical source and result metadata', async change => {
    const { client, fetcher } = historicalFixture(change);
    await expect(client.catalog()).rejects.toThrow(); expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it('does not extend the synthetic contract to recorded error responses', async () => {
    const { client } = fixture(m => { m.responses[route].status = 503; });
    await expect(client.catalog()).rejects.toThrow();
  });
});
