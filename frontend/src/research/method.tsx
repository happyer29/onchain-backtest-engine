import { t, useLocale } from '../i18n';
import { Card } from '../ui';

// A worked example describes the fixed recipe; it is not a synthetic analytical result.
export function ResearchMethod() {
  useLocale();
  return <Card><details className="research-method"><summary>{t('What is analysed and how to interpret it')}</summary>
    <h3>{t('One first purchase for each wallet + token')}</h3><p>{t('For wallet A, the first BUY of token X and the first BUY of token Y are two separate observations. We choose the earliest observed BUY by chain position inside the snapshot. Earlier history is not checked; this is not necessarily the first purchase in the wallet’s lifetime.')}</p>
    <ol><li>{t('Select signers and token modes; skip tokens with reported data issues. Empty signers means everyone in the snapshot. Without Mayhem excludes Mayhem and unknown modes before counting.')}</li><li>{t('For each token, compare the block times of the two wallets’ first purchases. Their absolute difference must be no greater than the window; exactly 60 seconds qualifies for a 60-second window.')}</li><li>{t('Each qualifying token adds exactly one to the pair’s shared-token count. Repeated purchases of that token do not increase it.')}</li><li>{t('Keep pairs that meet the minimum. With minimum 2, the wallets must match on at least two different tokens.')}</li></ol>
    <p className="notice">{t('Later purchases together can be missed: when A first bought long ago, a later purchase by A is not compared with B’s first purchase.')}</p>
    <table><caption>{t('Example: one token X, window 60 seconds; every event is inside the snapshot')}</caption><thead><tr>{['Time','Wallet','Purchase','Compared'].map(label => <th key={label}>{t(label)}</th>)}</tr></thead><tbody><tr><td>10:00:00</td><td>A</td><td>{t('First')}</td><td>{t('Yes')}</td></tr><tr><td>10:20:00</td><td>A</td><td>{t('Repeated')}</td><td>{t('No')}</td></tr><tr><td>10:20:30</td><td>B</td><td>{t('First')}</td><td>{t('Yes')}</td></tr></tbody></table>
    <p>{t('The comparison uses 10:00:00 and 10:20:30: a 1,230-second gap. X adds no match, although the later buys were 30 seconds apart. If B first bought at 10:00:30, X would add one; minimum 2 would still require another token.')}</p>
    <h3>{t('Reading the result')}</h3><p>{t('One row and one graph edge represent a pair of signers. Shared tokens counts distinct qualifying tokens, not purchases, profits or probability. A and B are ordered by address; A earlier / B earlier describe observed ordering, not a leader score. Same transaction is a separate count. The evidence table shows both signatures, signers, fee payers, blocks and the time difference B − A.')}</p>
    <p>{t('The block range defines the full research period; the window defines the allowed time gap for one token. Matches on different tokens can happen hours apart. Changing the start block can change which purchases are first.')}</p>
    <p>{t('Counts do not adjust for token popularity and do not test statistical significance. A link does not prove a common owner, coordination, copy trading or a profitable strategy. Market completeness, finality and historical availability remain UNKNOWN.')}</p>
  </details></Card>;
}
