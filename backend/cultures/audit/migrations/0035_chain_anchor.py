"""The anchors of ADR 0009: a chain head's hash with a qualified timestamp over it (#175).

The chain alone is evidence only against someone who cannot recompute it
(ADR 0009, Alternatives considered: "A chain without an anchor: whoever can edit
rows can recompute it"). An anchor is the outside evidence: the head's hash with
a token from a qualified trust service provider over it, which carries a legal
presumption of its date and of the integrity of the data it covers (eIDAS,
Regulation (EU) No 910/2014, Article 41).

Who may write one: the runtime role has only SELECT on the table
(audit/roles.py), and `audit_chain_anchor_record` inserts the row as the audit
owner. The function refuses an anchor that does not name a real row of the chain
holding the hash it claims, so nobody can stamp a head that never existed, and
the runtime role can call it but not insert directly. Its EXECUTE is revoked from
PUBLIC here and granted to the runtime role by roles.apply_grants after every
migrate.

Append-only like the other audit tables: the two triggers of migration 0002
refuse UPDATE and DELETE for every role and TRUNCATE for every role that does not
own the table. The anchor table is not itself chained: the token is what vouches
for it.

A migration that replaces the function body starts from FORWARD here and uses
FORWARD as its own REVERSE.
"""

import cultures.audit.models
import uuid
from django.db import migrations, models


FORWARD = """
CREATE FUNCTION audit_chain_anchor_record(
    chain text, head_id bigint, head_hash bytea, authority text, token bytea,
    token_time timestamptz, public_id uuid
) RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    stored bytea;
    anchor_id bigint;
BEGIN
    IF chain = 'event' THEN
        SELECT a.chain_hash INTO stored FROM public.audit_auditevent a WHERE a.id = head_id;
    ELSIF chain = 'row_change' THEN
        SELECT a.chain_hash INTO stored FROM public.audit_rowchange a WHERE a.id = head_id;
    ELSE
        RAISE EXCEPTION 'unknown audit chain %', chain USING ERRCODE = 'check_violation';
    END IF;
    IF stored IS NULL OR stored <> head_hash THEN
        RAISE EXCEPTION 'an anchor names the real head: % row % does not hold that hash',
            chain, head_id USING ERRCODE = 'check_violation';
    END IF;
    INSERT INTO public.audit_chainanchor
        (public_id, chain, head_id, head_hash, anchored_at, authority, token, token_time)
    VALUES (public_id, chain, head_id, head_hash, transaction_timestamp(), authority,
            token, token_time)
    RETURNING id INTO anchor_id;
    RETURN anchor_id;
END;
$$;
REVOKE ALL ON FUNCTION audit_chain_anchor_record(
    text, bigint, bytea, text, bytea, timestamptz, uuid) FROM PUBLIC;
CREATE TRIGGER audit_append_only BEFORE UPDATE OR DELETE ON audit_chainanchor
    FOR EACH ROW EXECUTE FUNCTION audit_refuse_change();
CREATE TRIGGER audit_no_truncate BEFORE TRUNCATE ON audit_chainanchor
    FOR EACH STATEMENT EXECUTE FUNCTION audit_refuse_truncate();
"""

REVERSE = """
DROP TRIGGER audit_no_truncate ON audit_chainanchor;
DROP TRIGGER audit_append_only ON audit_chainanchor;
DROP FUNCTION audit_chain_anchor_record(text, bigint, bytea, text, bytea, timestamptz, uuid);
"""


class Migration(migrations.Migration):

    dependencies = [
        ('audit', '0034_hash_chain'),
    ]

    operations = [
        migrations.CreateModel(
            name='ChainAnchor',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('public_id', models.UUIDField(default=uuid.uuid4, unique=True)),
                ('chain', models.CharField(max_length=40)),
                ('head_id', models.BigIntegerField()),
                ('head_hash', models.BinaryField()),
                ('anchored_at', models.DateTimeField(db_default=cultures.audit.models.TransactionNow())),
                ('authority', models.CharField(max_length=100)),
                ('token', models.BinaryField()),
                ('token_time', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'indexes': [models.Index(fields=['chain', 'head_id'], name='audit_anchor_chain_head_idx')],
                'constraints': [models.CheckConstraint(condition=models.Q(('chain__in', ['event', 'row_change'])), name='audit_chainanchor_chain_valid')],
            },
        ),
        migrations.RunSQL(FORWARD, REVERSE),
    ]
