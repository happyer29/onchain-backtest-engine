import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import { queryClient } from '../api';
import { ResearchForms } from './forms';
import { analysisSchema, prepareSchema } from './contracts';
const wrapper=({children}:{children:React.ReactNode})=><QueryClientProvider client={queryClient}><MemoryRouter>{children}</MemoryRouter></QueryClientProvider>;
afterEach(()=>{queryClient.clear();vi.unstubAllGlobals();});
const fill = (label:string,value:string) => fireEvent.change(screen.getByLabelText(label),{target:{value}});
it('submits all signers with exact mode/window and keeps one idempotent retry on uncertain failure',async()=>{
  const requests:{url:string;init:RequestInit;resolve:(response:Response)=>void}[]=[];
  vi.stubGlobal('fetch',vi.fn((url:string,init:RequestInit)=>new Promise<Response>(resolve=>requests.push({url,init,resolve}))));
  render(<ResearchForms />,{wrapper});fill('Research snapshot ID','a'.repeat(64));fill('Window, seconds','1000');
  fireEvent.submit(screen.getByRole('form',{name:'Analyze wallets'}));fireEvent.submit(screen.getByRole('form',{name:'Analyze wallets'}));
  await waitFor(()=>expect(requests).toHaveLength(1));expect(JSON.parse(requests[0].init.body as string)).toEqual({snapshot_id:'a'.repeat(64),window_seconds:1000,minimum_shared_mints:2,mode:'NON_MAYHEM',wallets:[]});
  expect(requests[0].init.headers).toMatchObject({'X-Backtest-CSRF':'1'});
  await act(async()=>requests[0].resolve(new Response(JSON.stringify({code:'TEMPORARY',message:'Try again'}),{status:503})));
  expect(await screen.findByRole('alert')).toHaveTextContent('Try again');fireEvent.submit(screen.getByRole('form',{name:'Analyze wallets'}));
  await waitFor(()=>expect(requests).toHaveLength(2));expect(requests[1].init.headers).toEqual(requests[0].init.headers);
});
it('invalid block ranges and signer limits reject before transport',async()=>{
  const fetch=vi.fn();vi.stubGlobal('fetch',fetch);render(<ResearchForms />,{wrapper});fill('From block, inclusive','200');fill('To block, exclusive','100');fireEvent.submit(screen.getByRole('form',{name:'Prepare research snapshot'}));expect(await screen.findByRole('alert')).toBeVisible();expect(fetch).not.toHaveBeenCalled();
  expect(prepareSchema.safeParse({from_block:0,to_block:300001}).success).toBe(false);
  expect(analysisSchema.safeParse({snapshot_id:'a'.repeat(64),window_seconds:1000,minimum_shared_mints:2,mode:'ALL',wallets:Array(129).fill('1'.repeat(32))}).success).toBe(false);
});
it('selecting All modes changes the command, not an already committed result',async()=>{
  let body:unknown;vi.stubGlobal('fetch',vi.fn((_url:string,init:RequestInit)=>{body=JSON.parse(init.body as string);return new Promise(()=>{});}));
  render(<ResearchForms />,{wrapper});fill('Research snapshot ID','b'.repeat(64));fill('Token mode','ALL');fill('Signers, optional','1'.repeat(32));fireEvent.submit(screen.getByRole('form',{name:'Analyze wallets'}));await waitFor(()=>expect(body).toMatchObject({mode:'ALL',wallets:['1'.repeat(32)]}));
});

// A missing optional graph bundle must not hide independently verified evidence or forms.
it('isolates graph rendering failure from the research table',async()=>{
  const {GraphBoundary}=await import('./page');
  const diagnostic=vi.spyOn(console,'error').mockImplementation(()=>{});
  function Broken(){throw new Error('Unavailable graph chunk');return null;}
  try {render(<><GraphBoundary><Broken /></GraphBoundary><p>Verified purchase evidence remains visible</p></>);expect(screen.getByRole('alert')).toHaveTextContent('graph renderer is unavailable');expect(screen.getByText('Verified purchase evidence remains visible')).toBeVisible();}finally{diagnostic.mockRestore();}
});
