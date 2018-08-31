import datetime

from django.core.exceptions import ValidationError
from django.db import models
from macaddress.fields import MACAddressField
from django.contrib.auth.models import User

from ClimateBox.settings import DEVICE_DEFAULT_SLEEP_TIME
from hub.tasks import async_send_mail


class Location(models.Model):
    buildings_list = (
        ('un', 'Университет'),
        ('d1', 'Жилой комплекс к.1'),
        ('d2', 'Жилой комплекс к.2'),
        ('d3', 'Жилой комплекс к.3'),
        ('d4', 'Жилой комплекс к.4'),
        ('d5', 'Жилой комплекс к.5')
    )
    building = models.CharField(verbose_name="Здание", max_length=2, choices=buildings_list, default='u')
    floor = models.IntegerField(verbose_name='Этаж', null=True)
    room = models.IntegerField(verbose_name='Номер аудитории', null=True, blank=True)
    description = models.CharField(verbose_name="Описание расположения",
                                   help_text="Указать при необходимости (несколько расположений в "
                                             "одной аудитории/находится вне аудитории)", blank=True, null=True,
                                   max_length=50)
    warm_season_normal_temp = models.FloatField(verbose_name='Норма летом',
                                                help_text="Нормальная температура в этой зоне в теплые месяцы "
                                                          "(Апрель-Сентябрь) (24°C по умолчанию)",
                                                default=24.0)
    cold_season_normal_temp = models.FloatField(verbose_name='Норма зимой',
                                                help_text="Нормальная температура в этой зоне в холодные месяцы "
                                                          "(Ноябрь-Март) (22°C по умолчанию)",
                                                default=22.0)
    max_temp_deviation = models.FloatField(verbose_name='Макс. отклонение',
                                           help_text="Максимально возможное отклонение от нормальной температуры "
                                                     "(2°C по умолчанию)",
                                           default=2)

    def __str__(self):
        descr = dict(self.buildings_list)[self.building] + " " + str(self.floor)
        descr += ("-" + str(self.room)) if self.room is not None else " этаж"
        descr += ("" if (self.description is None or self.description == "") else (" - " + self.description))
        return descr

    def name(self):
        return str(self)

    # Constraints
    def clean(self):
        if self.room is None and self.description is None:
            raise ValidationError(
                'Не указаны ни номер аудитории, ни описание. Пожалуйста, заполните хотя бы одно из этих полей')

    class Meta:
        verbose_name = 'расположение'
        verbose_name_plural = 'расположения'


class Device(models.Model):
    MAC = MACAddressField(null=True, unique=True)
    location = models.ForeignKey('Location', verbose_name='Расположение', on_delete=models.PROTECT, null=True,
                                 blank=True)
    has_temp_sensor = models.BooleanField(verbose_name='Датчик температуры', null=False, default=True)
    has_CO2_sensor = models.BooleanField(verbose_name='Датчик углек. газа', null=False, default=False)
    has_humid_sensor = models.BooleanField(verbose_name='Датчик влажности', null=False, default=False)
    has_motion_sensor = models.BooleanField(verbose_name='Датчик движения', null=False, default=False)
    charge = models.FloatField(verbose_name='Заряд батареи', help_text="Текущий ровень заряда батареи", null=True)
    battery_capacity = models.FloatField(verbose_name='Макс. заряд',
                                         help_text="Максимальный уровень заряда (см на аккумуляторе)", null=True)
    sleep_period = models.IntegerField(verbose_name='Время сна',
                                       help_text="Время Deep Sleep в мс (по умолчанию %d мс или %d мин)"
                                                 % (DEVICE_DEFAULT_SLEEP_TIME, DEVICE_DEFAULT_SLEEP_TIME / 60000),
                                       default=DEVICE_DEFAULT_SLEEP_TIME)
    last_connection = models.DateTimeField(verbose_name='Последнее подключение',
                                           help_text="Когда было последнее подключение", null=True, blank=True)
    allow_untrusted = models.BooleanField(verbose_name='Разрешить всё',
                                          help_text="Принимать все запросы с этого устройства, игнорируя проверку "
                                                    "времени (ТОЛЬКО ДЛЯ ОБСЛУЖИВАНИЯ)",
                                          default=False)
    last_readout = models.ForeignKey('Readout', related_name='readout', null=True, blank=True,
                                     on_delete=models.SET_NULL)
    warning = models.IntegerField(default=0)

    def __str__(self):
        descr = "%s (%1.1f%%) %s%s%s%s" % (
            self.location, self.battery_level(), ("ТЕМП " if self.has_temp_sensor else ""),
            ("C02 " if self.has_CO2_sensor else ""),
            ("ВЛАЖН " if self.has_humid_sensor else ""), ("ДВИЖ" if self.has_motion_sensor else ""))
        return descr

    def alert(self):
        alerts = Alert.objects.filter(location=self.location)
        return True if alerts else False

    def battery_level(self):
        if self.charge is None or self.battery_capacity is None:
            return -1
        return self.charge / self.battery_capacity * 100

    class Meta:
        ordering = ('location',)
        verbose_name = 'устройство'
        verbose_name_plural = 'устройства'


class Readout(models.Model):
    timestamp = models.DateTimeField()
    device = models.ForeignKey('Device', on_delete=models.SET_NULL, null=True)
    location = models.ForeignKey('Location', on_delete=models.CASCADE)
    charge = models.FloatField()
    temp = models.FloatField(null=True, blank=True)
    CO2 = models.FloatField(null=True, blank=True)
    humid = models.FloatField(null=True, blank=True)
    motion = models.BooleanField(default=False)

    def __str__(self):
        descr = "[%s] [%s] %s%s%s%s" % (
            self.timestamp, self.location, ("Температура: " + str(self.temp) + "°C " if self.temp is not None else ""),
            (" | Уровень C02: " + str(self.CO2) if self.CO2 is not None else ""),
            (" | Влажность: " + str(self.humid) + "%" if self.humid is not None else ""),
            (" | Движение: " + str(
                self.motion) if self.device is not None and self.device.has_motion_sensor else ""))
        return descr

    class Meta:
        ordering = ('-timestamp',)


class Alert(models.Model):
    timestamp = models.DateTimeField(null=True)
    location = models.ForeignKey('Location', on_delete=models.CASCADE, null=True, blank=True)
    readout = models.ForeignKey('Readout', on_delete=models.CASCADE, null=True, blank=True)
    message = models.TextField(null=True, blank=True)
    type_list = (
        ('t', 'Temperature alert'),
        ('c', 'CO2 level alert'),
        ('h', 'Humidity level alert'),
        ('b', 'Battery level alert'),
        ('o', 'Out of sync alert'),
        ('s', 'Service alert')
    )
    critical = models.BooleanField(default=False)
    type = models.CharField(max_length=1, choices=type_list, blank=True, default='s')
    counter = models.IntegerField(default=1)
    email_sent = models.BooleanField(default=False)
    email_timestamp = models.DateTimeField(null=True, blank=True)
    email_sender = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return "%s - %s" % (self.timestamp.strftime("%d.%m.%Y %H:%M:%S"), self.message)

    class Meta:
        ordering = ('-timestamp',)

    def send_alert(self, sender):
        if not self.email_sent:
            async_send_mail.delay("ClimateBox", self.message, self.id, sender.id)


class Log(models.Model):
    timestamp = models.DateTimeField(auto_now=True)
    type_list = (
        ('n', 'Notification'),
        ('w', 'Warning'),
        ('e', 'Error')
    )
    type = models.CharField(max_length=1, choices=type_list, default='n')
    tag = models.TextField()
    message = models.TextField()

    def __str__(self):
        return "%s %s [%s] %s" % (self.type.upper(), self.timestamp.strftime("%d.%m.%Y %H:%M:%S"), self.tag, self.message)

