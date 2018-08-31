from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User, Group, Permission


class Command(BaseCommand):
    help = 'Creates initial users and entities'

    def handle(self, *args, **options):

        watcher_perms = ["change_device", "add_location", "change_location", "delete_location"]
        watcher_group = Group.objects.create(name='Наблюдатель')

        for p in watcher_perms:
            watcher_group.permissions.add(Permission.objects.get(codename=p))

        User.objects.create_superuser('HIDDEN', 'admin@example.com', 'HIDDEN')

        User.objects.create_superuser('HIDDEN', 'admin@example.com', 'HIDDEN')

        watcher = User.objects.create_user(username='HIDDEN', email='eeeemail@maaaail.com',
                                         password='HIDDEN',
                                         first_name='John', last_name='Smith', is_staff=True)
        watcher.groups.add(watcher_group)

        self.stdout.write(self.style.SUCCESS("Success"))
        print("populate complete!")
