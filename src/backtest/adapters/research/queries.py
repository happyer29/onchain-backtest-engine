"""Reviewed local DuckDB recipe: first observed purchases and evidence-backed pairs."""

# Every relation comes from an exact local snapshot or bounded typed parameters.
FIRST_BUYS = """CREATE TEMP TABLE first_buys AS
SELECT * EXCLUDE (purchase_rank) FROM (
  SELECT *, row_number() OVER (
    PARTITION BY signing_wallet, mint
    ORDER BY block_ordinal, transaction_index, source_instruction_index, row_id
  ) AS purchase_rank FROM selected WHERE side='BUY'
) WHERE purchase_rank=1"""

# Validate candidate cardinality before the self-join can multiply participants.
CANDIDATE_BUDGET = """SELECT coalesce(max(n),0), coalesce(sum((n*(n-1))//2),0)
FROM (SELECT count(*)::HUGEINT n FROM first_buys GROUP BY mint)"""

# Position comparisons deliberately treat a shared transaction as a tie.
CANDIDATES = """CREATE TEMP TABLE matches AS
SELECT a.signing_wallet signer_a, b.signing_wallet signer_b, a.mint,
       a.row_id left_observation, b.row_id right_observation,
       b.block_time_s::BIGINT-a.block_time_s::BIGINT delta_seconds,
       CASE WHEN (a.block_ordinal,a.transaction_index)<(b.block_ordinal,b.transaction_index)
         THEN 1 WHEN (a.block_ordinal,a.transaction_index)>(b.block_ordinal,b.transaction_index)
         THEN -1 ELSE 0 END direction
FROM first_buys a JOIN first_buys b ON a.mint=b.mint AND a.signing_wallet<b.signing_wallet
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

# The complete filtered pair set selects evidence; pagination never affects totals.
EVIDENCE = """SELECT row_number() OVER (ORDER BY p.row_id,m.mint)-1 row_id,
 p.row_id pair_row_id, m.mint,m.left_observation,m.right_observation,m.delta_seconds
 FROM matches m JOIN pairs p USING(signer_a,signer_b) ORDER BY p.row_id,m.mint"""

# Activity is a source-row count; amount legs do not claim wallet cash PnL.
ACTIVITY = """SELECT row_number() OVER (ORDER BY signing_wallet)-1 row_id,signing_wallet,
 count(*) FILTER (WHERE side='BUY') buy_rows, count(*) FILTER (WHERE side='SELL') sell_rows,
 count(DISTINCT mint) mint_count,min(block_ordinal) first_block,max(block_ordinal) last_block,
 sum(CASE WHEN side='BUY' THEN quote_amount_atomic::HUGEINT ELSE 0 END) source_quote_buy_atomic,
 sum(CASE WHEN side='SELL' THEN quote_amount_atomic::HUGEINT ELSE 0 END) source_quote_sell_atomic
 FROM selected GROUP BY signing_wallet ORDER BY signing_wallet"""
