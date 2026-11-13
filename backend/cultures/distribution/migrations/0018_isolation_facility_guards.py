"""A quarantine pest goes out only to a recipient whose isolation facility is recorded (#197).

Two helpers and the two guards that call them:

- distribution_isolation_facility_recorded: whether an authorisation of an isolation facility of
  the requester holds on a day. `distribution.policy.isolation_facility_recorded` asks the same
  in Python, and a parity test compares the two.
- distribution_check_quarantine_facility: the rule of one package, on the Czech day the package
  was recorded (Europe/Prague, as `biosafety.policy.permit_today` reads it).
- The preparation guard and the shipment guard (from 0016) call it on every INSERT, so no
  QuerySet.update(), raw SQL or psql session writes a package the gate would refuse. A hard line
  with no override, like the § 17a notice of a RAT.

Rows written before this migration are untouched: the guards read the row being written.

The two helpers are not revoked from PUBLIC, unlike the trigger functions: a guard calls them as
the role that writes the row. They pin their search_path and reach the other tables through the
schema their caller passes.
"""

from importlib import import_module

from django.db import migrations

FUNCTIONS = r"""
-- #197: whether the requester's authorisation of an isolation facility holds on `day`
-- (Implementing Regulation (EU) 2019/829, Art. 5 c)). The same window as
-- biosafety.policy.valid_on, which policy.isolation_facility_recorded reads in Python.
CREATE FUNCTION distribution_isolation_facility_recorded(schema_name text, requester bigint,
    day date) RETURNS boolean
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    held boolean;
BEGIN
    EXECUTE format('SELECT EXISTS (SELECT FROM %I.distribution_recipientpermit'
        ' WHERE requester_id = $1 AND kind = ''plant_health_isolation'''
        ' AND valid_from <= $2 AND (expires_on IS NULL OR expires_on >= $2)'
        ' AND (ended_on IS NULL OR ended_on > $2))', schema_name)
        INTO held USING requester, day;
    RETURN held;
END;
$$;

-- The rule of one package, for the preparation guard and the shipment guard alike.
CREATE FUNCTION distribution_check_quarantine_facility(schema_name text, request bigint,
    day date, package uuid) RETURNS void
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    pest boolean;
    requester bigint;
    held boolean;
BEGIN
    EXECUTE format('SELECT EXISTS (SELECT FROM %1$I.distribution_requestline l'
        ' JOIN %1$I.strains_strainrestriction r ON r.strain_id = l.strain_id'
        ' WHERE l.request_id = $1 AND r.ended_at IS NULL'
        ' AND r.kind = ''quarantine_pest'')', schema_name)
        INTO pest USING request;
    IF NOT pest THEN
        RETURN;
    END IF;
    EXECUTE format('SELECT requester_id FROM %I.distribution_distributionrequest WHERE id = $1',
        schema_name) INTO requester USING request;
    EXECUTE format('SELECT %1$I.distribution_isolation_facility_recorded($1, $2, $3)', schema_name)
        INTO held USING schema_name, requester, day;
    IF NOT held THEN
        RAISE EXCEPTION 'a quarantine pest goes only to a recipient whose authorisation of an isolation facility is recorded (package %)',
            package USING ERRCODE = 'check_violation';
    END IF;
END;
$$;
"""

REVERSE = """
DROP FUNCTION distribution_check_quarantine_facility(text, bigint, date, uuid);
DROP FUNCTION distribution_isolation_facility_recorded(text, bigint, date);
"""

# The call each guard gains, with the Czech day of its own timestamp.
CALL = """    EXECUTE format('SELECT %1$I.distribution_check_quarantine_facility($1, $2, $3, $4)',
        TG_TABLE_SCHEMA) USING TG_TABLE_SCHEMA, NEW.request_id,
        (NEW.{moment} AT TIME ZONE 'Europe/Prague')::date, NEW.public_id;
"""
# The line of 0016 that each call goes after: the GMO class, then the facility.
AFTER = """    EXECUTE format('SELECT %1$I.distribution_check_gmo_class($1, $2, $3, $4)', TG_TABLE_SCHEMA)
        USING TG_TABLE_SCHEMA, NEW.request_id, NEW.transport_class, NEW.public_id;
"""


def _from_0016(name: str) -> str:
    """The function `name` as migration 0016 wrote it, as a replace."""
    source: str = import_module(
        "cultures.distribution.migrations.0016_gmo_transport_class"
    ).FUNCTIONS
    start = source.index(f"FUNCTION {name}()")
    start = source.rindex("CREATE", 0, start)
    end = source.index("$$;", source.index("$$", start) + 2) + len("$$;")
    body = source[start:end]
    return body if body.startswith("CREATE OR REPLACE") else "CREATE OR REPLACE" + body[6:]


def _with_call(name: str, moment: str) -> str:
    """The guard of 0016 with the facility check beside the class check it already makes."""
    body = _from_0016(name)
    if body.count(AFTER) != 1:
        raise RuntimeError(f"{name}: the class check of migration 0016 is not where it was")
    return body.replace(AFTER, AFTER + CALL.format(moment=moment))


GUARDS = "\n".join(
    _with_call(name, moment)
    for name, moment in (
        ("distribution_shipmentpreparation_guard", "prepared_at"),
        ("distribution_shipment_guard", "shipped_at"),
    )
)
RESTORE = "\n".join(
    _from_0016(name)
    for name in ("distribution_shipmentpreparation_guard", "distribution_shipment_guard")
)


class Migration(migrations.Migration):
    dependencies = [("distribution", "0017_isolation_facility")]

    operations = [migrations.RunSQL(FUNCTIONS + GUARDS, RESTORE + REVERSE)]
