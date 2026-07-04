PRAGMA foreign_keys = ON;

-- 实体与关系表在 load_origin_sqlite 中按依赖顺序创建。
-- state_region 的资源列由 RESOURCE_COLUMNS 动态追加。

DROP TABLE IF EXISTS tag__state__building;
DROP TABLE IF EXISTS tag__technology;
DROP TABLE IF EXISTS tag__market_master;
DROP TABLE IF EXISTS tag__state;
DROP TABLE IF EXISTS tag;
DROP TABLE IF EXISTS country_definition;
DROP TABLE IF EXISTS named_color;
DROP TABLE IF EXISTS state_meta;
DROP TABLE IF EXISTS state;
DROP TABLE IF EXISTS state_region;
