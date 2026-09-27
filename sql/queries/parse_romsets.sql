-- Read-only DAT parsing exploration, formerly romsets.sql.
-- The persisted transform is etl.v_romset.
with romsets as materialized
(
select distinct
	rf.dat_root_full_name as key,
	rf.dat_name as name
from staging.rv_files rf
where rf.dat_name is not null
),
parts as (
	select
		rs.key,
		rs.name,
		(regexp_split_to_array(rs.key,'/'))[2:] as parts_path,
		(regexp_match(rs.name,'(?:(Arcade) - )?(.+?) - ([^\(]+)(?: \(([^\)]+)\))?(?: \(([^\)]+)\))?')) as parts_name
	from romsets rs
)
select
	p.key,
	p.name,
	p.parts_path[1] as romset,
	case
		when p.parts_path[1] in ('TOSEC','TOSEC-ISO') then p.parts_path[2]
		else p.parts_name[2]
	end as manufacturer,
	case
		when p.parts_path[1] in ('TOSEC','TOSEC-ISO') then p.parts_path[3]
		else p.parts_name[3]
	end as system,
	case
		when p.parts_path[1] in ('TOSEC','TOSEC-ISO') then p.parts_path[4:array_length(p.parts_path,1)-1]
		else array_remove(array[p.parts_name[1]] || p.parts_name[4:],null)
	end as additional
from parts p
where p.parts_path[1] in ('No-Intro','Redump','TOSEC','TOSEC-ISO');
