-- Image cache: stores binary image data from SEC EDGAR, persists across Render redeploys.
-- Natural key: (cik, accession_no, filename) mirrors SECClient._get_image_cache_path convention.
-- cik uses leading-zeros-stripped form (matches URL construction in sec_client.py).

CREATE TABLE IF NOT EXISTS image_cache (
    cik             TEXT NOT NULL,
    accession_no    TEXT NOT NULL,
    filename        TEXT NOT NULL,
    image_data      BYTEA NOT NULL,
    content_type    TEXT,
    size_bytes      INTEGER NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (cik, accession_no, filename)
);

CREATE INDEX IF NOT EXISTS idx_image_cache_created ON image_cache(created_at);

COMMENT ON TABLE image_cache IS 'Binary cache of SEC EDGAR image files; persists across Render redeploys.';
