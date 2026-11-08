"""The official lists are not editable in the app (#169), against every writer.

A reading of a list and its entries are written once, by the loader
(cultures.biosafety.lists), and changed by nothing afterwards: no screen, no API and no admin
page writes one, and these triggers refuse the rest, also from QuerySet.update(), raw SQL and
psql.

- biosafety_regulatorylist: never deleted. The one update it takes is losing is_current, which
  the next reading of the same list does; every other column, is_current going back on and a
  row of another list's code are refused.
- biosafety_regulatorylistentry: never updated, never deleted. An entry is inserted with a
  reading that is current, so no entry is added to a list version that was replaced, and what
  its list says about it must fit that list: only annex 7 of government order 361/2007 Sb.
  states a risk group, and each list gives the restrictions of biosafety.models.
  LIST_RESTRICTIONS (annex 1 of decree 474/2002 Sb. the VRAT, annex 2 the RAT).

The functions pin their search_path and reach the other table through TG_TABLE_SCHEMA. The
runtime role has SELECT, INSERT and UPDATE on the readings and SELECT and INSERT on the
entries (audit.roles), so the guards are the second line, not the first.
"""

from django.db import migrations

FUNCTIONS = r"""
CREATE FUNCTION biosafety_regulatorylist_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'a reading of an official list is never deleted (list %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF TG_OP = 'INSERT' THEN
        RETURN NEW;
    END IF;
    IF (to_jsonb(NEW) - 'is_current' - 'updated_at')
       IS DISTINCT FROM (to_jsonb(OLD) - 'is_current' - 'updated_at') THEN
        RAISE EXCEPTION 'a reading of an official list is never edited (list %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.is_current AND NOT OLD.is_current THEN
        RAISE EXCEPTION 'a reading that was replaced does not become current again (list %)',
            OLD.public_id USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION biosafety_regulatorylistentry_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    list_code text;
    list_current boolean;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'an entry of an official list is never deleted (entry %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'an entry of an official list is never edited (entry %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    EXECUTE format('SELECT code, is_current FROM %I.biosafety_regulatorylist WHERE id = $1',
        TG_TABLE_SCHEMA) INTO list_code, list_current USING NEW.list_id;
    IF NOT list_current THEN
        RAISE EXCEPTION 'an entry is added to the current reading of its list (entry %)',
            NEW.public_id USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.risk_group IS NOT NULL AND list_code <> 'cz-361-2007-annex-7' THEN
        RAISE EXCEPTION 'only annex 7 of government order 361/2007 Sb. states a risk group (entry %)',
            NEW.public_id USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.restriction_kind <> '' AND NOT (
           list_code = 'cz-474-2002' AND NEW.restriction_kind IN ('cz_vrat', 'cz_rat')
        OR list_code = 'eu-2021-821-annex-i' AND NEW.restriction_kind = 'dual_use'
        OR list_code = 'eu-2019-2072-annex-ii' AND NEW.restriction_kind = 'quarantine_pest')
       OR NEW.restriction_kind = '' AND list_code <> 'cz-361-2007-annex-7' THEN
        RAISE EXCEPTION 'an entry gives the restriction its own list gives (entry %)',
            NEW.public_id USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION biosafety_regulatorylist_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION biosafety_regulatorylistentry_guard() FROM PUBLIC;

CREATE TRIGGER biosafety_regulatorylist_guard
    BEFORE INSERT OR UPDATE OR DELETE ON biosafety_regulatorylist
    FOR EACH ROW EXECUTE FUNCTION biosafety_regulatorylist_guard();

CREATE TRIGGER biosafety_regulatorylistentry_guard
    BEFORE INSERT OR UPDATE OR DELETE ON biosafety_regulatorylistentry
    FOR EACH ROW EXECUTE FUNCTION biosafety_regulatorylistentry_guard();
"""

REVERSE = """
DROP TRIGGER biosafety_regulatorylistentry_guard ON biosafety_regulatorylistentry;
DROP TRIGGER biosafety_regulatorylist_guard ON biosafety_regulatorylist;
DROP FUNCTION biosafety_regulatorylistentry_guard();
DROP FUNCTION biosafety_regulatorylist_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("biosafety", "0004_regulatory_lists")]

    operations = [migrations.RunSQL(FUNCTIONS, REVERSE)]
