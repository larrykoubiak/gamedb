-- Read-only source-system coverage, formerly canonical.sql.
select
	vr.manufacturer,vr."system",
	sum(case when vr.romset in ('No-Intro','Redump') then 1 else 0 end) >= 1 as no_intro_redump,
	sum(case when vr.romset in ('TOSEC','TOSEC-ISO') then 1 else 0 end) >= 1 as tosec
from
	etl.v_romset vr
group by
	 vr.manufacturer,vr."system"
order by 1, 2;
