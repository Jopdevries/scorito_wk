from scorito_wk_odds_optimizer.source_oddschecker import OddscheckerScraper


def test_parse_outrights_uses_structured_participant_and_prices() -> None:
    rows = [
        {
            "participant": "Spain",
            "prices": [
                {"bookmaker": "bet365", "odds": "5.5"},
                {"bookmaker": "Unibet", "odds": "5.75"},
            ],
            "cells": [],
            "bookmakers": [],
            "text": "",
        }
    ]

    parsed = OddscheckerScraper()._parse_outrights(rows)

    assert [(row.country, row.bookmaker, row.odds) for row in parsed] == [
        ("Spain", "bet365", 5.5),
        ("Spain", "Unibet", 5.75),
    ]


def test_parse_outrights_does_not_include_footer_without_participant() -> None:
    rows = [
        {
            "text": "Each-way terms",
            "cells": ["Each-way terms", "2", "1/2"],
            "bookmakers": [],
        }
    ]

    parsed = OddscheckerScraper()._parse_outrights(rows)

    assert all(row.country != "Each-way terms" for row in parsed)
