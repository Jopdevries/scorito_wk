from datetime import UTC, datetime

from scorito_wk_odds_optimizer import source_apifootball
from scorito_wk_odds_optimizer.logging_utils import save_json
from scorito_wk_odds_optimizer.schemas import PlayerMetadata


class _Response:
    status_code = 429
    ok = False
    headers = {"Retry-After": "120"}


class _EmptyResponse:
    status_code = 200
    ok = True
    headers = {}

    @staticmethod
    def json():
        return {"response": []}


class _DailyLimitResponse:
    status_code = 200
    ok = True
    headers = {}

    @staticmethod
    def json():
        return {
            "errors": {
                "requests": "You have reached the request limit for the day"
            },
            "response": [],
        }


def test_rate_limit_stops_after_first_request_and_keeps_cache(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("API_FOOTBALL_KEY", "test")
    monkeypatch.setenv("API_FOOTBALL_MAX_REQUESTS", "25")
    cached = PlayerMetadata(
        player="Cached Player",
        country="Test",
        position="FWD",
        position_confidence="HIGH",
        starter_prob=0.9,
        penalty_taker=0,
        set_piece_taker=0,
        minutes_risk="MEDIUM",
        source="api-football",
        notes=source_apifootball.EXACT_MATCH_NOTE,
    )
    save_json(source_apifootball.PARSED_PATH, [cached])
    calls = []

    def fake_get(*args, **kwargs):
        calls.append((args, kwargs))
        return _Response()

    monkeypatch.setattr(source_apifootball.requests, "get", fake_get)

    result = source_apifootball.fetch_api_football_metadata(
        [
            ("Cached Player", "Test"),
            ("Missing One", None),
            ("Missing Two", None),
        ]
    )

    assert len(calls) == 1
    assert [row.player for row in result] == ["Cached Player"]
    status = source_apifootball.load_json(source_apifootball.STATUS_PATH, {})
    assert status["status"] == "RATE_LIMITED"
    assert status["requests_made"] == 1
    assert status["retry_after_at"]


def test_active_rate_limit_cooldown_uses_cache_without_request(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("API_FOOTBALL_KEY", "test")
    save_json(
        source_apifootball.STATUS_PATH,
        {
            "status": "RATE_LIMITED",
            "checked_at": datetime.now(UTC).isoformat(),
        },
    )
    monkeypatch.setattr(
        source_apifootball.requests,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("request should not be made")
        ),
    )

    assert source_apifootball.fetch_api_football_metadata(
        [("Missing", None)]
    ) == []


def test_force_retry_ignores_active_cooldown(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("API_FOOTBALL_KEY", "test")
    save_json(
        source_apifootball.STATUS_PATH,
        {
            "status": "RATE_LIMITED",
            "checked_at": datetime.now(UTC).isoformat(),
        },
    )
    calls = []
    monkeypatch.setattr(
        source_apifootball.requests,
        "get",
        lambda *args, **kwargs: calls.append((args, kwargs)) or _Response(),
    )

    source_apifootball.fetch_api_football_metadata(
        [("Missing", None)],
        force_retry=True,
    )

    assert len(calls) == 1


def test_no_exact_match_is_not_requested_again(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("API_FOOTBALL_KEY", "test")
    calls = []
    monkeypatch.setattr(
        source_apifootball.requests,
        "get",
        lambda *args, **kwargs: calls.append((args, kwargs))
        or _EmptyResponse(),
    )

    source_apifootball.fetch_api_football_metadata([("Missing", None)])
    source_apifootball.fetch_api_football_metadata([("Missing", None)])

    assert len(calls) == 1
    status = source_apifootball.load_json(source_apifootball.STATUS_PATH, {})
    assert status["no_match_players"] == ["Missing"]


def test_daily_limit_payload_is_not_stored_as_no_match(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("API_FOOTBALL_KEY", "test")
    monkeypatch.setattr(
        source_apifootball.requests,
        "get",
        lambda *args, **kwargs: _DailyLimitResponse(),
    )

    source_apifootball.fetch_api_football_metadata([("Player", None)])

    status = source_apifootball.load_json(source_apifootball.STATUS_PATH, {})
    assert status["status"] == "RATE_LIMITED"
    assert status["no_match_players"] == []


def test_best_candidate_requires_exact_normalized_name() -> None:
    candidates = [
        {
            "player": {
                "name": "Lionel Messi Nyamsi",
                "nationality": "Cameroon",
                "position": "Attacker",
            }
        },
        {
            "player": {
                "name": "Lionel Messi",
                "nationality": "Argentina",
                "position": "Attacker",
            }
        },
    ]

    result = source_apifootball._best_candidate(
        candidates,
        "Lionel Messi",
        None,
    )

    assert result is candidates[1]


def test_best_candidate_matches_accents_and_prefers_attacking_position() -> None:
    candidates = [
        {"player": {"name": "Raphinha", "position": "Defender"}},
        {"player": {"name": "Raphinha", "position": "Midfielder"}},
    ]

    result = source_apifootball._best_candidate(
        candidates,
        "Raphinha",
        None,
    )

    assert result is candidates[1]
