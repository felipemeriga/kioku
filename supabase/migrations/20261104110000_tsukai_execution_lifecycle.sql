ALTER TABLE public.tsukai_attempts ADD COLUMN diagnostic JSON;

CREATE TABLE tsukai_tombstones (
	id VARCHAR(64) NOT NULL, 
	owner_sha256 VARCHAR(64) NOT NULL, 
	conversation_sha256 VARCHAR(64) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	job_ids JSON NOT NULL, 
	session_keys JSON NOT NULL, 
	artifacts JSON NOT NULL, 
	created_at FLOAT NOT NULL, 
	updated_at FLOAT NOT NULL, 
	PRIMARY KEY (id)
)

;
ALTER TABLE public.tsukai_tombstones ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.tsukai_tombstones FROM anon, authenticated;
GRANT ALL ON public.tsukai_tombstones TO service_role;
