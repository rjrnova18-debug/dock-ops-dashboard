"""
Data migration: the "History viewers" group, holding the history permission.

Giving someone access to the history is then just adding them to this group in the admin.
Django normally creates permissions after all migrations have run, so on a fresh
database the permission is created here first (get_or_create); Django finds it later.
"""
from django.db import migrations

GROUP = "History viewers"


def create_group(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")

    content_type, _ = ContentType.objects.get_or_create(app_label="board", model="transport")
    permission, _ = Permission.objects.get_or_create(
        content_type=content_type, codename="view_history", defaults={"name": "Can view the history page"})
    group, _ = Group.objects.get_or_create(name=GROUP)
    group.permissions.add(permission)


def remove_group(apps, schema_editor):
    apps.get_model("auth", "Group").objects.filter(name=GROUP).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("board", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [migrations.RunPython(create_group, remove_group)]
