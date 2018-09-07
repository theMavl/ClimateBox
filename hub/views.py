from datetime import timedelta, datetime

from django.conf import settings
from django.contrib import auth
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User, Group
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.utils.crypto import get_random_string
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ClimateBox.settings import HUB_SECRET_KEY_LENGTH, DEVICE_DEFAULT_SLEEP_TIME
from hub.models import Readout, Device, Alert, Log, AverageReadout
from hub.serializers import UserSerializer, GroupSerializer, ReadoutListSerializer, ReadoutCreateSerializer, \
    DeviceListSerializer, DeviceCreateSerializer, BatteryReadoutListSerializer, AlertListSerializer
from hub.tasks import remove_old_alerts, check_devices, process_readout, async_send_mail, async_generate_year_readouts, \
    async_remove_all_readouts_from_location, calculate_averages


@login_required
def index(request):
    return render(request, 'index.html')


@login_required
@staff_member_required
def secret_key(request):
    return JsonResponse({'key': settings.hub_secret_key})


class UserViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows users to be viewed or edited.
    """
    queryset = User.objects.all().order_by('-date_joined')
    serializer_class = UserSerializer

    permission_classes = (permissions.IsAuthenticatedOrReadOnly,)


class GroupViewSet(viewsets.ModelViewSet):
    queryset = Group.objects.all()
    serializer_class = GroupSerializer


# Used in ListViews
periods = {None: 0, "today": 1, "week": 7, "month": 30, "year": 365}


class ReadoutViewSet(viewsets.ModelViewSet):
    """
    list:
    Show readouts by given location and time period. GET params: location=id, period=[today, week, month, year] (if none - returns latest readout)

    create:
    Send new readout.
    """
    http_method_names = ['get', 'post', 'options']

    def get_serializer_class(self):
        if self.action == 'list':
            return ReadoutListSerializer
        if self.action == 'create':
            return ReadoutCreateSerializer
        return ReadoutListSerializer

    def list(self, request, *args, **kwarg):
        if not request.user.is_authenticated:
            return Response("You need to log in", status=status.HTTP_401_UNAUTHORIZED)

        location = request.query_params.get('location', None)
        period = request.query_params.get('period', None)

        if period is None:
            latest = Readout.objects.filter(Q(location=location) & Q(temp__isnull=False))
            if latest:
                queryset = Readout.objects.filter(id=latest.first().id)
            else:
                queryset = Readout.objects.none()
        else:
            start_date = datetime.now()
            delta = periods[period]
            end_date = start_date - timedelta(days=delta)
            queryset = Readout.objects.filter(
                Q(location=location) & Q(timestamp__range=[end_date, start_date]) & Q(temp__isnull=False))
            if queryset.count() > 600:
                queryset = AverageReadout.objects.filter(
                Q(location=location) & Q(timestamp__range=[end_date, start_date]) & Q(temp__isnull=False))

        serializer = self.get_serializer(queryset, many=True)

        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        is_many = True if isinstance(request.data, list) else False
        serializer = self.get_serializer(data=request.data, many=is_many)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        new_sleep_time = process_readout(serializer.instance)
        return Response(str(new_sleep_time), status=status.HTTP_201_CREATED, headers=headers)

    def perform_create(self, serializer):
        try:
            many = serializer.many
        except AttributeError:
            many = False
        data = serializer.validated_data
        print(many)
        if many:
            device = data[-1]['device']
        else:
            device = data['device']
        location = device.location
        # Log.objects.create(type='n', tag="readout_create", message="Creating new readout. Bulk: %s. Data: %s. Data[-1]: %s" % (many, data, data[-1] if many else ""))	
        if "timestamp" in data or many:
            serializer.save(location=location)
        else:
            serializer.save(location=location, timestamp=datetime.now())
        print(serializer)
        device.last_connection = datetime.now()
        device.last_readout_id = serializer.instance.id if not many else serializer.instance[-1].id
        device.charge = serializer.instance.charge if not many else serializer.instance[-1].charge
        device.save()

    def retrieve(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def destroy(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    queryset = Readout.objects.all()
    permission_classes = ()


class DeviceViewSet(viewsets.ModelViewSet):
    """
    list:
    Show all located devices (location is not None)

    create:
    Register new device

    retrieve:
    Get device details

    battery:
    Get battery readouts for given device id. GET params: period=[today, week, month, year]
    """
    http_method_names = ['get', 'post', 'options']

    def get_serializer_class(self):
        if self.action == 'list':
            return DeviceListSerializer
        if self.action == 'create':
            return DeviceCreateSerializer
        if self.action == 'battery':
            return BatteryReadoutListSerializer
        return DeviceListSerializer

    def list(self, request, *args, **kwarg):
        if not request.user.is_authenticated:
            return Response("You need to log in", status=status.HTTP_401_UNAUTHORIZED)

        queryset = Device.objects.filter(location__isnull=False)
        serializer = DeviceListSerializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=True, permission_classes=[permissions.IsAuthenticated, ])
    def battery(self, request, pk=None):
        period = request.query_params.get('period', None)
        if period is None:
            latest = Readout.objects.filter(device_id=pk)
            if latest:
                queryset = Readout.objects.filter(id=latest.first().id)
            else:
                queryset = Readout.objects.none()
        else:
            start_date = datetime.now()
            delta = periods[period]
            end_date = start_date - timedelta(days=delta)
            queryset = Readout.objects.filter(
                Q(device_id=pk) & Q(timestamp__range=[end_date, start_date]))
            if queryset.count() > 600:
                queryset = AverageReadout.objects.filter(
                    Q(device_id=pk) & Q(timestamp__range=[end_date, start_date]))

        serializer = self.get_serializer(queryset, many=True)

        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        key = self.request.data["key"]
        if not key == settings.hub_secret_key:
            print(request.META)
            Log.objects.create(type='e', tag="device_registration",
                               message="Attempt to register with bad key; " + str(request.META))
            return Response("Bad key", status=status.HTTP_403_FORBIDDEN)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        device = Device.objects.filter(MAC=serializer.validated_data["MAC"])
        if device:
            device = device.first()
            Log.objects.create(type='n', tag="device_registration",
                               message="Device %s already exists" % device.MAC)
            ret_status = status.HTTP_304_NOT_MODIFIED
        else:
            device = Device.objects.create(MAC=serializer.validated_data["MAC"],
                                           charge=serializer.validated_data["charge"],
                                           allow_untrusted=True, sleep_period=DEVICE_DEFAULT_SLEEP_TIME)
            device.save()
            ret_status = status.HTTP_201_CREATED
            Log.objects.create(type='n', tag="device_registration",
                               message="Created new device %s" % device.MAC)
        settings.hub_secret_key = get_random_string(length=HUB_SECRET_KEY_LENGTH).upper()

        return Response(str(device.id) + "," + str(device.sleep_period), status=ret_status)

    def destroy(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def retrieve(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return Response("You need to log in", status=status.HTTP_401_UNAUTHORIZED)
        return super().retrieve(request, *args, **kwargs)

    queryset = Device.objects.all()
    permission_classes = ()


class AlertViewSet(viewsets.ModelViewSet):
    """
    list:

    """
    http_method_names = ['get', 'options']
    queryset = Alert.objects.all()
    serializer_class = AlertListSerializer
    permission_classes = (IsAuthenticated,)

    def list(self, request, *args, **kwarg):
        location = request.query_params.get('location', None)

        if location is None:
            queryset = Alert.objects.all()
        else:
            queryset = Alert.objects.filter(location_id=location)

        serializer = self.get_serializer(queryset, many=True)

        return Response(serializer.data)

    @action(methods=['get'], detail=True, permission_classes=[permissions.IsAuthenticated, ])
    def send(self, request, pk):
        alert = Alert.objects.filter(id=pk)
        if alert:
            alert = alert.first()
            if alert.email_sent:
                return Response("Already sent", status=status.HTTP_400_BAD_REQUEST)
            if not alert.type == 't':
                return Response("Bad alert type (only temperature alerts allowed)", status=status.HTTP_400_BAD_REQUEST)

            alert.send_alert(auth.get_user(request))

            return Response("Email sent", status=status.HTTP_200_OK)
        else:
            return Response("Alert not found", status=status.HTTP_404_NOT_FOUND)


@login_required
@user_passes_test(lambda u: u.is_superuser)
def debug_interface(request):
    task = request.GET["task"]
    print(task)
    if task == '0':
        remove_old_alerts()
    elif task == '1':
        check_devices()
    elif task == '2':
        async_send_mail("LETTER", "Hey there!", 2, 1)
    elif task == '3':
        async_generate_year_readouts.delay(2, 2)
    elif task == '4':
        async_remove_all_readouts_from_location.delay(2)
    elif task == '5':
        calculate_averages.delay()

    return redirect('index')
