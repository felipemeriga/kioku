CREATE TABLE public.folders(id uuid PRIMARY KEY,user_id uuid NOT NULL,name text);
CREATE TABLE public.repo_symbols(folder_id uuid NOT NULL,user_id uuid NOT NULL,node_id text,
 symbol text,kind text,file text,start_line integer,updated_at timestamptz);
INSERT INTO folders VALUES
 ('00000000-0000-0000-0000-000000000001','11111111-1111-1111-1111-111111111111','first'),
 ('00000000-0000-0000-0000-000000000002','11111111-1111-1111-1111-111111111111','second'),
 ('00000000-0000-0000-0000-000000000003','22222222-2222-2222-2222-222222222222','foreign'),
 ('00000000-0000-0000-0000-000000000004','11111111-1111-1111-1111-111111111111','empty');
INSERT INTO repo_symbols
 SELECT f.id,f.user_id,g::text,'symbol-'||g,'function','Src/a.ts',g,'2026-11-09T12:00:00Z'
 FROM folders f CROSS JOIN generate_series(1,501) g WHERE f.name<>'empty';
-- Even a malformed graph row cannot cross the explicit owner boundary.
INSERT INTO repo_symbols VALUES ('00000000-0000-0000-0000-000000000001',
 '22222222-2222-2222-2222-222222222222','foreign','foreign','function','Src/a.ts',0,now());
ALTER DEFAULT PRIVILEGES GRANT EXECUTE ON FUNCTIONS TO anon,authenticated;
