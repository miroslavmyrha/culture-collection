"""A restriction points at the entry of the official list it names (#169), against every writer.

Two triggers on strains_strainrestriction, beside the guard of 0003 that already lets a
restriction change by nothing but ending (so what these check at the insert stays true):

- strains_restriction_list_entry, BEFORE INSERT. A dual-use item names an entry code of Annex I
  of Regulation (EU) 2021/821 and nothing else, so its row must point at an entry of the current
  reading of that annex whose code is the reference. A GMO is on no list and points at none.
  A VRAT, a RAT or a quarantine pest is referred to by the words of its annex, which the app
  does not own, so an entry is attached where the reference is one and not demanded; where it
  is attached, the entry's list must give that restriction and be the current reading.
- strains_restriction_cz_agent, a deferred constraint trigger. The last box of #169: an Annex I
  entry of 1C351.a, 1C351.c, 1C351.e or 1C354 that decree 474/2002 Sb. also lists is a highly
  risky agent (annex 1, VRAT) or a risky one (annex 2, RAT), and the strain must carry that
  restriction as well. Deferred to the commit, because a strain gets both restrictions in one
  transaction and the order inside it is the service's business. The two entries are the same
  organism when they derive the same scientific name at the same scope
  (biosafety.lists.match_of); nothing matches by substring.

The messages name the restriction's public id and the restriction kind that is missing, never
the agent. The functions pin their search_path and reach the list tables through TG_TABLE_SCHEMA.
"""

from django.db import migrations

FUNCTIONS = r"""
CREATE FUNCTION strains_restriction_list_entry() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    entry_code text;
    entry_kind text;
    entry_list text;
    list_current boolean;
BEGIN
    IF NEW.list_entry_id IS NOT NULL THEN
        EXECUTE format('SELECT e.code, e.restriction_kind, l.code, l.is_current'
            ' FROM %1$I.biosafety_regulatorylistentry e'
            ' JOIN %1$I.biosafety_regulatorylist l ON l.id = e.list_id'
            ' WHERE e.id = $1', TG_TABLE_SCHEMA)
            INTO entry_code, entry_kind, entry_list, list_current USING NEW.list_entry_id;
        IF NOT list_current OR entry_kind IS DISTINCT FROM NEW.kind THEN
            RAISE EXCEPTION 'a restriction points at an entry of the current reading of its own list (restriction %)',
                NEW.public_id USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    IF NEW.kind = 'dual_use' THEN
        IF NEW.list_entry_id IS NULL OR entry_list <> 'eu-2021-821-annex-i'
           OR entry_code IS DISTINCT FROM NEW.reference THEN
            RAISE EXCEPTION 'a dual-use restriction names an entry Annex I of Regulation (EU) 2021/821 holds (restriction %)',
                NEW.public_id USING ERRCODE = 'check_violation';
        END IF;
    ELSIF NEW.kind = 'gmo' AND NEW.list_entry_id IS NOT NULL THEN
        RAISE EXCEPTION 'a GMO is on no official list and points at no entry (restriction %)',
            NEW.public_id USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION strains_restriction_cz_agent() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    missing text;
BEGIN
    EXECUTE format('SELECT cz.restriction_kind'
        ' FROM %1$I.strains_strainrestriction r'
        ' JOIN %1$I.biosafety_regulatorylistentry du ON du.id = r.list_entry_id'
        ' JOIN %1$I.biosafety_regulatorylist dul ON dul.id = du.list_id'
        ' JOIN %1$I.biosafety_regulatorylistentry cz'
        '   ON cz.match_name = du.match_name AND cz.match_scope = du.match_scope'
        '  AND cz.restriction_kind IN (''cz_vrat'', ''cz_rat'')'
        ' JOIN %1$I.biosafety_regulatorylist czl ON czl.id = cz.list_id'
        ' WHERE r.strain_id = $1 AND r.ended_at IS NULL AND r.kind = ''dual_use'''
        '   AND dul.is_current AND czl.is_current AND czl.code = ''cz-474-2002'''
        '   AND length(du.match_name) > 0'
        '   AND (du.code ~ ''^1C351\.(a|c|e)(\.|$)'' OR du.code ~ ''^1C354(\.|$)'')'
        '   AND NOT EXISTS (SELECT FROM %1$I.strains_strainrestriction h'
        '        WHERE h.strain_id = r.strain_id AND h.ended_at IS NULL'
        '          AND h.kind = cz.restriction_kind)'
        ' ORDER BY cz.restriction_kind LIMIT 1', TG_TABLE_SCHEMA)
        INTO missing USING NEW.strain_id;
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'a dual-use entry decree 474/2002 Sb. also lists needs its own restriction (% is missing, restriction %)',
            missing, NEW.public_id USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END;
$$;

REVOKE ALL ON FUNCTION strains_restriction_list_entry() FROM PUBLIC;
REVOKE ALL ON FUNCTION strains_restriction_cz_agent() FROM PUBLIC;

CREATE TRIGGER strains_restriction_list_entry
    BEFORE INSERT ON strains_strainrestriction
    FOR EACH ROW EXECUTE FUNCTION strains_restriction_list_entry();

CREATE CONSTRAINT TRIGGER strains_restriction_cz_agent
    AFTER INSERT OR UPDATE ON strains_strainrestriction DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION strains_restriction_cz_agent();
"""

REVERSE = """
DROP TRIGGER strains_restriction_cz_agent ON strains_strainrestriction;
DROP TRIGGER strains_restriction_list_entry ON strains_strainrestriction;
DROP FUNCTION strains_restriction_cz_agent();
DROP FUNCTION strains_restriction_list_entry();
"""


class Migration(migrations.Migration):
    dependencies = [("strains", "0015_restriction_list_entry")]

    operations = [migrations.RunSQL(FUNCTIONS, REVERSE)]
