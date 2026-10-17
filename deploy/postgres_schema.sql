-- FRESCO ledger schema for PostgreSQL (design specification, Stage 3 section 5).
-- STATUS: specification only. It mirrors fresco/ledger.py transition-for-transition
-- but has NOT been executed against a PostgreSQL server in this repository yet.
-- Each transition runs as one SERIALIZABLE transaction; uniqueness and CHECK
-- constraints are a second line of defence for invariants I1-I4.

CREATE TABLE run (
    run_id          text PRIMARY KEY,
    config_hash     text NOT NULL,
    eps             double precision NOT NULL CHECK (eps > 0 AND eps < 1),
    eps_audit       double precision NOT NULL,
    alpha           double precision NOT NULL CHECK (alpha > 0 AND alpha < 1),
    levels          int NOT NULL,
    cap             int NOT NULL,
    mode            text NOT NULL CHECK (mode IN ('async', 'replay')),
    unleased        double precision NOT NULL CHECK (unleased >= -1e-12),   -- I1 pool
    b_hat           int,                                                    -- NULL = censored so far
    witness_j       bigint,
    slots_leased    bigint NOT NULL DEFAULT 0,
    max_slots       bigint NOT NULL
    -- the run key (PRF secret) is NOT stored here; it lives in the coordinator's secret store
);

CREATE TABLE budget_lease (
    run_id     text REFERENCES run,
    lease_id   bigint,
    worker_inc text NOT NULL,                     -- incarnation binding (R5)
    amount     double precision NOT NULL CHECK (amount > 0),
    spent      double precision NOT NULL DEFAULT 0,
    n_reg      int NOT NULL DEFAULT 0,
    open       boolean NOT NULL DEFAULT true,
    expires_at double precision NOT NULL,
    PRIMARY KEY (run_id, lease_id),
    CHECK (spent <= amount + 1e-12)                 -- I2
);

CREATE TABLE candidate (
    run_id       text REFERENCES run,
    j            bigint,
    level        int NOT NULL,
    content_hash text NOT NULL,
    a_j          double precision NOT NULL CHECK (a_j > 0),
    lease_id     bigint NOT NULL,
    owner_inc    text NOT NULL,
    status       text NOT NULL CHECK (status IN ('ACTIVE', 'CONFIRMED', 'ABANDONED', 'PRUNED')),
    n_committed  int NOT NULL DEFAULT 0,          -- I4 commit pointer
    s_committed  int NOT NULL DEFAULT 0,
    log_e        double precision NOT NULL DEFAULT 0,
    max_log_e    double precision NOT NULL DEFAULT 0,
    next_new_k   int NOT NULL DEFAULT 1,
    PRIMARY KEY (run_id, j),
    UNIQUE (run_id, level, content_hash),          -- content dedup
    FOREIGN KEY (run_id, lease_id) REFERENCES budget_lease
);

CREATE TABLE slot (
    run_id     text,
    j          bigint,
    k          int,
    state      text NOT NULL CHECK (state IN ('FREE', 'LEASED', 'DONE', 'CRASHED')),
    attempt    int NOT NULL DEFAULT 0,
    token      text,                               -- fencing token "j:k:attempt"
    worker_inc text,
    leased_at  double precision,
    y          smallint CHECK (y IN (0, 1)),
    trace_hash text,                               -- full trace in content-addressed object store
    PRIMARY KEY (run_id, j, k),                    -- I3: one row per (j, k)
    FOREIGN KEY (run_id, j) REFERENCES candidate,
    CHECK ((state = 'DONE') = (y IS NOT NULL))
);
CREATE INDEX slot_leased ON slot (run_id, leased_at) WHERE state = 'LEASED';

CREATE TABLE audit_draw (
    run_id   text REFERENCES run,
    level    int,
    i        int,
    state    text NOT NULL CHECK (state IN ('LEASED', 'DONE', 'CRASHED')),
    token    text NOT NULL,
    leased_at double precision NOT NULL,
    z        smallint CHECK (z IN (0, 1)),
    PRIMARY KEY (run_id, level, i)
);

CREATE TABLE audit_level (
    run_id    text REFERENCES run,
    level     int,
    next_i    int NOT NULL DEFAULT 1,
    committed int NOT NULL DEFAULT 0,              -- in-order audit prefix
    hits      int NOT NULL DEFAULT 0,
    cs_state  bytea,                               -- serialized BernoulliUpperCS
    PRIMARY KEY (run_id, level)
);

-- Request-level idempotency: one cached response per (sender, req_id).
CREATE TABLE request_cache (
    run_id     text REFERENCES run,
    sender     text,
    req_id     bigint,
    response   jsonb NOT NULL,
    PRIMARY KEY (run_id, sender, req_id)
);

-- Write-ahead journal for audit and deterministic replay (Ledger.recover).
CREATE TABLE journal (
    run_id  text REFERENCES run,
    seq     bigserial,
    op      text NOT NULL,
    sender  text,
    req_id  bigint,
    args    jsonb NOT NULL,
    PRIMARY KEY (run_id, seq)
);

-- Frontier / status events for LISTEN/NOTIFY fan-out (efficiency only; Prop. 10).
CREATE TABLE event (
    run_id text REFERENCES run,
    seq    bigserial,
    kind   text NOT NULL CHECK (kind IN ('frontier', 'status')),
    body   jsonb NOT NULL,
    PRIMARY KEY (run_id, seq)
);
