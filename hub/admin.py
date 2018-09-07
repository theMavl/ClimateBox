from django.contrib import admin, auth
from .models import Location, Device, Readout, Alert, Log, AverageReadout

admin.site.register(Location)
admin.site.register(Readout)
admin.site.register(Alert)
admin.site.register(Log)
admin.site.register(AverageReadout)

admin.site.site_header = "ClimateBox Admin"
admin.site.site_title = "ClimateBox"
admin.site.index_title = "Панель администрирования"


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    def get_readonly_fields(self, request, obj=None):
        user = auth.get_user(request)
        if not user.is_superuser:
            return ["id", "MAC", "charge", "last_connection", "last_readout", "warning"]
        else:
            return ["id"]
