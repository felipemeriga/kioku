-- Durable execution is private; domain publication is owned by consumers.

CREATE TABLE tsukai_jobs (
	id VARCHAR(36) NOT NULL, 
	owner_id VARCHAR(128) NOT NULL, 
	caller VARCHAR(20) NOT NULL, 
	idempotency_key VARCHAR(200) NOT NULL, 
	payload_hash VARCHAR(64) NOT NULL, 
	request_sha256 VARCHAR(64) NOT NULL, 
	request JSON NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	profile VARCHAR(30) NOT NULL, 
	conversation_id VARCHAR(128), 
	attempt_count INTEGER NOT NULL, 
	next_seq INTEGER NOT NULL, 
	created_at FLOAT NOT NULL, 
	updated_at FLOAT NOT NULL, 
	queue_deadline FLOAT NOT NULL, 
	result JSON, 
	error JSON, 
	cancel_requested BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (owner_id, caller, idempotency_key)
)

;
ALTER TABLE public.tsukai_jobs ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.tsukai_jobs FROM anon, authenticated;
GRANT ALL ON public.tsukai_jobs TO service_role;

CREATE TABLE tsukai_sessions (
	owner_id VARCHAR(128) NOT NULL, 
	conversation_id VARCHAR(128) NOT NULL, 
	native_session_id VARCHAR(36) NOT NULL, 
	generation INTEGER NOT NULL, 
	policy_fingerprint VARCHAR(64) NOT NULL, 
	history JSON NOT NULL, 
	state VARCHAR(30) NOT NULL, 
	workspace TEXT NOT NULL, 
	last_cost FLOAT, 
	last_counters JSON, 
	updated_at FLOAT NOT NULL, 
	PRIMARY KEY (owner_id, conversation_id), 
	UNIQUE (native_session_id)
)

;
ALTER TABLE public.tsukai_sessions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.tsukai_sessions FROM anon, authenticated;
GRANT ALL ON public.tsukai_sessions TO service_role;

CREATE TABLE tsukai_attempts (
	id VARCHAR(36) NOT NULL, 
	job_id VARCHAR(36) NOT NULL, 
	number INTEGER NOT NULL, 
	fence VARCHAR(36) NOT NULL, 
	worker_id VARCHAR(36) NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	lease_until FLOAT NOT NULL, 
	deadline FLOAT NOT NULL, 
	started_at FLOAT NOT NULL, 
	finished_at FLOAT, 
	native_session_id VARCHAR(36) NOT NULL, 
	resume BOOLEAN NOT NULL, 
	counter_segment VARCHAR(36) NOT NULL, 
	usage JSON, 
	error JSON, 
	PRIMARY KEY (id), 
	UNIQUE (job_id, number), 
	FOREIGN KEY(job_id) REFERENCES tsukai_jobs (id)
)

;
ALTER TABLE public.tsukai_attempts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.tsukai_attempts FROM anon, authenticated;
GRANT ALL ON public.tsukai_attempts TO service_role;

CREATE TABLE tsukai_events (
	job_id VARCHAR(36) NOT NULL, 
	seq INTEGER NOT NULL, 
	attempt_id VARCHAR(36), 
	type VARCHAR(50) NOT NULL, 
	data JSON NOT NULL, 
	created_at FLOAT NOT NULL, 
	PRIMARY KEY (job_id, seq), 
	FOREIGN KEY(job_id) REFERENCES tsukai_jobs (id)
)

;
ALTER TABLE public.tsukai_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.tsukai_events FROM anon, authenticated;
GRANT ALL ON public.tsukai_events TO service_role;

CREATE TABLE tsukai_locks (
	key VARCHAR(300) NOT NULL, 
	job_id VARCHAR(36) NOT NULL, 
	attempt_id VARCHAR(36), 
	fence VARCHAR(36), 
	lease_until FLOAT NOT NULL, 
	PRIMARY KEY (key), 
	FOREIGN KEY(job_id) REFERENCES tsukai_jobs (id)
)

;
ALTER TABLE public.tsukai_locks ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.tsukai_locks FROM anon, authenticated;
GRANT ALL ON public.tsukai_locks TO service_role;

CREATE TABLE tsukai_result_acks (
	job_id VARCHAR(36) NOT NULL, 
	consumer VARCHAR(100) NOT NULL, 
	reference VARCHAR(512) NOT NULL, 
	created_at FLOAT NOT NULL, 
	PRIMARY KEY (job_id, consumer), 
	FOREIGN KEY(job_id) REFERENCES tsukai_jobs (id)
)

;
ALTER TABLE public.tsukai_result_acks ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.tsukai_result_acks FROM anon, authenticated;
GRANT ALL ON public.tsukai_result_acks TO service_role;

CREATE INDEX tsukai_jobs_runnable ON public.tsukai_jobs(status, created_at);
CREATE INDEX tsukai_attempts_expiry ON public.tsukai_attempts(status, lease_until);
CREATE INDEX tsukai_events_retention ON public.tsukai_events(created_at);
