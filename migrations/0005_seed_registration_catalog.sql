-- ============================================================================
-- Migration 0005 — seed the registration catalog
-- States (36), countries (14), mock categories (4), catalog exams (22).
-- Idempotent via ON CONFLICT (code).
-- ============================================================================

-- ---- States & UTs (ISO 3166-2:IN) ----
insert into mock_db.states (code, name, kind, position) values
  ('AP','Andhra Pradesh','state',1),
  ('AR','Arunachal Pradesh','state',2),
  ('AS','Assam','state',3),
  ('BR','Bihar','state',4),
  ('CG','Chhattisgarh','state',5),
  ('GA','Goa','state',6),
  ('GJ','Gujarat','state',7),
  ('HR','Haryana','state',8),
  ('HP','Himachal Pradesh','state',9),
  ('JH','Jharkhand','state',10),
  ('KA','Karnataka','state',11),
  ('KL','Kerala','state',12),
  ('MP','Madhya Pradesh','state',13),
  ('MH','Maharashtra','state',14),
  ('MN','Manipur','state',15),
  ('ML','Meghalaya','state',16),
  ('MZ','Mizoram','state',17),
  ('NL','Nagaland','state',18),
  ('OD','Odisha','state',19),
  ('PB','Punjab','state',20),
  ('RJ','Rajasthan','state',21),
  ('SK','Sikkim','state',22),
  ('TN','Tamil Nadu','state',23),
  ('TG','Telangana','state',24),
  ('TR','Tripura','state',25),
  ('UP','Uttar Pradesh','state',26),
  ('UK','Uttarakhand','state',27),
  ('WB','West Bengal','state',28),
  ('AN','Andaman and Nicobar Islands','ut',29),
  ('CH','Chandigarh','ut',30),
  ('DH','Dadra and Nagar Haveli and Daman and Diu','ut',31),
  ('DL','Delhi','ut',32),
  ('JK','Jammu and Kashmir','ut',33),
  ('LA','Ladakh','ut',34),
  ('LD','Lakshadweep','ut',35),
  ('PY','Puducherry','ut',36)
on conflict (code) do update set name = excluded.name, kind = excluded.kind, position = excluded.position;

-- ---- Countries (curated study destinations) ----
insert into mock_db.countries (code, name, position) values
  ('DE','Germany',1),
  ('US','United States',2),
  ('GB','United Kingdom',3),
  ('CA','Canada',4),
  ('AU','Australia',5),
  ('IE','Ireland',6),
  ('NZ','New Zealand',7),
  ('FR','France',8),
  ('NL','Netherlands',9),
  ('SG','Singapore',10),
  ('IT','Italy',11),
  ('SE','Sweden',12),
  ('CH','Switzerland',13),
  ('AE','United Arab Emirates',14)
on conflict (code) do update set name = excluded.name, position = excluded.position;

-- ---- Mock categories ----
insert into mock_db.mock_categories (code, name, position) values
  ('JOB','Competitive Exam for Job',1),
  ('STUDY_INDIA','Competitive Exam for Further Study in India',2),
  ('STUDY_ABROAD','Competitive Exam for Further Study Abroad',3),
  ('K6_K12','K6-K12',4)
on conflict (code) do update set name = excluded.name, position = excluded.position;

-- ---- Catalog exams (per category) ----
insert into mock_db.catalog_exams (category_id, code, name, position, requires_country, default_country_code)
select c.id, v.code, v.name, v.position, v.requires_country, v.default_country_code
from (values
  -- Job
  ('JOB','RAILWAY','Railway',1,false,null),
  ('JOB','BANK','Bank',2,false,null),
  ('JOB','SSC','SSC',3,false,null),
  ('JOB','UPSC','UPSC',4,false,null),
  ('JOB','STATE_PCS','State PCS',5,false,null),
  ('JOB','OTHER_JOB','Other Competitive Exam',6,false,null),
  -- Study in India
  ('STUDY_INDIA','JEE_MAINS','IIT-JEE Mains',1,false,null),
  ('STUDY_INDIA','JEE_ADVANCED','IIT-JEE Advanced',2,false,null),
  ('STUDY_INDIA','CAT','CAT',3,false,null),
  ('STUDY_INDIA','NEET','NEET',4,false,null),
  -- Study abroad (all require a country; d-MAT defaults to Germany)
  ('STUDY_ABROAD','DMAT','d-MAT',1,true,'DE'),
  ('STUDY_ABROAD','GMAT','GMAT',2,true,null),
  ('STUDY_ABROAD','GRE','GRE',3,true,null),
  ('STUDY_ABROAD','TOEFL','TOEFL',4,true,null),
  ('STUDY_ABROAD','IELTS','IELTS',5,true,null),
  -- K6-K12
  ('K6_K12','CLASS_6','Class 6',1,false,null),
  ('K6_K12','CLASS_7','Class 7',2,false,null),
  ('K6_K12','CLASS_8','Class 8',3,false,null),
  ('K6_K12','CLASS_9','Class 9',4,false,null),
  ('K6_K12','CLASS_10','Class 10',5,false,null),
  ('K6_K12','CLASS_11','Class 11',6,false,null),
  ('K6_K12','CLASS_12','Class 12',7,false,null)
) as v(category_code, code, name, position, requires_country, default_country_code)
join mock_db.mock_categories c on c.code = v.category_code
on conflict (code) do update set
  category_id = excluded.category_id,
  name = excluded.name,
  position = excluded.position,
  requires_country = excluded.requires_country,
  default_country_code = excluded.default_country_code;

-- ---- Link d-MAT catalog entry to the real dMAT examination content ----
update mock_db.catalog_exams
set linked_examination_id = (select id from mock_db.examinations where code = 'dMAT')
where code = 'DMAT';
