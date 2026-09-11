import { t, useLocale } from './i18n';
import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { useForm, type UseFormReturn } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useQuery } from '@tanstack/react-query';
// Forms share accessible disclosure controls; the page never becomes a step wizard.
import * as Accordion from '@radix-ui/react-accordion';
import { Link, useSearchParams } from 'react-router-dom';
import { ChevronDown, Play, CheckCircle2 } from 'lucide-react';
import { api, digest, encode, errorText, type Json, type Schema } from './api';
import { datasetPlan, firstSwapDraft, integer, mlCommand, mlPaths, physical, pumpDraft, tokens, type MlKind, type Values } from './commands';
// Field metadata contains labels/defaults only; React owns every rendered control and action.
import catalog from './form-fields.json';
import { Badge, Button, Card, Failure, Loading, PageTitle } from './ui';
import { FactTree } from './results';
import { recordSubmission } from './workspace';

// Declarative field metadata supplies labels and constraints, never executable strategy code.
export type Field = { name: string; label: string; kind: string; type: string; default: string; required: boolean; options: { value: string; label: string }[]; min?: string; max?: string; minlength?: string; maxlength?: string; inputmode?: string };
export type Group = { id: string; title: string; description: string; fields: Field[]; open?: boolean };
const fields = (key: keyof typeof catalog): Field[] => catalog[key];
const select = (field: Field, values: string[]) => ({ ...field, default: values[0] ?? '', options: values.map(value => ({ value, label: value })) });
// The client validates syntax/bounds while authoritative domain policy stays in the resolver.
export function formSchema(items: Field[]) {
  return z.object(Object.fromEntries(items.map(field => [field.name, z.string().superRefine((value, ctx) => {
    const fail = (message: string) => ctx.addIssue({ code: 'custom', message });
    if (!value.trim()) { if (field.required) fail(t("This field is required")); return; }
    if (field.minlength && value.length < Number(field.minlength)) fail(t("At least {0} characters", [field.minlength]));
    // Keep wide atomic values as lexical integers rather than HTML number coercions.
    if (field.maxlength && value.length > Number(field.maxlength)) fail(t("At most {0} characters", [field.maxlength]));
    if (field.options.length && !field.options.some(option => option.value === value)) fail(t("Choose a supported value"));
    if (field.type === 'number' || field.inputmode === 'numeric') {
      if (!/^(0|[1-9][0-9]*)$/.test(value)) { fail(t("Enter a nonnegative integer")); return; }
      // BigInt comparisons validate exact UI bounds, including values above Number.MAX_SAFE_INTEGER.
      const number = BigInt(value);
      if (number > 18446744073709551615n) fail(t("Value exceeds UInt64"));
      if (field.min && number < BigInt(field.min)) fail(t("Minimum {0}", [field.min]));
      if (field.max && number > BigInt(field.max)) fail(t("Maximum {0}", [field.max]));
    }
  })])));
}

// Unique IDs keep labels and errors bound correctly across simultaneous form sections.
function FieldControl({ field, form }: { field: Field; form: UseFormReturn<Values> }) {
  useLocale();
  const unique = useId();
  const id = `${unique}-${field.name}`;
  const error = form.formState.errors[field.name]?.message;
  const props = { id, ...form.register(field.name), 'aria-invalid': !!error, 'aria-describedby': error ? `${id}-error` : undefined };
  // Text inputs avoid exponent/spinner rounding; exact numeric rules run through Zod.
  return <div className={`form-field ${field.kind === 'textarea' ? 'wide' : ''}`}><label htmlFor={id}>{t(field.label)}{field.required && <span aria-hidden="true"> *</span>}</label>
    {field.kind === 'select' ? <select {...props}>{field.options.map(option => <option key={option.value} value={option.value}>{t(option.label)}</option>)}</select> : field.kind === 'textarea' ? <textarea {...props} rows={4} maxLength={field.maxlength ? Number(field.maxlength) : 6000} /> : <input {...props} type="text" inputMode={field.type === 'number' || field.inputmode === 'numeric' ? 'numeric' : 'text'} maxLength={field.maxlength ? Number(field.maxlength) : 6000} autoComplete="off" />}
    {error && <small id={`${id}-error`} className="field-error">{t(String(error))}</small>}</div>;
}

// Disclosure state is presentation-only; hidden fields remain registered and validated.
export function FormFields({ groups, form }: { groups: Group[]; form: UseFormReturn<Values> }) {
  useLocale();
  const [open, setOpen] = useState(groups.filter(group => group.open).map(group => group.id));
  const errors = form.formState.errors;
  // Invalid fields open their containing disclosure before focus, without losing other sections.
  useEffect(() => { const invalid = groups.filter(group => group.fields.some(field => errors[field.name])).map(group => group.id); if (invalid.length) setOpen(old => [...new Set([...old, ...invalid])]); }, [errors, groups]);
  return <Accordion.Root type="multiple" value={open} onValueChange={setOpen} className="form-sections">{groups.filter(group => group.fields.length).map((group, index) => <Accordion.Item key={group.id} value={group.id} className="form-section"><Accordion.Header><Accordion.Trigger className="form-section-trigger"><span className="step-number">{String(index + 1).padStart(2, '0')}</span><span><strong>{t(group.title)}</strong><small>{t(group.description)}</small></span><ChevronDown size={18} /></Accordion.Trigger></Accordion.Header><Accordion.Content forceMount className="form-section-content"><div className="form-grid">{group.fields.map(field => <FieldControl key={field.name} field={field} form={form} />)}</div></Accordion.Content></Accordion.Item>)}</Accordion.Root>;
}

// The same immutable field list supplies defaults and validation, preventing hidden control drift.
function useTypedForm(groups: Group[]) {
  const items = useMemo(() => groups.flatMap(group => group.fields), [groups]);
  return useForm<Values>({ defaultValues: Object.fromEntries(items.map(field => [field.name, field.default])), resolver: zodResolver(formSchema(items)), shouldFocusError: false });
}

// Pending intent survives uncertain transport failure but is cleared only by a durable receipt.
type Submission = { fingerprint: string; key: string; body?: unknown; path?: string; nonce: string; resolveBody?: unknown };
export function useSubmission() {
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState('');
  const [receipt, setReceipt] = useState<Schema<'JobResponse'> | null>(null);
  // The ref closes the synchronous double-click gap and keeps uncertain retries identical.
  const running = useRef(false);
  const pending = useRef<Submission | null>(null);
  async function submit(fingerprint: string, prepare: (attempt: Submission) => Promise<{ path: string; body: unknown }>) {
    if (running.current) return;
    running.current = true; setBusy(true); setFailure(''); setReceipt(null);
    try {
      // A changed form is a new intentional operation; an unchanged failed request retains its key.
      const attempt = pending.current?.fingerprint === fingerprint ? pending.current : { fingerprint, key: digest(), nonce: digest() };
      pending.current = attempt;
      if (!attempt.path) Object.assign(attempt, await prepare(attempt));
      const job = await api<Schema<'JobResponse'>>(attempt.path!, { method: 'POST', body: attempt.body, key: attempt.key });
      setReceipt(job); recordSubmission(job); pending.current = null;
      // An authoritative receipt completes the operation even if refreshing the queue later fails.
    } catch (error) { setFailure(errorText(error)); } finally { running.current = false; setBusy(false); }
  }
  return { busy, failure, receipt, submit };
}
// A returned receipt links to the supervisor queue without implying the heavy job has finished.
function SubmissionResult({ operation }: { operation: ReturnType<typeof useSubmission> }) {
  useLocale();
  return <>{operation.failure && <Failure message={operation.failure} />}{operation.receipt && <div className="receipt" role="status"><CheckCircle2 size={22} /><div><strong>{t("Job queued")}</strong><code>{operation.receipt.job_id}</code></div><Button asChild><Link to="/jobs">{t("Open queue")}</Link></Button></div>}</>;
}

// Contract discovery prevents stale UI metadata from silently changing admitted semantics.
export function validateRunContract(data: Schema<'RunContractListResponse'>, family: 'sniping' | 'copy') {
  const schema = family === 'copy' ? 'pumpfun-copy-buy-run-draft/v1' : 'pumpfun-sniping-run-draft/v3';
  const contract = data.items.find(item => item.schema === schema);
  const expected: Record<string, string> = family === 'copy' ? { maximum_sell_attempts: '4', sell_retry_seconds: '2', mint_entry_limit: '1' } : { buy_delay_transactions: '500', cooldown_seconds: '600', quote_asset: 'SOL', sell_all: 'true', sell_decision_delay_seconds: '2' };
  // Discovery drift disables the form rather than silently changing fixed strategy semantics.
  if (!contract || Object.entries(expected).some(([key, value]) => contract.fixed_semantics[key] !== value)) throw new Error(t("The strategy contract is incompatible with this interface."));
  const mode = contract.editable_fields.find(field => field.name === 'execution_mode');
  if (!mode || mode.kind !== 'CLOSED_ENUM' || !mode.required || encode(mode.enum_values) !== encode(['EXOGENOUS_REPLAY', 'EXOGENOUS_VIRTUAL_SETTLEMENT'])) throw new Error(t("The execution_mode contract is incompatible with this interface."));
  return contract;
}

// Closed family capability sets keep unsupported physical and semantic controls out of drafts.
const copyFields = new Set(['signing_wallets', 'take_profit_bps', 'stop_loss_bps', 'maximum_hold_seconds', 'observation_delay_transactions', 'buy_delay_transactions']);
const physicalFields = new Set(['run_backend', 'reader_batch_rows', 'reader_readahead', 'output_buffer_rows', 'run_threads']);
const backendChoices = { sniping: ['reference-pumpfun-sniping-v1', 'numpy-mmap-pumpfun-sniping-v1'], copy: ['reference-pumpfun-copy-buy-v1'], firstswap: ['reference-python-v1', 'numpy-mmap-first-swap-exact-v1'] };
// Each field is assigned exactly once, so advanced controls remain discoverable without duplication.
function runGroups(family: keyof typeof backendChoices): Group[] {
  const all = fields(family === 'firstswap' ? 'backtest-form' : 'sniping-form').filter(field => field.name !== 'pumpfun-strategy' && (family === 'copy' ? field.name !== 'delivery_schedule_id' : !copyFields.has(field.name))).map(field => field.name === 'run_backend' ? select(field, backendChoices[family]) : family !== 'firstswap' && field.name === 'execution_mode' ? select(field, ['EXOGENOUS_REPLAY', 'EXOGENOUS_VIRTUAL_SETTLEMENT']) : field);
  const definitions: [string, string, string, (name: string) => boolean][] = [
    ['inputs', t("Data and strategy"), t("Exact input artifacts and trading pair"), name => ['dataset_revision_id', 'snapshot_id', 'replay_pack_id', 'delivery_schedule_id', 'pool_id', 'sold_asset_id', 'bought_asset_id', 'signing_wallets'].includes(name)],
    ['policy', t("Entry and exit"), t("Position size, execution, delays and limits"), name => !physicalFields.has(name) && !/^(wallet_|pump_|uva_|legacy_ata_|token_2022_ata_|buy_fee_|sell_fee_|buy_transaction_|sell_transaction_|buy_signature_|sell_signature_|buy_lamports_|sell_lamports_|buy_compute_|sell_compute_|buy_micro_|sell_micro_|feature_|model_|prediction_|inference_|root_seed|sweep_seeds)/.test(name)],
    // Fee profiles are separate from the buy/sell slippage controls above.
    ['accounts', t("Wallet and deposits"), t("UVA and separate ATAs for each token"), name => /^(wallet_|uva_|legacy_ata_|token_2022_ata_)/.test(name)],
    ['pump-fees', t("Pump fees"), t("Formula versions, components and effective interval"), name => name.startsWith('pump_')],
    ['network-fees', t("Network fees"), t("Independent buy and sell profiles"), name => /^(buy_|sell_)/.test(name)],
    ['ml', t("Models and features"), t("Exact dependencies and causal availability"), name => /^(feature_|model_|prediction_|inference_)/.test(name)],
    // Seeds are semantic, while resource settings affect only the physical attempt.
    ['seeds', t("Reproducibility"), t("Root seed and FirstSwap run series"), name => ['root_seed', 'sweep_seeds'].includes(name)],
    ['physical', t("Execution resources"), t("Backend, reader and output buffers"), name => physicalFields.has(name)],
  ];
  // Ordered assignment prevents a broad predicate from duplicating a field in two sections.
  const remaining = new Set(all.map(field => field.name));
  return definitions.map(([id, title, description, predicate], index) => ({ id, title, description, open: index < 2, fields: all.filter(field => remaining.has(field.name) && predicate(field.name) && remaining.delete(field.name)) }));
}

// Route selection remounts the family form so previous strategy values cannot leak into a draft.
export function Launch() {
  useLocale();
  const [params, setParams] = useSearchParams();
  const family = params.get('strategy') === 'copy' ? 'copy' : params.get('strategy') === 'firstswap' ? 'firstswap' : 'sniping';
  return <><PageTitle eyebrow={t("New experiment")} title={t("Launch strategy")} /><div className="strategy-selector" role="group" aria-label={t("Strategy")}>{(['sniping', 'copy', 'firstswap'] as const).map(key => <button key={key} aria-pressed={family === key} onClick={() => setParams({ strategy: key })}><strong>{key === 'sniping' ? 'Pump.fun Sniping' : key === 'copy' ? 'Pump.fun Copy Buy' : 'FirstSwap'}</strong><span>{key === 'sniping' ? t("Enter at token creation") : key === 'copy' ? t("Copy wallet BUY signals") : t("First available swap")}</span></button>)}</div><RunForm key={family} family={family} /></>;
}

// The launch form waits for both admitted semantic discovery and the local physical profile.
function RunForm({ family }: { family: keyof typeof backendChoices }) {
  const locale = useLocale();
  const groups = useMemo(() => runGroups(family), [family, locale]);
  const form = useTypedForm(groups);
  const operation = useSubmission();
  const contract = useQuery({ queryKey: ['run-contract', family], enabled: family !== 'firstswap', queryFn: async ({ signal }) => validateRunContract(await api<Schema<'RunContractListResponse'>>('/api/v1/run-contracts', { signal }), family as 'copy' | 'sniping') });
  // One coherent host profile supplies physical defaults; user edits always win.
  const settings = useQuery({ queryKey: ['run-physical-settings'], queryFn: ({ signal }) => api<Schema<'RunPhysicalSettingsCommand'>>('/api/v1/run-physical-settings', { signal }) });
  const seeded = useRef(false);
  useEffect(() => { if (!settings.data || seeded.current) return; seeded.current = true; for (const name of physicalFields) { if (form.getFieldState(name).isDirty) continue; const key = name === 'run_backend' ? 'backend' : name === 'run_threads' ? 'threads' : name; const value = settings.data[key as keyof typeof settings.data]; if (name !== 'run_backend' || backendChoices[family].includes(String(value))) form.setValue(name, String(value)); } }, [settings.data, family, form]);
  const mode = form.watch('execution_mode');
  async function submit(values: Values, sweep = false) {
    if ((family !== 'firstswap' && !contract.data) || !settings.data) return;
    // Resolve output is forwarded losslessly and never reconstructed by the browser.
    await operation.submit(encode({ family, values, sweep }), async attempt => {
      if (sweep) {
        const seeds = tokens(values, 'sweep_seeds').map(root_seed => integer({ root_seed }, 'root_seed'));
        if (!seeds.length || seeds.length > 100) throw new Error(t("Enter between 1 and 100 seeds for a series."));
        attempt.resolveBody ??= { entries: seeds.map(seed => ({ draft: firstSwapDraft(values, seed), attempt_nonce: digest(), physical_settings: physical(values) })), comparison_metrics: ['canonical_result_hash'] };
        // Resolution retries retain all member nonces before the durable sweep request exists.
        const resolved = await api<Schema<'ResolvedSweepSpecResponse'>>('/api/v1/sweep-specs/resolve', { method: 'POST', body: attempt.resolveBody });
        return { path: '/api/v1/jobs', body: { job_type: 'RUN_SWEEP', payload: { schema: 'backtest.sweep-job/v2', resolved_sweep_spec: resolved.resolved_sweep_spec } } };
      }
      const draft = family === 'firstswap' ? firstSwapDraft(values) : pumpDraft(values, family);
      const resolved = await api<Schema<'ResolvedRunSpecResponse'>>('/api/v1/run-specs/resolve', { method: 'POST', body: draft });
      // The server owns defaults, canonical digests, identity and all preflight admission checks.
      return { path: '/api/v1/backtests', body: { attempt_nonce: attempt.nonce, physical_settings: physical(values), resolved_run_spec: resolved.resolved_spec } };
    });
  }
  // No submit control becomes active until all required server-owned defaults are available.
  const ready = settings.isSuccess && (family === 'firstswap' || contract.isSuccess);
  return <><Card><p className="strategy-note">{family === 'sniping' ? t("600-second cooldown. Buy after 500 transactions. Sell decision 2 seconds after the fill.") : family === 'copy' ? t("One entry per token per run, including rejected buys. Fee-free price TP/SL; up to 4 sell attempts with a new decision after 2 seconds.") : t("Deterministic FirstSwap. Available backends pass exact equivalence checks.")}</p><Badge tone={ready ? 'positive' : ''}>{ready ? t("Contract ready") : t("Checking contract…")}</Badge></Card>
    {contract.isError && <Failure message={errorText(contract.error)} retry={() => void contract.refetch()} />}{settings.isError && <Failure message={errorText(settings.error)} retry={() => void settings.refetch()} />}
    <form noValidate onSubmit={form.handleSubmit(values => submit(values))}><fieldset disabled={operation.busy}><FormFields groups={groups} form={form} />
      {mode === 'EXOGENOUS_VIRTUAL_SETTLEMENT' && <div className="synthetic-warning" role="note">{t("Synthetic mode: missing SOL at sale is added virtually. The result is not executable on-chain.")}</div>}
      <div className="form-footer"><p>{t("Validate inputs → resolve specification → queue")}</p><div className="actions">{family === 'firstswap' && <Button type="button" disabled={!ready || operation.busy} onClick={() => void form.handleSubmit(values => submit(values, true))()}>{t("Launch seed series")}</Button>}<Button tone="primary" type="submit" disabled={!ready || operation.busy}><Play size={16} />{operation.busy ? t("Validating and submitting…") : t("Run strategy")}</Button></div></div></fieldset></form><SubmissionResult operation={operation} /></>;
}

// Each existing ML use case has its own typed form and the shared reference capability gate.
const mlTitles: Record<MlKind, string> = { features: "Features", universe: 'Universe', labels: "Labels", train: "Training", schedule: "Model schedule", predict: "Predictions" };
export function MachineLearning() {
  useLocale();
  const [kind, setKind] = useState<MlKind>('features');
  const contract = useQuery({ queryKey: ['ml-contract'], queryFn: ({ signal }) => api<Schema<'ReferenceMlContractResponse'>>('/api/v1/ml/reference-contract', { signal }) });
  return <><PageTitle eyebrow="Point-in-time pipeline" title={t("Models and features")} /><div className="tabs" role="group" aria-label={t("ML stage")}>{(Object.keys(mlTitles) as MlKind[]).map(key => <Button key={key} tone={kind === key ? 'primary' : 'ghost'} onClick={() => setKind(key)}>{t(mlTitles[key])}</Button>)}</div>
    {contract.isError && <Failure message={errorText(contract.error)} retry={() => void contract.refetch()} />}{contract.isPending && <Loading />}{contract.data && <MlForm key={kind} kind={kind} contract={contract.data} />}</>;
}
function MlForm({ kind, contract }: { kind: MlKind; contract: Schema<'ReferenceMlContractResponse'> }) {
  const locale = useLocale();
  const groups = useMemo(() => [{ id: kind, title: mlTitles[kind], description: `CANONICAL_EXACT · ${contract.compiler_version}`, open: true, fields: fields(`ml-${kind}-form`).map(field => field.name === 'feature_name' ? select(field, contract.supported_feature_names) : field) }], [kind, contract, locale]);
  const form = useTypedForm(groups);
  const operation = useSubmission();
  // All six forms dispatch the same existing typed ML application commands.
  return <><form noValidate onSubmit={form.handleSubmit(values => operation.submit(encode({ kind, values, contract }), async () => ({ path: `/api/v1/ml/${mlPaths[kind]}`, body: mlCommand(kind, values, contract as unknown as Record<string, Json>) })))}><fieldset disabled={operation.busy}><FormFields groups={groups} form={form} /><div className="form-footer"><p>{t("Heavy work runs through the job queue.")}</p><Button tone="primary" type="submit" disabled={operation.busy}><Play size={16} />{operation.busy ? t("Submitting…") : t("Launch: {0}", [t(mlTitles[kind])])}</Button></div></fieldset></form><SubmissionResult operation={operation} /></>;
}

export function DatasetPreparation() {
  const locale = useLocale();
  const inspectGroups = useMemo(() => [{ id: 'inspect', title: t("Source inspection"), description: t("Bounded read-only capability inspection"), open: true, fields: fields('inspect-form') }], [locale]);
  const planGroups = useMemo(() => { const all = fields('dataset-plan-form'); return [
    { id: 'identity', title: t("Source and capabilities"), description: t("Verified identity, capability and explicit columns"), open: true, fields: all.slice(0, 6) },
    // Typed half-open block range remains independent from operational acquisition budgets.
    { id: 'range', title: t("Data range"), description: t("Decisions, warmup and right settlement tail"), open: true, fields: all.slice(6, 11) },
    { id: 'budget', title: t("Preparation limits"), description: t("Source, local disk and memory budgets"), open: false, fields: all.slice(11) },
   ]; }, [locale]);
  const inspectionForm = useTypedForm(inspectGroups);
  const planForm = useTypedForm(planGroups);
  const [inspection, setInspection] = useState<Schema<'SourceInspectionResponse'> | null>(null);
  // A resolved plan is usable only with the exact form values that produced it.
  const [plan, setPlan] = useState<{ values: string; result: Schema<'DatasetPlanResponse'> } | null>(null);
  const [busy, setBusy] = useState<'inspect' | 'plan' | null>(null);
  const [failure, setFailure] = useState('');
  const running = useRef(false);
  const operation = useSubmission();
  // Watching values invalidates readiness synchronously on edits, without mutating the old plan.
  const current = encode(planForm.watch());
  const accepted = !!plan && current === plan.values && plan.result.budget.status !== 'REJECTED';
  async function inspect(values: Values) {
    if (running.current) return;
    running.current = true; setBusy('inspect'); setFailure(''); setInspection(null); setPlan(null);
    try {
      // The logical source ID is encoded into one route segment; no credential input exists.
      const result = await api<Schema<'SourceInspectionResponse'>>(`/api/v1/sources/${encodeURIComponent(values.source_id.trim())}/inspect`, { method: 'POST' });
      setInspection(result);
      const capability = result.capabilities[0];
      planForm.reset({ ...planForm.getValues(), source_id: result.source_id, source_inspection_artifact_id: result.artifact_id, network_id: result.network_id, position_schema_id: result.position_schema_id, capability_id: capability?.capability_id ?? '', columns: capability?.mandatory_columns.join(',') ?? '' });
    } catch (error) { setFailure(errorText(error)); } finally { running.current = false; setBusy(null); }
  }
  async function resolvePlan(values: Values) {
    // Invalidate previous admission before building or sending a replacement plan.
    if (running.current) return;
    running.current = true; setBusy('plan'); setFailure(''); setPlan(null);
    try { const result = await api<Schema<'DatasetPlanResponse'>>('/api/v1/datasets/plan', { method: 'POST', body: datasetPlan(values) }); setPlan({ values: encode(values), result }); }
    catch (error) { setFailure(errorText(error)); } finally { running.current = false; setBusy(null); }
  }
  return <><PageTitle eyebrow={t("Verified local data")} title={t("Prepare data")} />{failure && <Failure message={failure} />}
    <form noValidate onSubmit={inspectionForm.handleSubmit(inspect)}><fieldset disabled={!!busy || operation.busy}><FormFields groups={inspectGroups} form={inspectionForm} /><div className="form-footer"><p>{t("Inspection checks the source within permitted bounds.")}</p><Button type="submit">{busy === 'inspect' ? t("Checking…") : t("Inspect source")}</Button></div></fieldset></form>
    {inspection && <Card><details><summary>{t("Inspection result ·")} {inspection.capabilities.length} capabilities</summary><FactTree value={inspection} /></details><div className="actions">{inspection.capabilities.map(capability => <Button key={capability.capability_id} onClick={() => { planForm.setValue('capability_id', capability.capability_id); planForm.setValue('columns', capability.mandatory_columns.join(',')); }}>{capability.capability_id}</Button>)}</div></Card>}
    <form noValidate onSubmit={planForm.handleSubmit(resolvePlan)}><fieldset disabled={!!busy || operation.busy}><FormFields groups={planGroups} form={planForm} /><div className="form-footer"><p>{t("The plan pins the exact range and limits.")}</p><Button type="submit">{busy === 'plan' ? t("Planning…") : t("Build plan")}</Button></div></fieldset></form>
    {plan && <Card><div className="card-heading"><h3>{t("Preparation plan")}</h3><Badge tone={accepted ? 'positive' : ''}>{current !== plan.values ? t("Parameters changed — refresh the plan") : plan.result.budget.status}</Badge></div><FactTree value={plan.result} /><Button tone="primary" disabled={!accepted || operation.busy || !!busy} onClick={() => void operation.submit(encode(plan.result.resolved_plan), async () => ({ path: '/api/v1/jobs', body: { job_type: 'PREPARE_DATASET', payload: { schema: 'backtest.prepare-dataset-job/v1', plan: plan.result.resolved_plan } } }))}>{t("Prepare dataset")}</Button></Card>}
    <SubmissionResult operation={operation} /></>;
}
