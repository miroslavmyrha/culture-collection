from typing import Any

from django.db.models import QuerySet
from rest_framework import serializers
from rest_framework.request import Request

from cultures.core.api import ScopedRelatedField
from cultures.labs.access import access_of
from cultures.labs.models import Lab, LocationGrant, Membership, VratAccess
from cultures.labs.permissions import Perm, Role
from cultures.users.models import User


class LabOutputSerializer(serializers.ModelSerializer[Lab]):
    """A lab and the caller's role in it (annotated by the selector, never one query per row)."""

    my_role = serializers.ChoiceField(choices=Role.choices, read_only=True)

    class Meta:
        model = Lab
        fields = ("public_id", "name", "code", "my_role")
        read_only_fields = fields


class MemberOutputSerializer(serializers.ModelSerializer[Membership]):
    username = serializers.CharField(source="user.username", read_only=True)
    first_name = serializers.CharField(source="user.first_name", read_only=True)
    last_name = serializers.CharField(source="user.last_name", read_only=True)

    class Meta:
        model = Membership
        fields = ("public_id", "username", "first_name", "last_name", "role", "created_at")
        read_only_fields = fields


def active_users(request: Request) -> QuerySet[User]:
    """Who a manager may add: any active user. Unknown and inactive give the same error."""
    return User.objects.filter(is_active=True)


class MemberCreateInputSerializer(serializers.Serializer[None]):
    # By username, resolved through a scope: a missing, an inactive and a malformed
    # username all give "Invalid user.", so the field cannot tell them apart.
    username = ScopedRelatedField(model=User, scope=active_users, slug_field="username")
    role = serializers.ChoiceField(choices=Role.choices)

    def validate_role(self, value: Any) -> Role:
        return Role(value)


class MemberRoleInputSerializer(serializers.Serializer[None]):
    role = serializers.ChoiceField(choices=Role.choices)

    def validate_role(self, value: Any) -> Role:
        return Role(value)


REASON_HELP = "Why, in a sentence. Stored for good: name no person."


class LocationGrantOutputSerializer(serializers.ModelSerializer[LocationGrant]):
    """An open grant: who may see where the lab's regulated strains are (ADR 0009)."""

    member = serializers.UUIDField(source="membership_public_id", read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = LocationGrant
        fields = ("public_id", "member", "username", "reason", "created_at")
        read_only_fields = fields


def lab_members(request: Request) -> QuerySet[Membership]:
    """Members of any lab the caller manages: the view keeps the lab of the URL."""
    return Membership.objects.for_access(access_of(request), Perm.MANAGE_MEMBERS)


class LocationGrantInputSerializer(serializers.Serializer[None]):
    member = ScopedRelatedField(model=Membership, scope=lab_members)
    reason = serializers.CharField(help_text=REASON_HELP)


class LocationRevokeInputSerializer(serializers.Serializer[None]):
    reason = serializers.CharField(help_text=REASON_HELP)


class VratAccessOutputSerializer(serializers.ModelSerializer[VratAccess]):
    """An entry of the lab's VRAT access list (act 281/2002 Sb., § 14a(4)): who, from when, until
    when, put on and taken off by whom and why. Open while `ended_at` is null. People are read
    through the user rows at read time: an erased person is their tombstone username."""

    username = serializers.CharField(source="user.username", read_only=True)
    first_name = serializers.CharField(source="user.first_name", read_only=True)
    last_name = serializers.CharField(source="user.last_name", read_only=True)
    granted_at = serializers.DateTimeField(source="created_at", read_only=True)
    granted_by = serializers.CharField(source="granted_by.username", read_only=True)
    # Null when nobody signed in ended it (a command deactivated the account).
    ended_by = serializers.CharField(source="ended_by.username", read_only=True, allow_null=True)

    class Meta:
        model = VratAccess
        fields = (
            "public_id",
            "username",
            "first_name",
            "last_name",
            "granted_at",
            "granted_by",
            "reason",
            "ended_at",
            "ended_by",
            "end_reason",
        )
        read_only_fields = fields


class VratAccessInputSerializer(serializers.Serializer[None]):
    # By username, like adding a member: a missing, an inactive and a malformed username give
    # the same error, and the service gives it too for an active user who is not a member.
    username = ScopedRelatedField(model=User, scope=active_users, slug_field="username")
    reason = serializers.CharField(help_text=REASON_HELP)


class VratAccessEndInputSerializer(serializers.Serializer[None]):
    reason = serializers.CharField(help_text=REASON_HELP)
