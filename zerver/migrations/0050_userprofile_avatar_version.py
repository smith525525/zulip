# Generated by Django 1.10.5 on 2017-01-23 17:44
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("zerver", "0049_userprofile_pm_content_in_desktop_notifications"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="avatar_version",
            field=models.PositiveSmallIntegerField(default=1),
        ),
    ]
