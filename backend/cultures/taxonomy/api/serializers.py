from rest_framework import serializers

from cultures.taxonomy.models import Taxon, TaxonIdentifier


class TaxonBriefSerializer(serializers.ModelSerializer[Taxon]):
    """A taxon inside another resource: enough to show and link it."""

    class Meta:
        model = Taxon
        fields = ("public_id", "name", "authority", "rank", "status")
        read_only_fields = fields


class TaxonIdentifierOutputSerializer(serializers.ModelSerializer[TaxonIdentifier]):
    class Meta:
        model = TaxonIdentifier
        fields = ("system", "value")
        read_only_fields = fields


class TaxonOutputSerializer(serializers.ModelSerializer[Taxon]):
    parent = TaxonBriefSerializer(read_only=True, allow_null=True)
    # A synonym names its accepted taxon, so a form can say what the name stands for.
    accepted = TaxonBriefSerializer(read_only=True, allow_null=True)
    identifiers = TaxonIdentifierOutputSerializer(many=True, read_only=True)

    class Meta:
        model = Taxon
        fields = (
            "public_id",
            "name",
            "authority",
            "rank",
            "status",
            "parent",
            "accepted",
            "identifiers",
        )
        read_only_fields = fields
