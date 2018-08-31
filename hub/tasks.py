import logging
import os
from datetime import datetime, timedelta

from celery import Celery
from celery.schedules import crontab
from celery.task import task, periodic_task
from celery.utils.log import get_task_logger
from django.core.mail import send_mail
from django.template.loader import render_to_string

from ClimateBox.settings import DEVICE_DEFAULT_SLEEP_TIME, BOX_EMAIL, SERVICE_EMAIL, DEVICE_NIGHT_SLEEP_TIME
# from hub.models import Readout, Alert, Device

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from ClimateBox.celery import app, logger


# logger = get_task_logger(__name__)


@periodic_task(run_every=(crontab(minute='*/720')), name="remove_old_alerts", ignore_result=True)
def remove_old_alerts(period=24):
    """
    Removes alerts created earlier that in the last :period: hours.
    :param period: in hours
    """
    from hub.models import Alert, Log
    Log.objects.create(type='n', tag = "remove_old_alerts", message="Searching for old alerts started")
    end_date = datetime.now() - timedelta(hours=period)
    alerts = Alert.objects.filter(timestamp__lt=end_date)
    Log.objects.create(type='n', tag = "remove_old_alerts", message="To be removed: %s" % alerts)
    alerts.delete()


@periodic_task(run_every=(crontab(minute='*/30')), name="check_devices", ignore_result=True)
def check_devices():
    from hub.models import Device, Alert, Log
    logger.info("Checking devices")
    print("Checking devices")
    Log.objects.create(type='n', tag = "check_devices", message="Searching of outdated devices started")
    devices = Device.objects.filter(location__isnull=False)
    t_now = datetime.now().timestamp()
    for device in devices:
        l_c = device.last_connection.timestamp()
        print(device, device.last_connection, t_now - l_c, (device.sleep_period / 1000) * 2.5)
        if t_now - l_c > (device.sleep_period / 1000) * 2.5:
            alert, created = Alert.objects.get_or_create(location=device.location, type='o', critical=True)
            if not created:
                alert.counter += 1
            alert.message = "Устройство, расположенное в [%s], не вышло на связь более двух раз. " \
                            "Время последней синхронизации: %s. Последний известный уровень заряда батареи: %1.1f%%" % \
                            (device.location, str(device.last_connection.strftime("%d.%m.%Y %H:%M:%S")),
                             device.battery_level())
            Log.objects.create(type='w', tag = "check_devices", message=alert.message)
            alert.timestamp = datetime.now()
            alert.save()
            device.warning = 2
            device.save()


def process_readout(readout) -> int:
    from hub.models import Alert, Log
    def season():
        """
        Is it cold season now or not
        :return: 0 if winter, 1 otherwise
        """
        month = datetime.now().month
        return 0 if month in {1, 2, 3, 10, 11, 12} else 1

    Log.objects.create(type='n', tag = "process_readout", message="Processing readout...")
    if isinstance(readout, list):
        readout = readout[-1]  # The last element - the newest element
    # Temperature check
    if datetime.now().time().hour in range(8, 24):
        sleep_time = DEVICE_DEFAULT_SLEEP_TIME
    else:
        sleep_time = DEVICE_NIGHT_SLEEP_TIME
    location = readout.location
    norm_temp = location.cold_season_normal_temp if season() == 0 else location.warm_season_normal_temp
    deviation = readout.temp - norm_temp
    if abs(deviation) > location.max_temp_deviation:
        temp_status = "низкая" if deviation < 0 else "высокая"
        if abs(deviation) > location.max_temp_deviation * 3:
            critical = True
            temp_status = "Критически " + temp_status
        else:
            critical = False
            temp_status = "Слишком " + temp_status

        alert, created = Alert.objects.get_or_create(location=location, type='t')
        message = "[%s] %s температура в [%s]: %1.1f°C" % (
            readout.timestamp.strftime("%A, %d %B %Y %H:%M:%S"), temp_status, readout.location, readout.temp)
        alert.message = message
        alert.timestamp = datetime.now()
        Log.objects.create(type='w', tag = "process_readout", message="Alert: " + message)
        if not created:
            alert.counter += 1
            if critical and alert.critical:
                if not alert.email_sent:
                    async_send_mail.delay("ClimateBox", message, alert.id, 1)
            elif critical and not alert.critical:
                alert.critical = True
            elif not critical and alert.critical:
                alert.critical = False
        else: # New critical
            sleep_time = 180000  # 3 min
        alert.save()

        readout.device.warning = 2 if critical else 1
        readout.device.sleep_period = sleep_time
        readout.device.save()

    # Battery check
    if readout.device.battery_level() <= 0.1:
        alert, created = Alert.objects.get_or_create(location=location, type='b')
        critical = True
        alert.timestamp = readout.timestamp
        battery_status = "" if critical else "почти "
        message = "Батарея устройства, расположенного в [%s], %sразряжена (%s%%)" % (
            readout.location, battery_status, str(readout.device.battery_level()))
        Log.objects.create(type='w', tag = "process_readout", message="Battery Alert: " + message)
        alert.message = message
        alert.critical = critical
        if created:
            pass
        else:
            alert.counter += 1
        alert.save()
    else:
        alert = Alert.objects.filter(location=location, type='b')
        alert.delete()
      
    sync_alert = Alert.objects.filter(location=location, type='o')
    sync_alert.delete()
    return sleep_time


@task(name="send_email_task")
def async_send_mail(title, message, alert_id, sender_id):
    from hub.models import Alert, Log
    Log.objects.create(type='n', tag = "async_send_mail", message='Sending email. Title: "%s" Text: "%s" Alert: %d Sender: %d' % (title, message, alert_id, sender_id))
    alert = Alert.objects.filter(id=alert_id)
    if alert:
        alert = alert.first()
    else:
        return False

    html = render_to_string('mails/alert_template.html', {
        'message': message
    })
    email = EmailMultiAlternatives(title, html, to=[SERVICE_EMAIL])
    email.attach_alternative(html, "text/html")
    email.from_email = BOX_EMAIL
    # send_mail(title, html, BOX_EMAIL, [SERVICE_EMAIL])
    email.send()
    alert.email_timestamp = datetime.now()
    alert.email_sender_id = sender_id
    alert.email_sent = True
    alert.save()
    Log.objects.create(type='n', tag = "async_send_mail", message='Sent successfully')
    return True
