from rest_framework import serializers

from cultures.users.models import User


class LoginInputSerializer(serializers.Serializer[None]):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(
        max_length=256, trim_whitespace=False, style={"input_type": "password"}
    )


class MeOutputSerializer(serializers.ModelSerializer[User]):
    class Meta:
        model = User
        fields = ("public_id", "username", "first_name", "last_name", "email")
        read_only_fields = fields
