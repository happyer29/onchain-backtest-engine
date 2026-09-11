// Only a verified closed corpus is copied into the independently built Pages directory.
import {readFile, readdir, stat, cp, writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const root=fileURLToPath(new URL('../',import.meta.url)),data=path.join(root,'demo-data'),out=path.join(root,'demo-dist');
const hash=bytes=>createHash('sha256').update(bytes).digest('hex');
const raw=await readFile(path.join(data,'manifest.json')),expected=(await readFile(path.join(data,'manifest.sha256'),'utf8')).trim();
if(raw.length>1024**2||hash(raw)!==expected)throw new Error('Invalid demo manifest.');
const manifest=JSON.parse(raw),records=Object.entries(manifest.responses);
if(manifest.schema!=='backtest.static-demo/v1'||manifest.synthetic!==true||records.length>2048||manifest.wallets>100||manifest.runs.length!==2)throw new Error('Invalid demo corpus.');
let total=0;const allowed=new Set(['manifest.json','manifest.sha256']);
for(const [route,record]of records){
 if(!route.startsWith('/api/v1/')||!/^responses\/[0-9a-f]{64}\.json$/.test(record.file)||record.file!==`responses/${record.sha256}.json`)throw new Error('Invalid demo route or path.');
 const file=path.join(data,record.file),info=await stat(file);if(!info.isFile()||info.size!==record.bytes||info.size>2*1024**2)throw new Error('Invalid demo response size.');
 const bytes=await readFile(file);if(hash(bytes)!==record.sha256)throw new Error('Corrupt demo response.');JSON.parse(bytes);
 if(/(?:\/Users\/|\/private\/|\/tmp\/|\.env\b|secret_ref|password|127\.0\.0\.1|localhost)/i.test(bytes.toString()))throw new Error('Non-exportable local metadata in demo.');
 total+=bytes.length;allowed.add(record.file);
}
if(total!==manifest.response_bytes||total>16*1024**2)throw new Error('Invalid demo total size.');
async function files(dir,prefix=''){const list=[];for(const entry of await readdir(dir,{withFileTypes:true})){if(entry.isSymbolicLink())throw new Error('Links cannot enter demo distribution.');const name=prefix+entry.name;if(entry.isDirectory())list.push(...await files(path.join(dir,entry.name),name+'/'));else list.push(name);}return list;}
for(const file of await files(data))if(!allowed.has(file))throw new Error('Unexpected demo data file: '+file);
const html=await readFile(path.join(out,'index.html'),'utf8');if(!html.includes('Content-Security-Policy')||!html.includes('form-action &#39;none&#39;')&&!html.includes("form-action 'none'"))throw new Error('Demo CSP missing.');
await cp(data,path.join(out,'demo-data'),{recursive:true});await writeFile(path.join(out,'.nojekyll'),'');
const distribution=await files(out);for(const name of distribution){if(!/^(?:assets\/[A-Za-z0-9_.-]+\.(?:js|css)|demo-data\/(?:manifest\.(?:json|sha256)|responses\/[0-9a-f]{64}\.json)|\.vite\/manifest\.json|index\.html|theme\.js|third-party-licenses\.txt|\.nojekyll)$/.test(name))throw new Error('Unexpected public file: '+name);}
const entries=await Promise.all(distribution.sort().map(async file=>{const bytes=await readFile(path.join(out,file));return {file,bytes:bytes.length,sha256:hash(bytes)};}));
await writeFile(path.join(out,'distribution.json'),JSON.stringify({schema:'backtest.demo-distribution/v1',synthetic:true,files:entries}));
console.log(`Verified static demo: ${records.length} response routes, ${total} response bytes; ${entries.length} public files.`);
