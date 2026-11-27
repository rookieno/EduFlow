from rest_framework.serializers import CharField, Serializer


class StaffLoginSerializer(Serializer):
    username = CharField(max_length=150)
    password = CharField(max_length=4096, trim_whitespace=False, write_only=True)
