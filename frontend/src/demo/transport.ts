import { createDemoClient } from './client';
declare const __DEMO_MANIFEST_SHA256__: string;
// This module is selected by the separate demo build, never by an operational API error.
export const demoClient=createDemoClient(new URL('./demo-data/',document.baseURI),__DEMO_MANIFEST_SHA256__);
export const request:typeof fetch=demoClient.request;
