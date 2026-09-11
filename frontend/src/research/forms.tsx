import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api, type Schema } from '../api';
import { useSubmission } from '../forms';
import { useVisible } from '../workspace';
import { t, useLocale } from '../i18n';
import { Badge, Button, Card, Failure } from '../ui';
import { analysisSchema, prepareSchema, researchError, type Summary } from './contracts';

const initial = {from_block: '', to_block: '', snapshot_id: '', window_seconds: '60', minimum_shared_mints: '2', mode: 'NON_MAYHEM', wallets: ''};
// Form defaults follow a verified selection once; later edits do not relabel the committed result.
export function ResearchForms({summary}: {summary?: Summary}) {
  useLocale();
  const [values, setValues] = useState(initial), [failure, setFailure] = useState({prepare: '', analyze: ''});
  const prepare = useSubmission(), analyze = useSubmission();
  useEffect(() => {
    if (!summary) return;
    setValues(old => ({...old, from_block: String(summary.dataset.from_block_ordinal), to_block: String(summary.dataset.to_block_ordinal), snapshot_id: summary.analysis?.snapshot_id ?? summary.artifact_id, window_seconds: String(summary.analysis?.window_seconds ?? 60), minimum_shared_mints: String(summary.analysis?.minimum_shared_mints ?? 2), wallets: summary.analysis?.wallets.join('\n') ?? '', mode: summary.analysis ? summary.analysis.mode ?? 'ALL' : 'NON_MAYHEM'}));
  }, [summary]);
  const field = (name: keyof typeof initial, label: string, props: {min?: number; max?: number; type?: string; pattern?: string; maxLength?: number} = {}) => <label>{t(label)}<input name={name} value={values[name]} onChange={event => setValues(old => ({...old, [name]: event.target.value}))} required {...props} /></label>;
  async function submit(kind: 'prepare' | 'analyze') {
    setFailure(old => ({...old, [kind]: ''}));
    try {
      const body = kind === 'prepare' ? prepareSchema.parse({from_block: Number(values.from_block), to_block: Number(values.to_block)}) : analysisSchema.parse({snapshot_id: values.snapshot_id, window_seconds: Number(values.window_seconds), minimum_shared_mints: Number(values.minimum_shared_mints), mode: values.mode, wallets: values.wallets.trim() ? values.wallets.trim().split(/\s+/) : []});
      await (kind === 'prepare' ? prepare : analyze).submit(JSON.stringify(body), async () => ({path: `/api/v1/research/${kind}`, body}));
    } catch (error) {setFailure(old => ({...old, [kind]: researchError(error)}));}
  }
  return <div className="research-forms"><Card><p className="eyebrow">{t('01 / Observations')}</p><h2>{t('Save observations')}</h2><form aria-label={t('Prepare research snapshot')} aria-busy={prepare.busy} onSubmit={event => {event.preventDefault(); void submit('prepare');}}>
    {field('from_block', 'From block, inclusive', {type:'number', min:0, max:2**32 - 1})}{field('to_block', 'To block, exclusive', {type:'number', min:1, max:2**32})}
    <p className="subtle">{t('Up to 300,000 blocks, 2 million swaps and 50,000 tokens. The snapshot retains successful SOL-paired Pump.fun swaps and available creation-mode data from the same configured source.')}</p><Button tone="primary" disabled={prepare.busy}>{t(prepare.busy ? 'Submitting…' : 'Prepare snapshot')}</Button><Receipt operation={prepare} failure={failure.prepare} />
  </form></Card><Card><p className="eyebrow">{t('02 / Hypothesis')}</p><h2>{t('Find co-purchases')}</h2><form aria-label={t('Analyze wallets')} aria-busy={analyze.busy} onSubmit={event => {event.preventDefault(); void submit('analyze');}}>
    {field('snapshot_id','Research snapshot ID',{pattern:'[0-9a-f]{64}',maxLength:64})}<div className="form-grid">{field('window_seconds','Window, seconds',{type:'number',min:0,max:3600})}{field('minimum_shared_mints','Minimum shared tokens',{type:'number',min:1,max:2000000})}</div>
    <label>{t('Token mode')}<select name="mode" value={values.mode} onChange={event => setValues(old => ({...old, mode: event.target.value}))}><option value="NON_MAYHEM">{t('Without Mayhem')}</option><option value="ALL">{t('All modes')}</option></select></label>
    <p className="subtle">{t('Without Mayhem keeps only confirmed ordinary tokens. Mayhem and unknown modes are excluded before first purchases and pair thresholds. To change the result’s mode, run a new analysis.')}</p>
    {summary && summary.dataset.schema !== 'research-dataset-spec/v2' && <p className="notice">{t('This snapshot has no token modes. Prepare a new snapshot for Without Mayhem, or use All modes.')}</p>}
    <label>{t('Signers, optional')}<textarea name="wallets" rows={2} value={values.wallets} onChange={event => setValues(old => ({...old, wallets: event.target.value}))} placeholder={t('Addresses separated by spaces or newlines; up to 128')} maxLength={5760} /></label>
    <p className="subtle">{t('An empty signer list includes all observed signers. Compare only the first BUY of each token by each wallet inside the snapshot; later purchases of the same token are ignored.')}</p>
    <Button tone="primary" disabled={analyze.busy}>{t(analyze.busy ? 'Submitting…' : 'Run analysis')}</Button><Receipt operation={analyze} failure={failure.analyze} />
  </form></Card></div>;
}

// A submission receipt is followed through durable state independently from bounded recent-job pages.
function Receipt({operation, failure}: {operation: ReturnType<typeof useSubmission>; failure: string}) {
  return <>{(failure || operation.failure) && <Failure message={failure || operation.failure} />}{operation.receipt && <SubmittedResearchJob key={operation.receipt.job_id} receipt={operation.receipt} />}</>;
}
function SubmittedResearchJob({receipt}: {receipt: Schema<'JobResponse'>}) {
  const visible = useVisible();
  const query = useQuery<Schema<'JobResponse'>>({queryKey:['research-submitted-job',receipt.job_id], enabled:visible, refetchInterval: query => visible && ['QUEUED','STARTING','RUNNING'].includes(query.state.data?.state ?? receipt.state) ? 2000 : false, queryFn: ({signal}) => api<Schema<'JobResponse'>>(`/api/v1/jobs/${receipt.job_id}`,{signal})});
  const job = query.data ?? receipt;
  return <div className="receipt research-receipt" role="status"><code>{job.job_id}</code><Badge>{job.state}</Badge>{job.state === 'SUCCEEDED' && <Button asChild><Link to={`/research?job=${encodeURIComponent(job.job_id)}`}>{t('Open research output')}</Link></Button>}<Button asChild><Link to="/jobs">{t('Open queue')}</Link></Button>{query.isError && <Failure message={researchError(query.error)} retry={() => void query.refetch()} />}</div>;
}
