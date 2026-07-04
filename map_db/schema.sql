PRAGMA foreign_keys = ON;

-- Map editor database: ref_* (read-only catalogs) + geo_* / st_* (editable scenario).

DROP TABLE IF EXISTS import_msg;
DROP TABLE IF EXISTS st_bld_pm;
DROP TABLE IF EXISTS st_bld_own;
DROP TABLE IF EXISTS st_bld;
DROP TABLE IF EXISTS st_pop;
DROP TABLE IF EXISTS st_prov;
DROP TABLE IF EXISTS st;
DROP TABLE IF EXISTS geo_claim;
DROP TABLE IF EXISTS geo_homeland;
DROP TABLE IF EXISTS geo_state;
DROP TABLE IF EXISTS map_layer_png;
DROP TABLE IF EXISTS map_png;
DROP TABLE IF EXISTS ref_loc;
DROP TABLE IF EXISTS ref_hist_file;
DROP TABLE IF EXISTS ref_hist_src;
DROP TABLE IF EXISTS ref_strat_st;
DROP TABLE IF EXISTS ref_strat;
DROP TABLE IF EXISTS ref_sr_impassable;
DROP TABLE IF EXISTS ref_sr_prime;
DROP TABLE IF EXISTS ref_sr_prov;
DROP TABLE IF EXISTS ref_sr;
DROP TABLE IF EXISTS ref_tag_culture;
DROP TABLE IF EXISTS ref_tag;
DROP TABLE IF EXISTS ref_named_color;
DROP TABLE IF EXISTS ref_co;
DROP TABLE IF EXISTS ref_pmg_pm;
DROP TABLE IF EXISTS ref_pmg;
DROP TABLE IF EXISTS ref_bld_pmg;
DROP TABLE IF EXISTS ref_bld;
DROP TABLE IF EXISTS ref_bg;
DROP TABLE IF EXISTS ref_culture;
DROP TABLE IF EXISTS ref_religion;
DROP TABLE IF EXISTS meta;

CREATE TABLE meta (
    key TEXT NOT NULL PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE import_msg (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    severity TEXT NOT NULL CHECK (severity IN ('error', 'warning')),
    message TEXT NOT NULL
);

-- ---------- reference catalogs ----------

CREATE TABLE ref_religion (
    religion TEXT NOT NULL PRIMARY KEY,
    r INTEGER NOT NULL CHECK (r BETWEEN 0 AND 255),
    g INTEGER NOT NULL CHECK (g BETWEEN 0 AND 255),
    b INTEGER NOT NULL CHECK (b BETWEEN 0 AND 255),
    name_zh TEXT NOT NULL DEFAULT '',
    name_en TEXT NOT NULL DEFAULT ''
);

CREATE TABLE ref_culture (
    culture TEXT NOT NULL PRIMARY KEY,
    default_religion TEXT NOT NULL,
    r INTEGER NOT NULL CHECK (r BETWEEN 0 AND 255),
    g INTEGER NOT NULL CHECK (g BETWEEN 0 AND 255),
    b INTEGER NOT NULL CHECK (b BETWEEN 0 AND 255),
    FOREIGN KEY (default_religion) REFERENCES ref_religion (religion)
);

CREATE TABLE ref_bg (
    building_group TEXT NOT NULL PRIMARY KEY,
    parent_group TEXT,
    root_group TEXT NOT NULL,
    FOREIGN KEY (parent_group) REFERENCES ref_bg (building_group),
    FOREIGN KEY (root_group) REFERENCES ref_bg (building_group)
);

CREATE TABLE ref_bld (
    building TEXT NOT NULL PRIMARY KEY,
    building_group TEXT NOT NULL,
    buildable INTEGER NOT NULL DEFAULT 1 CHECK (buildable IN (0, 1)),
    FOREIGN KEY (building_group) REFERENCES ref_bg (building_group)
);

CREATE TABLE ref_bld_pmg (
    building TEXT NOT NULL,
    ord INTEGER NOT NULL,
    pm_group TEXT NOT NULL,
    PRIMARY KEY (building, ord),
    FOREIGN KEY (building) REFERENCES ref_bld (building),
    FOREIGN KEY (pm_group) REFERENCES ref_pmg (pm_group)
);

CREATE TABLE ref_pmg (
    pm_group TEXT NOT NULL PRIMARY KEY
);

CREATE TABLE ref_pmg_pm (
    pm_group TEXT NOT NULL,
    ord INTEGER NOT NULL,
    pm TEXT NOT NULL,
    PRIMARY KEY (pm_group, ord),
    FOREIGN KEY (pm_group) REFERENCES ref_pmg (pm_group)
);

CREATE TABLE ref_co (
    company_type TEXT NOT NULL PRIMARY KEY
);

CREATE TABLE ref_named_color (
    color_key TEXT NOT NULL PRIMARY KEY,
    r INTEGER NOT NULL CHECK (r BETWEEN 0 AND 255),
    g INTEGER NOT NULL CHECK (g BETWEEN 0 AND 255),
    b INTEGER NOT NULL CHECK (b BETWEEN 0 AND 255)
);

CREATE TABLE ref_tag (
    tag TEXT NOT NULL PRIMARY KEY,
    r INTEGER NOT NULL CHECK (r BETWEEN 0 AND 255),
    g INTEGER NOT NULL CHECK (g BETWEEN 0 AND 255),
    b INTEGER NOT NULL CHECK (b BETWEEN 0 AND 255),
    capital_state TEXT NOT NULL DEFAULT '',
    country_type TEXT NOT NULL DEFAULT ''
);

CREATE TABLE ref_tag_culture (
    tag TEXT NOT NULL,
    culture TEXT NOT NULL,
    ord INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (tag, culture),
    FOREIGN KEY (tag) REFERENCES ref_tag (tag),
    FOREIGN KEY (culture) REFERENCES ref_culture (culture)
);

CREATE TABLE ref_sr (
    state TEXT NOT NULL PRIMARY KEY CHECK (state GLOB 'STATE_*'),
    sr_id INTEGER NOT NULL DEFAULT 0,
    city TEXT NOT NULL DEFAULT '',
    port TEXT NOT NULL DEFAULT '',
    farm TEXT NOT NULL DEFAULT '',
    mine TEXT NOT NULL DEFAULT '',
    wood TEXT NOT NULL DEFAULT ''
);

CREATE TABLE ref_sr_prov (
    state TEXT NOT NULL,
    province TEXT NOT NULL,
    PRIMARY KEY (state, province),
    FOREIGN KEY (state) REFERENCES ref_sr (state)
);

CREATE TABLE ref_sr_prime (
    state TEXT NOT NULL,
    province TEXT NOT NULL,
    PRIMARY KEY (state, province),
    FOREIGN KEY (state) REFERENCES ref_sr (state),
    FOREIGN KEY (state, province) REFERENCES ref_sr_prov (state, province)
);

CREATE TABLE ref_sr_impassable (
    state TEXT NOT NULL,
    province TEXT NOT NULL,
    PRIMARY KEY (state, province),
    FOREIGN KEY (state) REFERENCES ref_sr (state),
    FOREIGN KEY (state, province) REFERENCES ref_sr_prov (state, province)
);

CREATE TABLE ref_strat (
    region TEXT NOT NULL PRIMARY KEY CHECK (region GLOB 'region_*'),
    capital_province TEXT NOT NULL DEFAULT '',
    map_r REAL NOT NULL DEFAULT 0,
    map_g REAL NOT NULL DEFAULT 0,
    map_b REAL NOT NULL DEFAULT 0
);

CREATE TABLE ref_strat_st (
    region TEXT NOT NULL,
    state TEXT NOT NULL,
    PRIMARY KEY (region, state),
    FOREIGN KEY (region) REFERENCES ref_strat (region),
    FOREIGN KEY (state) REFERENCES ref_sr (state)
);

-- Static mapping: which history txt file each state exports to (build time only).
CREATE TABLE ref_hist_src (
    state TEXT NOT NULL PRIMARY KEY,
    bld_file TEXT NOT NULL,
    bld_ord INTEGER NOT NULL,
    pop_file TEXT NOT NULL,
    pop_ord INTEGER NOT NULL,
    st_file TEXT NOT NULL,
    st_ord INTEGER NOT NULL,
    FOREIGN KEY (state) REFERENCES ref_sr (state)
);

-- All effective history filenames per category (incl. intentional empty mod overrides).
CREATE TABLE ref_hist_file (
    category TEXT NOT NULL CHECK (category IN ('buildings', 'pops', 'states')),
    filename TEXT NOT NULL,
    is_empty INTEGER NOT NULL DEFAULT 0 CHECK (is_empty IN (0, 1)),
    PRIMARY KEY (category, filename)
);

CREATE TABLE map_png (
    id INTEGER NOT NULL PRIMARY KEY CHECK (id = 1),
    source_path TEXT NOT NULL,
    png BLOB NOT NULL
);

-- Precomputed map overlays that depend only on ref_* + provinces.png (not st_*).
CREATE TABLE map_layer_png (
    layer TEXT NOT NULL PRIMARY KEY,
    png BLOB NOT NULL
);

CREATE TABLE ref_loc (
    loc_key TEXT NOT NULL,
    locale TEXT NOT NULL CHECK (locale IN ('en', 'bp', 'fr', 'de', 'pl', 'ru', 'es', 'ja', 'zh', 'ko', 'tr')),
    text TEXT NOT NULL,
    PRIMARY KEY (loc_key, locale)
);

-- ---------- editable scenario ----------

CREATE TABLE geo_state (
    state TEXT NOT NULL PRIMARY KEY CHECK (state GLOB 'STATE_*'),
    FOREIGN KEY (state) REFERENCES ref_sr (state)
);

CREATE TABLE geo_homeland (
    state TEXT NOT NULL,
    culture TEXT NOT NULL,
    PRIMARY KEY (state, culture),
    FOREIGN KEY (state) REFERENCES geo_state (state)
);

CREATE TABLE geo_claim (
    state TEXT NOT NULL,
    claim_tag TEXT NOT NULL,
    PRIMARY KEY (state, claim_tag),
    FOREIGN KEY (state) REFERENCES geo_state (state)
);

CREATE TABLE st (
    state TEXT NOT NULL,
    tag TEXT NOT NULL,
    state_type TEXT NOT NULL DEFAULT 'incorporated',
    PRIMARY KEY (state, tag),
    FOREIGN KEY (state) REFERENCES geo_state (state),
    FOREIGN KEY (tag) REFERENCES ref_tag (tag)
);

CREATE TABLE st_prov (
    -- Each province belongs to exactly one state and one tag (province is globally unique).
    province TEXT NOT NULL PRIMARY KEY,
    state TEXT NOT NULL,
    tag TEXT NOT NULL,
    FOREIGN KEY (state, tag) REFERENCES st (state, tag),
    FOREIGN KEY (state, province) REFERENCES ref_sr_prov (state, province)
);

CREATE INDEX idx_st_prov_tag_state ON st_prov (tag, state);
CREATE INDEX idx_st_prov_state_tag ON st_prov (state, tag);

CREATE TABLE st_pop (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    state TEXT NOT NULL,
    tag TEXT NOT NULL,
    culture TEXT NOT NULL,
    religion TEXT,
    is_slaves INTEGER NOT NULL DEFAULT 0 CHECK (is_slaves IN (0, 1)),
    size INTEGER NOT NULL CHECK (size >= 1),
    FOREIGN KEY (state, tag) REFERENCES st (state, tag),
    FOREIGN KEY (culture) REFERENCES ref_culture (culture)
) STRICT;

CREATE UNIQUE INDEX uq_st_pop ON st_pop (
    state, tag, culture, IFNULL(religion, ''), is_slaves
);

CREATE TABLE st_bld (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    state TEXT NOT NULL,
    tag TEXT NOT NULL,
    building TEXT NOT NULL,
    reserves INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (state, tag) REFERENCES st (state, tag),
    FOREIGN KEY (building) REFERENCES ref_bld (building)
);

CREATE TABLE st_bld_own (
    bld_id INTEGER NOT NULL,
    ord INTEGER NOT NULL,
    ownership TEXT NOT NULL,
    level INTEGER NOT NULL CHECK (level >= 1),
    owner_tag TEXT NOT NULL DEFAULT '',
    owner_state TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (bld_id, ord),
    FOREIGN KEY (bld_id) REFERENCES st_bld (id) ON DELETE CASCADE
) STRICT;

CREATE TABLE st_bld_pm (
    bld_id INTEGER NOT NULL,
    ord INTEGER NOT NULL,
    pm TEXT NOT NULL,
    PRIMARY KEY (bld_id, ord),
    FOREIGN KEY (bld_id) REFERENCES st_bld (id) ON DELETE CASCADE
);
