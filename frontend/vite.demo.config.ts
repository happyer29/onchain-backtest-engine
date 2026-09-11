import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
const file=(path:string)=>fileURLToPath(new URL(path,import.meta.url));
const digest=readFileSync(file('./demo-data/manifest.sha256'),'utf8').trim();
if(!/^[0-9a-f]{64}$/.test(digest))throw new Error('Generate the verified demo corpus before building.');
export default defineConfig({root:file('./demo'),base:'./',publicDir:file('./public'),plugins:[react(),tailwindcss()],
 resolve:{alias:[{find:'./http',replacement:file('./src/demo/transport.ts')},{find:'../http',replacement:file('./src/demo/transport.ts')}]},
 define:{__DEMO_MANIFEST_SHA256__:JSON.stringify(digest)},
 build:{outDir:file('./demo-dist'),emptyOutDir:true,manifest:true},});
