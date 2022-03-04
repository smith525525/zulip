# Generated by Django 3.2.2 on 2021-05-19 11:53

import bitfield.models
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("zerver", "0325_alter_realmplayground_unique_together"),
    ]

    operations = [
        migrations.AlterField(
            model_name="realm",
            name="authentication_methods",
            field=bitfield.models.BitField(
                [
                    "Google",
                    "Email",
                    "GitHub",
                    "LDAP",
                    "Dev",
                    "RemoteUser",
                    "AzureAD",
                    "SAML",
                    "GitLab",
                    "Apple",
                    "OpenID Connect",
                ],
                default=2147483647,
            ),
        ),
    ]
