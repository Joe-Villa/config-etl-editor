from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from market_subordination import parse_market_subordination_text  # noqa: E402


class MarketSubordinationAssignOpTests(unittest.TestCase):
    def test_country_block_supports_plain_equals(self) -> None:
        subject_text = """
        DIPLOMACY = {
            c:C22 = {
                create_diplomatic_pact = {
                    country = c:C64
                    type = protectorate
                }
            }
        }
        """
        bloc_text = """
        POWER_BLOCS = {
            c:C12 = {
                create_power_bloc = {
                    identity = identity_trade_league
                    member = c:C14
                }
            }
        }
        """
        rows, own_market = parse_market_subordination_text(
            subject_text=subject_text,
            bloc_text=bloc_text,
        )
        by_tag = {row.tag: row.market_master for row in rows}
        self.assertEqual(by_tag["C64"], "C22")
        self.assertEqual(by_tag["C14"], "C12")
        self.assertEqual(own_market, set())

    def test_country_block_supports_maybe_equals(self) -> None:
        subject_text = """
        DIPLOMACY = {
            c:C22 ?= {
                create_diplomatic_pact = {
                    country ?= c:C64
                    type ?= protectorate
                }
            }
        }
        """
        bloc_text = """
        POWER_BLOCS = {
            c:C12 ?= {
                create_power_bloc ?= {
                    identity ?= identity_trade_league
                    member ?= c:C14
                }
            }
        }
        """
        rows, _ = parse_market_subordination_text(
            subject_text=subject_text,
            bloc_text=bloc_text,
        )
        by_tag = {row.tag: row.market_master for row in rows}
        self.assertEqual(by_tag["C64"], "C22")
        self.assertEqual(by_tag["C14"], "C12")

    def test_custom_subject_types_use_blacklist(self) -> None:
        subject_text = """
        DIPLOMACY = {
            c:C01 = {
                create_diplomatic_pact = { country = c:C59 type = domain }
                create_diplomatic_pact = { country = c:C02 type = duchy }
                create_diplomatic_pact = { country = c:C33 type = rivalry }
            }
        }
        """
        rows, own_market = parse_market_subordination_text(
            subject_text=subject_text,
            bloc_text="POWER_BLOCS = { }",
        )
        by_tag = {row.tag: row.market_master for row in rows}
        self.assertEqual(by_tag["C59"], "C01")
        self.assertEqual(by_tag["C02"], "C01")
        self.assertNotIn("C33", by_tag)
        self.assertEqual(own_market, set())


if __name__ == "__main__":
    unittest.main()
