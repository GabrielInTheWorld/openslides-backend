from tests.system.action.base import BaseActionTestCase


class SpeakerCreateActionTest(BaseActionTestCase):
    def test_create(self) -> None:
        self.set_models(
            {
                "meeting/7844": {"name": "name_asdewqasd"},
                "user/7": {"username": "test_username1"},
                "list_of_speakers/23": {"speaker_ids": [], "meeting_id": 7844},
            }
        )
        response = self.request(
            "speaker.create", {"user_id": 7, "list_of_speakers_id": 23}
        )
        self.assert_status_code(response, 200)
        speaker = self.get_model("speaker/1")
        assert speaker.get("user_id") == 7
        assert speaker.get("list_of_speakers_id") == 23
        assert speaker.get("weight") == 1
        list_of_speakers = self.get_model("list_of_speakers/23")
        assert list_of_speakers.get("speaker_ids") == [1]
        user = self.get_model("user/7")
        assert user.get("speaker_$7844_ids") == [1]
        assert user.get("speaker_$_ids") == ["7844"]

    def test_create_empty_data(self) -> None:
        response = self.request("speaker.create", {})
        self.assert_status_code(response, 400)
        self.assertIn(
            "data must contain ['list_of_speakers_id', 'user_id'] properties",
            response.json["message"],
        )

    def test_create_wrong_field(self) -> None:
        response = self.request("speaker.create", {"wrong_field": "text_AefohteiF8"})
        self.assert_status_code(response, 400)
        self.assertIn(
            "data must contain ['list_of_speakers_id', 'user_id'] properties",
            response.json["message"],
        )

    def test_create_already_exist(self) -> None:
        self.set_models(
            {
                "meeting/7844": {"name": "name_asdewqasd"},
                "user/7": {"username": "test_username1", "speaker_$7844_ids": [42]},
                "list_of_speakers/23": {"speaker_ids": [42], "meeting_id": 7844},
                "speaker/42": {"user_id": 7, "list_of_speakers_id": 23},
            }
        )
        response = self.request(
            "speaker.create", {"user_id": 7, "list_of_speakers_id": 23}
        )
        self.assert_status_code(response, 400)
        list_of_speakers = self.get_model("list_of_speakers/23")
        assert list_of_speakers.get("speaker_ids") == [42]

    def test_create_add_2_speakers_in_1_action(self) -> None:
        self.set_models(
            {
                "meeting/7844": {"name": "name_asdewqasd"},
                "user/7": {"username": "test_username6"},
                "user/8": {"username": "test_username7"},
                "user/9": {"username": "test_username8"},
                "speaker/1": {"user_id": 7, "list_of_speakers_id": 23, "weight": 10000},
                "list_of_speakers/23": {"speaker_ids": [1], "meeting_id": 7844},
            }
        )
        response = self.request_multi(
            "speaker.create",
            [
                {"user_id": 8, "list_of_speakers_id": 23},
                {"user_id": 9, "list_of_speakers_id": 23},
            ],
        )
        self.assert_status_code(response, 400)
        self.assertIn(
            "It is not permitted to create more than one speaker per request!",
            response.json["message"],
        )

    def test_create_add_2_speakers_in_2_actions(self) -> None:
        self.create_model("meeting/7844", {"name": "name_asdewqasd"})
        self.create_model("user/7", {"username": "test_username6"})
        self.create_model("user/8", {"username": "test_username7"})
        self.create_model("user/9", {"username": "test_username8"})
        self.create_model(
            "speaker/1", {"user_id": 7, "list_of_speakers_id": 23, "weight": 10000}
        )
        self.create_model(
            "list_of_speakers/23", {"speaker_ids": [1], "meeting_id": 7844}
        )
        response = self.client.post(
            "/",
            json=[
                {
                    "action": "speaker.create",
                    "data": [
                        {"user_id": 8, "list_of_speakers_id": 23},
                    ],
                },
                {
                    "action": "speaker.create",
                    "data": [
                        {"user_id": 8, "list_of_speakers_id": 23},
                    ],
                },
            ],
        )
        self.assert_status_code(response, 400)
        self.assertIn(
            "Datastore service sends HTTP 400. Model 'user/8' raises MODEL_LOCKED error.",
            response.json["message"],
        )

    def test_create_user_present(self) -> None:
        self.set_models(
            {
                "meeting/7844": {
                    "name": "name_asdewqasd",
                    "list_of_speakers_present_users_only": True,
                },
                "user/9": {
                    "username": "user9",
                    "speaker_$7844_ids": [3],
                    "speaker_$_ids": ["7844"],
                    "is_present_in_meeting_ids": [7844],
                },
                "list_of_speakers/23": {"speaker_ids": [], "meeting_id": 7844},
            }
        )
        response = self.request(
            "speaker.create",
            {
                "user_id": 9,
                "list_of_speakers_id": 23,
            },
        )
        self.assert_status_code(response, 200)
        self.assert_model_exists("speaker/1")

    def test_create_user_not_present(self) -> None:
        self.set_models(
            {
                "meeting/7844": {
                    "name": "name_asdewqasd",
                    "list_of_speakers_present_users_only": True,
                },
                "user/9": {
                    "username": "user9",
                    "speaker_$7844_ids": [3],
                    "speaker_$_ids": ["7844"],
                },
                "list_of_speakers/23": {"speaker_ids": [], "meeting_id": 7844},
            }
        )
        response = self.request(
            "speaker.create",
            {
                "user_id": 9,
                "list_of_speakers_id": 23,
            },
        )
        self.assert_status_code(response, 400)
        self.assert_model_not_exists("speaker/1")
        self.assertIn(
            "Only present users can be on the lists of speakers.",
            response.json["message"],
        )

    def test_create_standard_speaker_in_only_talker_list(self) -> None:
        self.create_model("meeting/7844", {"name": "name_asdewqasd"})
        self.create_model("user/7", {"username": "talking"})
        self.create_model(
            "speaker/1",
            {
                "user_id": 7,
                "list_of_speakers_id": 23,
                "begin_time": 100000,
                "weight": 5,
            },
        )
        self.create_model(
            "list_of_speakers/23", {"speaker_ids": [1], "meeting_id": 7844}
        )
        response = self.client.post(
            "/",
            json=[
                {
                    "action": "speaker.create",
                    "data": [{"user_id": 1, "list_of_speakers_id": 23}],
                }
            ],
        )
        self.assert_status_code(response, 200)
        self.assert_model_exists(
            "speaker/2",
            {"user_id": 1, "weight": 1},
        )
        self.assert_model_exists("list_of_speakers/23", {"speaker_ids": [1, 2]})

    def test_create_standard_speaker_at_the_end_of_filled_list(self) -> None:
        self.create_model("meeting/7844", {"name": "name_asdewqasd"})
        self.create_model("user/7", {"username": "talking"})
        self.create_model("user/8", {"username": "waiting"})
        self.update_model(
            "user/1",
            {
                "speaker_$7844_ids": [3],
                "speaker_$_ids": ["7844"],
            },
        )
        self.create_model(
            "speaker/1",
            {
                "user_id": 7,
                "list_of_speakers_id": 23,
                "begin_time": 100000,
                "weight": 5,
            },
        )
        self.create_model(
            "speaker/2", {"user_id": 8, "list_of_speakers_id": 23, "weight": 1}
        )
        self.create_model(
            "speaker/3",
            {
                "user_id": 1,
                "list_of_speakers_id": 23,
                "point_of_order": True,
                "weight": 2,
            },
        )
        self.create_model(
            "list_of_speakers/23", {"speaker_ids": [1, 2, 3], "meeting_id": 7844}
        )
        response = self.client.post(
            "/",
            json=[
                {
                    "action": "speaker.create",
                    "data": [{"user_id": 1, "list_of_speakers_id": 23}],
                }
            ],
        )
        self.assert_status_code(response, 200)
        self.assert_model_exists(
            "speaker/3",
            {"user_id": 1, "point_of_order": True, "weight": 2},
        )
        self.assert_model_exists(
            "speaker/4",
            {"user_id": 1, "point_of_order": None, "weight": 3},
        )
        self.assert_model_exists("list_of_speakers/23", {"speaker_ids": [1, 2, 3, 4]})
