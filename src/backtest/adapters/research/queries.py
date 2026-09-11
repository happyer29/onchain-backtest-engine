"""Reviewed local DuckDB recipe: first observed purchases and evidence-backed pairs."""

# Rank only first buys; compact keys follow exact lexical address order and fit the row cap.
FIRST_BUYS = """CREATE TEMP TABLE first_buys AS
SELECT row_id,signing_wallet,mint,block_time_s,block_ordinal,transaction_index,
       (dense_rank() OVER (ORDER BY signing_wallet)-1)::UINTEGER signer_key,
       (dense_rank() OVER (ORDER BY mint)-1)::UINTEGER mint_key
-- Keep source ordering and the canonical row tie-breaker unchanged before dictionary ranking.
FROM (
  SELECT row_id,signing_wallet,mint,block_time_s,block_ordinal,transaction_index,
  row_number() OVER (
    PARTITION BY signing_wallet, mint
    -- An instruction position selects the observation; pair direction uses transaction groups.
    ORDER BY block_ordinal, transaction_index, source_instruction_index, row_id
  ) AS purchase_rank FROM selected WHERE side='BUY'
) WHERE purchase_rank=1"""

# Validate candidate cardinality before the self-join can multiply participants.
CANDIDATE_BUDGET = """SELECT coalesce(max(n),0), coalesce(sum((n*(n-1))//2),0)
FROM (SELECT count(*)::HUGEINT n FROM first_buys GROUP BY mint)"""

# The quadratic relation retains integers only; full addresses stay in the first-buy dictionary.
CANDIDATES = """CREATE TEMP TABLE matches AS
SELECT a.signer_key signer_a, b.signer_key signer_b, a.mint_key mint,
       a.row_id left_observation, b.row_id right_observation,
       b.block_time_s::BIGINT-a.block_time_s::BIGINT delta_seconds,
       -- Position comparisons deliberately treat a shared transaction as a tie.
       CASE WHEN (a.block_ordinal,a.transaction_index)<(b.block_ordinal,b.transaction_index)
         THEN 1 WHEN (a.block_ordinal,a.transaction_index)>(b.block_ordinal,b.transaction_index)
         THEN -1 ELSE 0 END direction
-- Dense ranks preserve the prior lexical orientation without repeating strings for every pair.
FROM first_buys a JOIN first_buys b ON a.mint_key=b.mint_key AND a.signer_key<b.signer_key
WHERE abs(b.block_time_s::BIGINT-a.block_time_s::BIGINT)<=?"""

# A qualifying mint contributes once, regardless of duplicate rows or repeated buys.
PAIRS = """CREATE TEMP TABLE pairs AS
SELECT row_number() OVER (ORDER BY signer_a,signer_b)-1 row_id, *,
       coalesce(sum(shared_mints) OVER (ORDER BY signer_a,signer_b
         ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),0) evidence_start,
       shared_mints evidence_count
FROM (SELECT signer_a,signer_b,count(*) shared_mints,
      count(*) FILTER (WHERE direction=1) a_first,
      count(*) FILTER (WHERE direction=-1) b_first,
      count(*) FILTER (WHERE direction=0) same_transaction
      FROM matches GROUP BY signer_a,signer_b HAVING count(*)>=?)"""

# Decode addresses only in the complete published pair stream, after bounded aggregation.
PAIR_ROWS = """SELECT p.row_id,a.signing_wallet signer_a,b.signing_wallet signer_b,
 p.shared_mints,p.a_first,p.b_first,p.same_transaction,p.evidence_start,p.evidence_count
 FROM pairs p
 JOIN (SELECT DISTINCT signer_key,signing_wallet FROM first_buys) a ON p.signer_a=a.signer_key
 -- One dictionary entry per signer prevents decoding from multiplying result rows.
 JOIN (SELECT DISTINCT signer_key,signing_wallet FROM first_buys) b ON p.signer_b=b.signer_key
 ORDER BY p.row_id"""

# The complete filtered pair set selects evidence; pagination never affects totals.
EVIDENCE = """SELECT row_number() OVER (ORDER BY p.row_id,m.mint)-1 row_id,
 p.row_id pair_row_id, d.mint,m.left_observation,m.right_observation,m.delta_seconds
 FROM matches m JOIN pairs p USING(signer_a,signer_b)
 -- Mint keys follow lexical mint order; exact observation ordinals remain unchanged.
 JOIN (SELECT DISTINCT mint_key,mint FROM first_buys) d ON m.mint=d.mint_key
 ORDER BY p.row_id,m.mint"""

# Activity is a source-row count; amount legs do not claim wallet cash PnL.
ACTIVITY = """SELECT row_number() OVER (ORDER BY signing_wallet)-1 row_id,signing_wallet,
 count(*) FILTER (WHERE side='BUY') buy_rows, count(*) FILTER (WHERE side='SELL') sell_rows,
 count(DISTINCT mint) mint_count,min(block_ordinal) first_block,max(block_ordinal) last_block,
 sum(CASE WHEN side='BUY' THEN quote_amount_atomic::HUGEINT ELSE 0 END) source_quote_buy_atomic,
 sum(CASE WHEN side='SELL' THEN quote_amount_atomic::HUGEINT ELSE 0 END) source_quote_sell_atomic
 FROM selected GROUP BY signing_wallet ORDER BY signing_wallet"""
