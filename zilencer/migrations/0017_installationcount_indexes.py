# Generated by Django 1.11.20 on 2019-04-23 20:17

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("zilencer", "0016_remote_counts"),
    ]

    operations = [
        migrations.AlterIndexTogether(
            name="remoteinstallationcount",
            index_together={("server", "remote_id")},
        ),
        migrations.AlterIndexTogether(
            name="remoterealmcount",
            index_together={("property", "end_time"), ("server", "remote_id")},
        ),
    ]