from datetime import datetime

from django.contrib.auth.models import User, Group
from rest_framework import serializers

from ClimateBox.settings import HUB_SECRET_KEY_LENGTH
from hub.models import Readout, Device, Alert


class UserSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = User
        fields = ('url', 'username', 'email', 'groups')


class GroupSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Group
        fields = ('url', 'name')


class ReadoutListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Readout
        fields = ('timestamp', 'temp', 'CO2', 'humid')


class ReadoutCreateSerializer(serializers.ModelSerializer):
    timestamp = serializers.DateTimeField(required=False, help_text="Timestamp")
    device = serializers.SlugRelatedField(slug_field="id", required=True, queryset=Device.objects.all(),
                                          help_text="Sender-device id")
    charge = serializers.FloatField(help_text="Current battery voltage")

    class Meta:
        model = Readout
        fields = ('id', 'timestamp', 'device', 'charge', 'temp', 'CO2', 'humid')

    def validate(self, data):
        import numbers
        import math
        if "temp" in data:
            if math.isnan(data["temp"]):
                raise serializers.ValidationError("Temperature should be a number")
        if "charge" in data:
            if math.isnan(data["charge"]):
                raise serializers.ValidationError("Charge should be a number")
        if "CO2" in data:
            if math.isnan(data["CO2"]):
                raise serializers.ValidationError("CO2 level should be a number")
        if "humid" in data:
            if math.isnan(data["temp"]):
                raise serializers.ValidationError("Humidity should be a number")
        return data

    @staticmethod
    def validate_device(value):
        if value is None:
            raise serializers.ValidationError("Device is not specified")
        if value.location is None:
            raise serializers.ValidationError("The location for this device is not set")
        if not value.allow_untrusted and value.last_connection is not None:
            l_c = value.last_connection.timestamp()
            t_now = datetime.now().timestamp()
            if l_c - t_now < value.sleep_period / 1000 or l_c > t_now:
                raise serializers.ValidationError("Untrusted behaviour - Rejected")
        return value


class DeviceListSerializer(serializers.ModelSerializer):
    location_id = serializers.PrimaryKeyRelatedField(many=False, read_only=True)
    location = serializers.StringRelatedField(many=False, read_only=True)

    class Meta:
        model = Device
        fields = ('id', 'location', 'location_id', 'battery_level', 'alert')


class AlertListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Alert
        fields = ('id', 'timestamp', 'location', 'type', 'message', 'critical', 'counter', 'email_sent')


class DeviceCreateSerializer(serializers.ModelSerializer):
    key = serializers.CharField(max_length=HUB_SECRET_KEY_LENGTH, help_text="/api/secret_key")

    def create(self, validated_data):
        return Device(MAC=validated_data["MAC"], charge=validated_data["charge"])

    class Meta:
        model = Device
        fields = ('key', 'MAC', 'charge')


class BatteryReadoutListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Readout
        fields = ('timestamp', 'charge')
