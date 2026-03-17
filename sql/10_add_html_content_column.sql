ALTER TABLE filings ADD COLUMN IF NOT EXISTS html_content TEXT;
COMMENT ON COLUMN filings.html_content IS 'Raw HTML content for cloud environments without persistent disk';
