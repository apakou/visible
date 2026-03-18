CREATE TABLE IF NOT EXISTS owners (
    id SERIAL PRIMARY KEY,
    phone_number TEXT UNIQUE NOT NULL,
    name TEXT,
    shop_name TEXT,
    location TEXT,
    language_pref TEXT DEFAULT 'en',
    onboarded_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS inventory_log (
    id SERIAL PRIMARY KEY,
    owner_id INTEGER NOT NULL REFERENCES owners(id),
    entry_type TEXT NOT NULL,
    product_name TEXT,
    product_category TEXT,
    quantity INTEGER,
    unit_cost_pesewas INTEGER,
    unit_price_pesewas INTEGER,
    stock_value_pesewas INTEGER,
    raw_message TEXT,
    parse_confidence REAL,
    logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS inventory_declarations (
    id SERIAL PRIMARY KEY,
    owner_id INTEGER NOT NULL REFERENCES owners(id),
    declaration_month DATE NOT NULL,
    total_stock_value_ghs NUMERIC(12,2),
    item_breakdown_json TEXT,
    days_logged INTEGER,
    consistency_score REAL,
    declaration_text_en TEXT,
    declaration_text_tw TEXT,
    submitted_to_insurer BOOLEAN DEFAULT FALSE,
    submitted_at TIMESTAMP,
    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS susu_groups (
    id SERIAL PRIMARY KEY,
    group_name TEXT NOT NULL,
    leader_phone TEXT NOT NULL REFERENCES owners(phone_number),
    market_location TEXT,
    member_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS susu_members (
    id SERIAL PRIMARY KEY,
    group_id INTEGER NOT NULL REFERENCES susu_groups(id),
    owner_id INTEGER NOT NULL REFERENCES owners(id),
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS policies (
    id SERIAL PRIMARY KEY,
    owner_id INTEGER NOT NULL REFERENCES owners(id),
    susu_group_id INTEGER REFERENCES susu_groups(id),
    policy_number TEXT UNIQUE NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    premium_pesewas INTEGER NOT NULL,
    payout_cap_pesewas INTEGER NOT NULL,
    cover_start_date DATE,
    cover_end_date DATE,
    insurer_partner TEXT,
    last_premium_paid_at TIMESTAMP,
    declarations_submitted INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS claims (
    id SERIAL PRIMARY KEY,
    policy_id INTEGER NOT NULL REFERENCES policies(id),
    owner_id INTEGER NOT NULL REFERENCES owners(id),
    claim_reference TEXT UNIQUE NOT NULL,
    event_type TEXT NOT NULL,
    event_date DATE NOT NULL,
    declared_loss_pesewas INTEGER,
    verified_loss_pesewas INTEGER,
    payout_pesewas INTEGER,
    status TEXT DEFAULT 'initiated',
    supporting_declaration_id INTEGER REFERENCES inventory_declarations(id),
    initiated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS financial_profiles (
    id SERIAL PRIMARY KEY,
    owner_id INTEGER NOT NULL REFERENCES owners(id) UNIQUE,
    credit_score INTEGER,
    logging_days INTEGER DEFAULT 0,
    avg_daily_revenue_pesewas INTEGER,
    last_calculated_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
