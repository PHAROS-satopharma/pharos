-- PHAROS — what the coded terms say, per ingredient (2026-11-06; builds on 0061).
--
--   papers   collectors/coding/papers.py stores each literature paper's MeSH headings from PubMed in
--            document.structured -> 'mesh' ([{ui, name, major, q: [qualifier ui]}]). A paper reports a reaction
--            when a disease heading carries the qualifier "chemically induced" (Q000139), or sits under
--            Chemically-Induced Disorders (C25): that is how NLM's indexers mark an adverse effect.
--   cases    the MeSH code a reviewer chose for each reaction (0061).
--   labels   collectors/coding/labels.py finds the MeSH names in the adverse-reactions section of our own label
--            (our_label, section 4.8) and of the reference product's latest label (4.8, or the US "Adverse
--            reactions"): label_mesh. A reaction is listed when the label names it or a broader heading above it.
--   topics   safety_topic: groups of MeSH descriptors with everything beneath them, in place of MedDRA's SMQs
--            (which need a MedDRA licence). Seeded below; the descriptors were checked against MeSH 2026.
--
-- ingredient_mesh_counts() and ingredient_topic_counts() count, for the days chosen and the same number of days
-- before, the cases and the papers that report each term and each topic. Counting is not judging: the screen
-- shows the numbers and the label beside them, and the team decides.

create table safety_topic (
  id          text primary key check (id ~ '^[a-z0-9_]+$'),
  name        text not null,
  description text,
  uis         text[] not null check (cardinality(uis) > 0),   -- MeSH descriptors; everything beneath them counts
  sort        int not null default 100
);
alter table safety_topic enable row level security;
create policy safety_topic_read on safety_topic for select to authenticated using (my_role() is not null);

insert into safety_topic (id, name, uis, sort) values
  ('liver',         'Liver injury',                               '{D056486,D017093,D006505,D007565,D006932}', 10),
  ('scar',          'Severe skin reactions (SJS/TEN, DRESS, AGEP)', '{D013262,D063926,D056150,D004892}', 20),
  ('anaphylaxis',   'Anaphylaxis and angioedema',                 '{D000707,D000799}', 30),
  ('hypersens',     'Drug hypersensitivity',                      '{D004342}', 35),
  ('kidney',        'Acute kidney injury',                        '{D058186}', 40),
  ('qt',            'QT prolongation and torsades de pointes',    '{D008133,D016171}', 50),
  ('arrhythmia',    'Cardiac arrhythmias',                        '{D001145}', 55),
  ('brady_hypo',    'Slow heart rate, low blood pressure, fainting', '{D001919,D007022,D013575}', 56),
  ('heart_failure', 'Heart failure',                              '{D006333}', 60),
  ('ischaemia',     'Ischaemic heart disease',                    '{D017202}', 65),
  ('stroke',        'Stroke and cerebrovascular disorders',       '{D002561}', 70),
  ('thrombosis',    'Thrombosis and embolism',                    '{D013923,D013927}', 75),
  ('bleeding',      'Bleeding',                                   '{D006470}', 80),
  ('gi_ulcer',      'Peptic ulcer and gastrointestinal bleeding', '{D010437,D006471}', 85),
  ('cytopenia',     'Blood cytopenias',                           '{D000380,D013921,D010198,D000741}', 90),
  ('muscle',        'Rhabdomyolysis and myositis',                '{D012206,D009220}', 100),
  ('tendon',        'Tendon disorders',                           '{D052256,D013708}', 105),
  ('pancreatitis',  'Pancreatitis',                               '{D010195}', 110),
  ('ild',           'Interstitial lung disease',                  '{D017563}', 115),
  ('hypoglycaemia', 'Hypoglycaemia',                              '{D007003}', 120),
  ('hyperglycaemia','Hyperglycaemia',                             '{D006943}', 125),
  ('lactic',        'Lactic acidosis',                            '{D000140}', 130),
  ('electrolytes',  'Potassium and sodium disturbances',          '{D006947,D007010}', 135),
  ('seizures',      'Seizures',                                   '{D012640}', 140),
  ('neuropathy',    'Peripheral neuropathy',                      '{D010523}', 145),
  ('nms_serotonin', 'Neuroleptic malignant and serotonin syndromes', '{D009459,D020230}', 150),
  ('psychiatric',   'Depression, psychosis and delirium',         '{D003863,D003866,D011618,D006212,D003693}', 155),
  ('suicide',       'Suicide and self-harm',                      '{D016728}', 160),
  ('hearing',       'Hearing loss and tinnitus',                  '{D034381,D014012}', 165),
  ('pregnancy',     'Pregnancy loss and birth defects',           '{D000022,D000013}', 170),
  ('malignancy',    'Malignancies',                               '{D009369}', 175);

-- Every descriptor in a topic: its own descriptors and everything beneath them in the tree.
create view topic_descriptor with (security_invoker = true) as
select distinct t.id as topic_id, d.ui
  from safety_topic t
  join mesh_descriptor s on s.ui = any (t.uis)
  join mesh_descriptor d on exists (select 1 from unnest(d.trees) dt, unnest(s.trees) st
                                     where dt = st or dt like st || '.%');

-- The labels coded, and the MeSH names found in their adverse-reactions sections. No reference to
-- mesh_descriptor: a new MeSH release replaces the dictionary, and the labels are coded again after it.
create table label_coded (
  ingredient_id uuid not null references ingredient (id) on delete cascade,
  source        text not null check (source in ('our_label','reference')),
  label_ref     text not null,          -- our_label.id, or the reference product's spc_snapshot.id
  label_name    text not null,          -- what the screen calls it: product and version
  mesh_version  text,
  terms         int  not null,
  coded_at      timestamptz not null default now(),
  primary key (ingredient_id, source)
);
create table label_mesh (
  ingredient_id uuid not null,
  source        text not null,
  ui            text not null,
  term          text not null,          -- the name as found in the label
  primary key (ingredient_id, source, ui),
  foreign key (ingredient_id, source) references label_coded (ingredient_id, source) on delete cascade
);
alter table label_coded enable row level security;
alter table label_mesh  enable row level security;
create policy label_coded_read on label_coded for select to authenticated using (my_role() is not null);
create policy label_mesh_read  on label_mesh  for select to authenticated using (my_role() is not null);

-- Which label lists a reaction: our label first, then the reference product's; null when neither does.
create function mesh_listed(p_ingredient uuid, p_ui text) returns text language sql stable security invoker
set search_path = public as $$
  select lm.source
    from label_mesh lm
    join mesh_descriptor l on l.ui = lm.ui
    join mesh_descriptor r on r.ui = p_ui
   where lm.ingredient_id = p_ingredient
     and exists (select 1 from unnest(r.trees) rt, unnest(l.trees) lt where rt = lt or rt like lt || '.%')
   order by lm.source = 'our_label' desc
   limit 1
$$;

-- Each case and paper of the ingredient with each reaction term it reports, and its day.
create function ingredient_coded_terms(p_ingredient uuid)
returns table (kind text, item uuid, ui text, day date) language sql stable security invoker
set search_path = public as $$
  select 'case', c.id, r ->> 'mesh_ui', c.day_zero
    from safety_case c,
         jsonb_array_elements(case when jsonb_typeof(c.data -> 'reactions') = 'array'
                                   then c.data -> 'reactions' else '[]'::jsonb end) r
   where c.ingredient_id = p_ingredient
     and c.status in ('to_confirm','confirmed','sent')
     and coalesce(r ->> 'mesh_ui', '') <> ''
  union
  select 'paper', d.id, m ->> 'ui', coalesce(d.published_date, (d.first_seen_at at time zone 'Africa/Cairo')::date)
    from issue_ingredient ii
    join issue_document idoc on idoc.issue_id = ii.issue_id and idoc.method <> 'suggested'
    join document d on d.id = idoc.document_id and d.doc_type = 'literature'
    cross join lateral jsonb_array_elements(case when jsonb_typeof(d.structured -> 'mesh') = 'array'
                                                 then d.structured -> 'mesh' else '[]'::jsonb end) m
    join mesh_descriptor md on md.ui = m ->> 'ui'
   where ii.ingredient_id = p_ingredient
     and (coalesce(m -> 'q', '[]'::jsonb) ? 'Q000139'
          or exists (select 1 from unnest(md.trees) t where t like 'C25%'))
$$;

create function ingredient_mesh_counts(p_ingredient uuid, p_from date, p_to date)
returns table (ui text, name text, categories text[], cases_now int, cases_before int, papers_now int,
               papers_before int, listed text)
language sql stable security invoker set search_path = public as $$
  with s as (select p_from - (p_to - p_from + 1) as b_from, p_from - 1 as b_to),
  t as (select * from ingredient_coded_terms(p_ingredient)),
  n as (
    select t.ui,
           count(distinct t.item) filter (where t.kind = 'case'  and t.day between p_from and p_to)       as cn,
           count(distinct t.item) filter (where t.kind = 'case'  and t.day between s.b_from and s.b_to)   as cb,
           count(distinct t.item) filter (where t.kind = 'paper' and t.day between p_from and p_to)       as pn,
           count(distinct t.item) filter (where t.kind = 'paper' and t.day between s.b_from and s.b_to)   as pb
      from t, s
     group by t.ui)
  select d.ui, d.name, mesh_category(d.trees), n.cn::int, n.cb::int, n.pn::int, n.pb::int,
         mesh_listed(p_ingredient, d.ui)
    from n join mesh_descriptor d on d.ui = n.ui
   where n.cn + n.cb + n.pn + n.pb > 0
   order by n.cn + n.pn desc, n.cb + n.pb desc, d.name
$$;

create function ingredient_topic_counts(p_ingredient uuid, p_from date, p_to date)
returns table (topic text, name text, cases_now int, cases_before int, papers_now int, papers_before int,
               terms text[])
language sql stable security invoker set search_path = public as $$
  with s as (select p_from - (p_to - p_from + 1) as b_from, p_from - 1 as b_to),
  t as (select ct.*, td.topic_id from ingredient_coded_terms(p_ingredient) ct
          join topic_descriptor td on td.ui = ct.ui)
  select st.id, st.name,
         (count(distinct t.item) filter (where t.kind = 'case'  and t.day between p_from and p_to))::int,
         (count(distinct t.item) filter (where t.kind = 'case'  and t.day between s.b_from and s.b_to))::int,
         (count(distinct t.item) filter (where t.kind = 'paper' and t.day between p_from and p_to))::int,
         (count(distinct t.item) filter (where t.kind = 'paper' and t.day between s.b_from and s.b_to))::int,
         array_agg(distinct d.name order by d.name)
    from t cross join s
    join safety_topic st on st.id = t.topic_id
    join mesh_descriptor d on d.ui = t.ui
   where t.day between s.b_from and p_to
   group by st.id, st.name, st.sort
   order by st.sort
$$;

revoke all on function mesh_listed(uuid, text), ingredient_coded_terms(uuid),
  ingredient_mesh_counts(uuid, date, date), ingredient_topic_counts(uuid, date, date) from public, anon;
grant execute on function mesh_listed(uuid, text), ingredient_coded_terms(uuid),
  ingredient_mesh_counts(uuid, date, date), ingredient_topic_counts(uuid, date, date) to authenticated;
grant select on topic_descriptor to authenticated;
