import { Link } from 'react-router-dom';
import { useLocale } from '../i18n';
import { Button, Card } from '../ui';
import { parseSummary } from '../result-contracts';
import type { DemoCatalog } from './client';

// Demo-only copy keeps the operational UI and its command routes unchanged.
const copy = {
  en: {
    title: 'Start here: one Copy Buy example',
    introduction: 'Follow a wallet purchase from signal to simulated execution, then inspect why each attempt succeeded or failed.',
    boundary: 'The wallet and rules are already fixed in this prepared example. This site opens saved results; selecting your own wallet, changing rules and calculating a new backtest require the local application.',
    historicalBoundary: 'This tour opens a completed historical backtest. You can explore the configuration controls, but editing preview fields does not change a published result or start a new calculation.',
    historicalSignal: 'The prepared Copy Buy run follows purchases by its selected wallets. Open Trades to identify the signal wallet for each entry.',
    historicalRules: 'Open Launch strategy → Pump.fun Copy Buy to explore wallet selection and strategy rules. These are form previews, not the saved configuration of the linked result; execution is disabled.',
    historicalResult: 'Open the prepared strict replay below. It simulates execution against historical observations and reserves; it does not send transactions to the market.',
    separateBoundary: 'The historical site currently shows other strategy results. Follow the separate synthetic Copy Buy walkthrough to inspect this scenario; its generated data is distinct from the historical dataset.',
    separateSignal: 'The separate Copy Buy walkthrough uses a selected synthetic wallet and its generated purchase signal.',
    separateResult: 'Open the synthetic walkthrough below, then its strict replay result. It contains a filled buy and exhausted sell attempts, calculated offline by the Python engine.',
    separateLink: 'Open Copy Buy walkthrough (synthetic)',
    preview: 'Explore the strategy controls',
    steps: [
      ['Select a wallet / signal', 'The fixture contains a selected synthetic wallet. Its observed purchase supplies the Copy Buy signal.'],
      ['Configure Copy Buy', 'Entry size, slippage, holding period and retry limits were set before this result was calculated. They are not editable on this site.'],
      ['Open the backtest', 'Start with strict replay below: a buy fills, but sell attempts exhaust their limits under the observed reserves. This is an expected test outcome.'],
      ['Inspect the trade', 'Choose Trades, then the token or its Details button. Follow Signal → decision → fill, inspect quotes and failure reasons. Verification opens the result’s identity and offline lineage.'],
    ],
    result: 'Open strict replay result',
    unavailable: 'The strict replay example is unavailable in this build.',
    next: 'Next: Trades → token or Details',
    strictHint: 'The filled buy and failed sell attempts are intentional. Inspect the attempts and their reasons before interpreting any total.',
    historicalHint: 'Inspect the signal, attempts and failure reasons before interpreting the totals. Historical market observations and modeled strategy trades remain distinct.',
    virtualHint: 'This comparison uses virtual SOL funding for sales. A completed trade in this mode does not establish that the sale could execute on-chain.',
    back: 'Back to the four-step guide',
    researchTitle: 'Also explore: wallet research',
    researchBoundary: 'The 60-wallet graph is a separate generated dataset. It did not select the wallet or produce the signal in the Copy Buy example.',
    comparison: 'Compare the two prepared outcomes',
  },
  ru: {
    title: 'Начните здесь: один пример Copy Buy',
    introduction: 'Проследите покупку кошелька от сигнала до симуляции исполнения и разберите, почему каждая попытка завершилась успешно или ошибкой.',
    boundary: 'Кошелёк и правила в этом примере уже заданы. Сайт открывает сохранённые результаты; выбор своего кошелька, изменение правил и расчёт нового бэктеста доступны в локальном приложении.',
    historicalBoundary: 'Этот маршрут открывает завершённый исторический бэктест. Настройки можно изучить в форме предпросмотра, но её изменения не меняют опубликованный результат и не запускают новый расчёт.',
    historicalSignal: 'Готовый запуск Copy Buy следует покупкам выбранных для него кошельков. Откройте «Сделки», чтобы увидеть кошелёк сигнала для каждого входа.',
    historicalRules: 'Откройте «Запуск стратегии» → Pump.fun Copy Buy и изучите выбор кошелька и правила стратегии. Это предпросмотр формы, а не сохранённые настройки результата по ссылке; исполнение отключено.',
    historicalResult: 'Откройте готовый строгий replay ниже. Он моделирует исполнение по историческим наблюдениям и резервам, не отправляя транзакции на рынок.',
    separateBoundary: 'Исторический сайт сейчас показывает результаты других стратегий. Для этого сценария откройте отдельный синтетический пример Copy Buy: его сгенерированные данные независимы от исторического датасета.',
    separateSignal: 'Отдельный пример Copy Buy использует выбранный синтетический кошелёк и его сгенерированную покупку как сигнал.',
    separateResult: 'Откройте синтетический пример ниже, затем его строгий replay. Покупка исполняется, попытки продажи исчерпываются; всё рассчитано заранее Python-движком.',
    separateLink: 'Открыть пример Copy Buy (синтетический)',
    preview: 'Изучить настройки стратегии',
    steps: [
      ['Выбрать кошелёк / сигнал', 'В тестовых данных уже выбран синтетический кошелёк. Его наблюдаемая покупка служит сигналом для Copy Buy.'],
      ['Настроить Copy Buy', 'Размер входа, проскальзывание, срок удержания и лимиты повторных попыток заданы до расчёта результата. На этом сайте они не редактируются.'],
      ['Открыть бэктест', 'Начните со строгого replay ниже: покупка исполняется, но попытки продажи исчерпываются при наблюдаемых резервах. Это ожидаемый исход теста.'],
      ['Разобрать сделку', 'Откройте «Сделки», затем токен или кнопку его подробностей. Проследите «Сигнал → решение → исполнение», проверьте котировки и причины ошибок. Вкладка «Проверка» показывает идентификаторы результата и происхождение данных.'],
    ],
    result: 'Открыть результат строгого replay',
    unavailable: 'Пример строгого replay недоступен в этой сборке.',
    next: 'Далее: «Сделки» → токен или подробности',
    strictHint: 'Исполненная покупка и неудавшиеся продажи предусмотрены примером. Перед оценкой итоговых показателей разберите попытки и причины ошибок.',
    historicalHint: 'Перед оценкой итоговых показателей разберите сигнал, попытки и причины ошибок. Исторические рыночные наблюдения и смоделированные сделки стратегии — разные данные.',
    virtualHint: 'В этом сравнении продажи используют виртуальное финансирование в SOL. Закрытие сделки в этом режиме не подтверждает возможность такой продажи в блокчейне.',
    back: 'Вернуться к четырём шагам',
    researchTitle: 'Дополнительно: исследование кошельков',
    researchBoundary: 'Граф из 60 кошельков — отдельный набор сгенерированных данных. Он не выбирал кошелёк и не создавал сигнал для примера Copy Buy.',
    comparison: 'Сравните два готовых результата',
  },
};

export function useDemoCopy() {
  const locale = useLocale();
  return { text: copy[locale] };
}

export function strictCopyRun(catalog: DemoCatalog) {
  return catalog.runs.find(run => {
    if (run.mode !== 'EXOGENOUS_REPLAY') return false;
    const summary = parseSummary(run.summary, run.id);
    return summary.family === 'PUMPFUN_COPY_BUY' && summary.execution_mode === run.mode;
  });
}

export function CopyBuyGuide({ catalog }: { catalog: DemoCatalog }) {
  const { text } = useDemoCopy();
  // Resolve identity by verified family/mode, never by title or catalog order.
  const strict = strictCopyRun(catalog);
  const separate = !catalog.synthetic && !strict;
  const steps = text.steps.map(([title, detail], index) => [title, catalog.synthetic ? detail : [separate ? text.separateSignal : text.historicalSignal, text.historicalRules, separate ? text.separateResult : text.historicalResult, detail][index]]);
  return <Card className="demo-guide">
    <h2>{text.title}</h2>
    <p className="demo-guide-intro">{text.introduction}</p>
    <p className="demo-guide-boundary">{catalog.synthetic ? text.boundary : separate ? text.separateBoundary : text.historicalBoundary}</p>
    <ol className="demo-guide-steps" aria-label={text.title}>
      {steps.map(([title, detail], index) => <li key={title}><h3>{title}</h3><p>{detail}</p>{!catalog.synthetic && index === 1 && <Link to="/launch">{text.preview}</Link>}</li>)}
    </ol>
    <div className="demo-guide-actions">
      {strict ? <Button asChild tone="primary"><Link to={`/runs/${strict.id}`}>{text.result}</Link></Button> : separate ? <Button asChild tone="primary"><a href="./copy-buy/">{text.separateLink}</a></Button> : <p role="status">{text.unavailable}</p>}
    </div>
  </Card>;
}

export function ResultGuide({ mode, synthetic }: { mode: DemoCatalog['runs'][number]['mode']; synthetic: boolean }) {
  const { text } = useDemoCopy();
  return <aside className="demo-result-guide" aria-label={text.next}>
    <strong>{text.next}</strong>
    <p>{mode === 'EXOGENOUS_REPLAY' ? synthetic ? text.strictHint : text.historicalHint : text.virtualHint}</p>
    <Link to="/">{text.back}</Link>
  </aside>;
}
