# Generated by Django 1.11.4 on 2017-09-28 22:56

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("zerver", "0149_realm_emoji_drop_unique_constraint"),
    ]

    operations = [
        migrations.AddField(
            model_name="realm",
            name="allow_community_topic_editing",
            field=models.BooleanField(default=False),
        ),
    ]
