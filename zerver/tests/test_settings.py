import time
from typing import Any, Dict
from unittest import mock

import orjson
from django.http import HttpRequest, HttpResponse
from django.test import override_settings

from zerver.lib.initial_password import initial_password
from zerver.lib.rate_limiter import add_ratelimit_rule, remove_ratelimit_rule
from zerver.lib.test_classes import ZulipTestCase
from zerver.lib.test_helpers import get_test_image_file
from zerver.lib.users import get_all_api_keys
from zerver.models import Draft, UserProfile, get_user_profile_by_api_key


class ChangeSettingsTest(ZulipTestCase):
    # TODO: requires method consolidation, right now, there's no alternative
    # for check_for_toggle_param for PATCH.
    def check_for_toggle_param_patch(self, pattern: str, param: str) -> None:
        self.login("hamlet")
        user_profile = self.example_user("hamlet")
        json_result = self.client_patch(pattern, {param: orjson.dumps(True).decode()})
        self.assert_json_success(json_result)
        # refetch user_profile object to correctly handle caching
        user_profile = self.example_user("hamlet")
        self.assertEqual(getattr(user_profile, param), True)

        json_result = self.client_patch(pattern, {param: orjson.dumps(False).decode()})
        self.assert_json_success(json_result)
        # refetch user_profile object to correctly handle caching
        user_profile = self.example_user("hamlet")
        self.assertEqual(getattr(user_profile, param), False)

    def test_successful_change_settings(self) -> None:
        """
        A call to /json/settings with valid parameters changes the user's
        settings correctly and returns correct values.
        """
        user = self.example_user("hamlet")
        self.login_user(user)
        json_result = self.client_patch(
            "/json/settings",
            dict(
                full_name="Foo Bar",
                old_password=initial_password(user.delivery_email),
                new_password="foobar1",
            ),
        )
        self.assert_json_success(json_result)

        user.refresh_from_db()
        self.assertEqual(user.full_name, "Foo Bar")
        self.logout()

        # This is one of the few places we log in directly
        # with Django's client (to test the password change
        # with as few moving parts as possible).
        request = HttpRequest()
        request.session = self.client.session
        self.assertTrue(
            self.client.login(
                request=request,
                username=user.delivery_email,
                password="foobar1",
                realm=user.realm,
            ),
        )
        self.assert_logged_in_user_id(user.id)

    def test_password_change_check_strength(self) -> None:
        self.login("hamlet")
        with self.settings(PASSWORD_MIN_LENGTH=3, PASSWORD_MIN_GUESSES=1000):
            json_result = self.client_patch(
                "/json/settings",
                dict(
                    full_name="Foo Bar",
                    old_password=initial_password(self.example_email("hamlet")),
                    new_password="easy",
                ),
            )
            self.assert_json_error(json_result, "New password is too weak!")

            json_result = self.client_patch(
                "/json/settings",
                dict(
                    full_name="Foo Bar",
                    old_password=initial_password(self.example_email("hamlet")),
                    new_password="f657gdGGk9",
                ),
            )
            self.assert_json_success(json_result)

    def test_illegal_name_changes(self) -> None:
        user = self.example_user("hamlet")
        self.login_user(user)
        full_name = user.full_name

        with self.settings(NAME_CHANGES_DISABLED=True):
            json_result = self.client_patch("/json/settings", dict(full_name="Foo Bar"))

        # We actually fail silently here, since this only happens if
        # somebody is trying to game our API, and there's no reason to
        # give them the courtesy of an error reason.
        self.assert_json_success(json_result)

        user = self.example_user("hamlet")
        self.assertEqual(user.full_name, full_name)

        # Now try a too-long name
        json_result = self.client_patch("/json/settings", dict(full_name="x" * 1000))
        self.assert_json_error(json_result, "Name too long!")

        # Now try a too-short name
        json_result = self.client_patch("/json/settings", dict(full_name="x"))
        self.assert_json_error(json_result, "Name too short!")

    def test_illegal_characters_in_name_changes(self) -> None:
        self.login("hamlet")

        # Now try a name with invalid characters
        json_result = self.client_patch("/json/settings", dict(full_name="Opheli*"))
        self.assert_json_error(json_result, "Invalid characters in name!")

    def test_change_email_to_disposable_email(self) -> None:
        hamlet = self.example_user("hamlet")
        self.login_user(hamlet)
        realm = hamlet.realm
        realm.disallow_disposable_email_addresses = True
        realm.emails_restricted_to_domains = False
        realm.save()

        json_result = self.client_patch("/json/settings", dict(email="hamlet@mailnator.com"))
        self.assert_json_error(json_result, "Please use your real email address.")

    # This is basically a don't-explode test.
    def test_notify_settings(self) -> None:
        for notification_setting in UserProfile.notification_setting_types.keys():
            # `notification_sound` is a string not a boolean, so this test
            # doesn't work for it.
            #
            # TODO: Make this work more like do_test_realm_update_api
            if UserProfile.notification_setting_types[notification_setting] is bool:
                self.check_for_toggle_param_patch("/json/settings", notification_setting)

    def test_change_notification_sound(self) -> None:
        pattern = "/json/settings"
        param = "notification_sound"
        user_profile = self.example_user("hamlet")
        self.login_user(user_profile)

        json_result = self.client_patch(pattern, {param: "invalid"})
        self.assert_json_error(json_result, "Invalid notification sound 'invalid'")

        json_result = self.client_patch(pattern, {param: "ding"})
        self.assert_json_success(json_result)

        # refetch user_profile object to correctly handle caching
        user_profile = self.example_user("hamlet")
        self.assertEqual(getattr(user_profile, param), "ding")

        json_result = self.client_patch(pattern, {param: "zulip"})

        self.assert_json_success(json_result)
        # refetch user_profile object to correctly handle caching
        user_profile = self.example_user("hamlet")
        self.assertEqual(getattr(user_profile, param), "zulip")

    def test_change_email_batching_period(self) -> None:
        hamlet = self.example_user("hamlet")
        self.login_user(hamlet)

        # Default is two minutes
        self.assertEqual(hamlet.email_notifications_batching_period_seconds, 120)

        result = self.client_patch(
            "/json/settings", {"email_notifications_batching_period_seconds": -1}
        )
        self.assert_json_error(result, "Invalid email batching period: -1 seconds")

        result = self.client_patch(
            "/json/settings", {"email_notifications_batching_period_seconds": 7 * 24 * 60 * 60 + 10}
        )
        self.assert_json_error(result, "Invalid email batching period: 604810 seconds")

        result = self.client_patch(
            "/json/settings", {"email_notifications_batching_period_seconds": 5 * 60}
        )
        self.assert_json_success(result)
        hamlet = self.example_user("hamlet")
        self.assertEqual(hamlet.email_notifications_batching_period_seconds, 300)

    def test_toggling_boolean_user_display_settings(self) -> None:
        """Test updating each boolean setting in UserProfile property_types"""
        boolean_settings = (
            s for s in UserProfile.property_types if UserProfile.property_types[s] is bool
        )
        for display_setting in boolean_settings:
            self.check_for_toggle_param_patch("/json/settings", display_setting)

    def test_wrong_old_password(self) -> None:
        self.login("hamlet")
        result = self.client_patch(
            "/json/settings",
            dict(
                old_password="bad_password",
                new_password="ignored",
            ),
        )
        self.assert_json_error(result, "Wrong password!")

    def test_wrong_old_password_rate_limiter(self) -> None:
        self.login("hamlet")
        with self.settings(RATE_LIMITING_AUTHENTICATE=True):
            add_ratelimit_rule(10, 2, domain="authenticate_by_username")
            start_time = time.time()
            with mock.patch("time.time", return_value=start_time):
                result = self.client_patch(
                    "/json/settings",
                    dict(
                        old_password="bad_password",
                        new_password="ignored",
                    ),
                )
                self.assert_json_error(result, "Wrong password!")
                result = self.client_patch(
                    "/json/settings",
                    dict(
                        old_password="bad_password",
                        new_password="ignored",
                    ),
                )
                self.assert_json_error(result, "Wrong password!")

                # We're over the limit, so we'll get blocked even with the correct password.
                result = self.client_patch(
                    "/json/settings",
                    dict(
                        old_password=initial_password(self.example_email("hamlet")),
                        new_password="ignored",
                    ),
                )
                self.assert_json_error(
                    result, "You're making too many attempts! Try again in 10 seconds."
                )

            # After time passes, we should be able to succeed if we give the correct password.
            with mock.patch("time.time", return_value=start_time + 11):
                json_result = self.client_patch(
                    "/json/settings",
                    dict(
                        old_password=initial_password(self.example_email("hamlet")),
                        new_password="foobar1",
                    ),
                )
                self.assert_json_success(json_result)

            remove_ratelimit_rule(10, 2, domain="authenticate_by_username")

    @override_settings(
        AUTHENTICATION_BACKENDS=(
            "zproject.backends.ZulipLDAPAuthBackend",
            "zproject.backends.EmailAuthBackend",
            "zproject.backends.ZulipDummyBackend",
        )
    )
    def test_change_password_ldap_backend(self) -> None:
        self.init_default_ldap_database()
        ldap_user_attr_map = {"full_name": "cn", "short_name": "sn"}

        self.login("hamlet")

        with self.settings(
            LDAP_APPEND_DOMAIN="zulip.com", AUTH_LDAP_USER_ATTR_MAP=ldap_user_attr_map
        ):
            result = self.client_patch(
                "/json/settings",
                dict(
                    old_password=initial_password(self.example_email("hamlet")),
                    new_password="ignored",
                ),
            )
            self.assert_json_error(result, "Your Zulip password is managed in LDAP")

            result = self.client_patch(
                "/json/settings",
                dict(
                    old_password=self.ldap_password("hamlet"),  # hamlet's password in LDAP
                    new_password="ignored",
                ),
            )
            self.assert_json_error(result, "Your Zulip password is managed in LDAP")

        with self.settings(
            LDAP_APPEND_DOMAIN="example.com", AUTH_LDAP_USER_ATTR_MAP=ldap_user_attr_map
        ), self.assertLogs("zulip.ldap", "DEBUG") as debug_log:
            result = self.client_patch(
                "/json/settings",
                dict(
                    old_password=initial_password(self.example_email("hamlet")),
                    new_password="ignored",
                ),
            )
            self.assert_json_success(result)
            self.assertEqual(
                debug_log.output,
                [
                    "DEBUG:zulip.ldap:ZulipLDAPAuthBackend: Email hamlet@zulip.com does not match LDAP domain example.com."
                ],
            )

        with self.settings(LDAP_APPEND_DOMAIN=None, AUTH_LDAP_USER_ATTR_MAP=ldap_user_attr_map):
            result = self.client_patch(
                "/json/settings",
                dict(
                    old_password=initial_password(self.example_email("hamlet")),
                    new_password="ignored",
                ),
            )
            self.assert_json_error(result, "Your Zulip password is managed in LDAP")

    def do_test_change_user_display_setting(self, setting_name: str) -> None:

        test_changes: Dict[str, Any] = dict(
            default_language="de",
            default_view="all_messages",
            emojiset="google",
            timezone="US/Mountain",
            demote_inactive_streams=2,
            color_scheme=2,
        )

        self.login("hamlet")
        test_value = test_changes.get(setting_name)
        # Error if a setting in UserProfile.property_types does not have test values
        if test_value is None:
            raise AssertionError(f"No test created for {setting_name}")

        if isinstance(test_value, int):
            invalid_value: Any = 100
        else:
            invalid_value = "invalid_" + setting_name

        if setting_name not in ["demote_inactive_streams", "color_scheme"]:
            data = {setting_name: test_value}
        else:
            data = {setting_name: orjson.dumps(test_value).decode()}

        result = self.client_patch("/json/settings", data)
        self.assert_json_success(result)
        user_profile = self.example_user("hamlet")
        self.assertEqual(getattr(user_profile, setting_name), test_value)

        # Test to make sure invalid settings are not accepted
        # and saved in the db.
        if setting_name not in ["demote_inactive_streams", "color_scheme"]:
            data = {setting_name: invalid_value}
        else:
            data = {setting_name: orjson.dumps(invalid_value).decode()}

        result = self.client_patch("/json/settings", data)
        # the json error for multiple word setting names (ex: default_language)
        # displays as 'Invalid language'. Using setting_name.split('_') to format.
        self.assert_json_error(result, f"Invalid {setting_name}")

        user_profile = self.example_user("hamlet")
        self.assertNotEqual(getattr(user_profile, setting_name), invalid_value)

    def test_change_user_display_setting(self) -> None:
        """Test updating each non-boolean setting in UserProfile property_types"""
        user_settings = (
            s for s in UserProfile.property_types if UserProfile.property_types[s] is not bool
        )
        for setting in user_settings:
            self.do_test_change_user_display_setting(setting)
        self.do_test_change_user_display_setting("timezone")

    def do_change_emojiset(self, emojiset: str) -> HttpResponse:
        self.login("hamlet")
        data = {"emojiset": emojiset}
        result = self.client_patch("/json/settings", data)
        return result

    def test_emojiset(self) -> None:
        """Test banned emojisets are not accepted."""
        banned_emojisets = ["apple", "emojione"]
        valid_emojisets = ["google", "google-blob", "text", "twitter"]

        for emojiset in banned_emojisets:
            result = self.do_change_emojiset(emojiset)
            self.assert_json_error(result, "Invalid emojiset")

        for emojiset in valid_emojisets:
            result = self.do_change_emojiset(emojiset)
            self.assert_json_success(result)

    def test_avatar_changes_disabled(self) -> None:
        self.login("hamlet")

        with self.settings(AVATAR_CHANGES_DISABLED=True):
            result = self.client_delete("/json/users/me/avatar")
            self.assert_json_error(result, "Avatar changes are disabled in this organization.", 400)

        with self.settings(AVATAR_CHANGES_DISABLED=True):
            with get_test_image_file("img.png") as fp1:
                result = self.client_post("/json/users/me/avatar", {"f1": fp1})
            self.assert_json_error(result, "Avatar changes are disabled in this organization.", 400)

    def test_invalid_setting_name(self) -> None:
        self.login("hamlet")

        # Now try an invalid setting name
        json_result = self.client_patch("/json/settings", dict(invalid_setting="value"))
        self.assert_json_success(json_result)

        result = orjson.loads(json_result.content)
        self.assertIn("ignored_parameters_unsupported", result)
        self.assertEqual(result["ignored_parameters_unsupported"], ["invalid_setting"])

    def test_changing_setting_using_display_setting_endpoint(self) -> None:
        """
        This test is just for adding coverage for `/settings/display` endpoint which is
        now depreceated.
        """
        self.login("hamlet")

        result = self.client_patch(
            "/json/settings/display", dict(color_scheme=UserProfile.COLOR_SCHEME_NIGHT)
        )
        self.assert_json_success(result)
        hamlet = self.example_user("hamlet")
        self.assertEqual(hamlet.color_scheme, UserProfile.COLOR_SCHEME_NIGHT)

    def test_changing_setting_using_notification_setting_endpoint(self) -> None:
        """
        This test is just for adding coverage for `/settings/notifications` endpoint which is
        now depreceated.
        """
        self.login("hamlet")

        result = self.client_patch(
            "/json/settings/notifications",
            dict(enable_stream_desktop_notifications=orjson.dumps(True).decode()),
        )
        self.assert_json_success(result)
        hamlet = self.example_user("hamlet")
        self.assertEqual(hamlet.enable_stream_desktop_notifications, True)


class UserChangesTest(ZulipTestCase):
    def test_update_api_key(self) -> None:
        user = self.example_user("hamlet")
        email = user.email

        self.login_user(user)
        old_api_keys = get_all_api_keys(user)
        # Ensure the old API keys are in the authentication cache, so
        # that the below logic can test whether we have a cache-flushing bug.
        for api_key in old_api_keys:
            self.assertEqual(get_user_profile_by_api_key(api_key).email, email)

        result = self.client_post("/json/users/me/api_key/regenerate")
        self.assert_json_success(result)
        new_api_key = result.json()["api_key"]
        self.assertNotIn(new_api_key, old_api_keys)
        user = self.example_user("hamlet")
        current_api_keys = get_all_api_keys(user)
        self.assertIn(new_api_key, current_api_keys)

        for api_key in old_api_keys:
            with self.assertRaises(UserProfile.DoesNotExist):
                get_user_profile_by_api_key(api_key)

        for api_key in current_api_keys:
            self.assertEqual(get_user_profile_by_api_key(api_key).email, email)


class UserDraftSettingsTests(ZulipTestCase):
    def test_enable_drafts_syncing(self) -> None:
        hamlet = self.example_user("hamlet")
        hamlet.enable_drafts_synchronization = False
        hamlet.save()
        payload = {"enable_drafts_synchronization": orjson.dumps(True).decode()}
        resp = self.api_patch(hamlet, "/api/v1/settings", payload)
        self.assert_json_success(resp)
        hamlet = self.example_user("hamlet")
        self.assertTrue(hamlet.enable_drafts_synchronization)

    def test_disable_drafts_syncing(self) -> None:
        aaron = self.example_user("aaron")
        self.assertTrue(aaron.enable_drafts_synchronization)

        initial_count = Draft.objects.count()

        # Create some drafts. These should be deleted once aaron disables
        # syncing drafts.
        visible_stream_id = self.get_stream_id(self.get_streams(aaron)[0])
        draft_dicts = [
            {
                "type": "stream",
                "to": [visible_stream_id],
                "topic": "thinking out loud",
                "content": "What if pigs really could fly?",
                "timestamp": 15954790199,
            },
            {
                "type": "private",
                "to": [],
                "topic": "",
                "content": "What if made it possible to sync drafts in Zulip?",
                "timestamp": 1595479020,
            },
        ]
        payload = {"drafts": orjson.dumps(draft_dicts).decode()}
        resp = self.api_post(aaron, "/api/v1/drafts", payload)
        self.assert_json_success(resp)
        self.assertEqual(Draft.objects.count() - initial_count, 2)

        payload = {"enable_drafts_synchronization": orjson.dumps(False).decode()}
        resp = self.api_patch(aaron, "/api/v1/settings", payload)
        self.assert_json_success(resp)
        aaron = self.example_user("aaron")
        self.assertFalse(aaron.enable_drafts_synchronization)
        self.assertEqual(Draft.objects.count() - initial_count, 0)
