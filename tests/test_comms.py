"""Who may talk to whom is decided in code, not parsed out of free text."""
import pytest

from airdrop_alpha.domain.comms import CommsDenied, INTERPHONE, RADIO, resolve_recipients


def test_all_means_the_crew_and_never_the_sender_or_atc():
    channel, to = resolve_recipients("COMMANDER", ["ALL"])
    assert channel == INTERPHONE and to == ["COPILOT", "NAVIGATOR", "LOADMASTER"]
    assert resolve_recipients("LOADMASTER", "ALL STATIONS")[1] == ["COMMANDER", "COPILOT", "NAVIGATOR"]


def test_comma_lists_and_aliases():
    assert resolve_recipients("NAVIGATOR", "COMMANDER,LOADMASTER")[1] == ["COMMANDER", "LOADMASTER"]
    assert resolve_recipients("COPILOT", ["AC", "lm"])[1] == ["COMMANDER", "LOADMASTER"]
    assert resolve_recipients("COPILOT", ["Alpha Approach"]) == (RADIO, ["ATC"])


@pytest.mark.parametrize("sender", ["COMMANDER", "NAVIGATOR", "LOADMASTER"])
def test_only_copilot_reaches_atc(sender):
    with pytest.raises(CommsDenied) as err:
        resolve_recipients(sender, ["ATC"])
    assert err.value.rule == "atc_via_copilot"


def test_atc_reaches_only_copilot():
    assert resolve_recipients("ATC", ["COPILOT"]) == (RADIO, ["COPILOT"])
    for to in (["COMMANDER"], ["ALL"], ["COPILOT", "COMMANDER"]):
        with pytest.raises(CommsDenied) as err:
            resolve_recipients("ATC", to)
        assert err.value.rule == "atc_radio_only"


def test_radio_and_interphone_do_not_mix():
    with pytest.raises(CommsDenied) as err:
        resolve_recipients("COPILOT", ["ATC", "COMMANDER"])
    assert err.value.rule == "mixed_channels"


def test_unknown_and_self_addressed_messages_are_refused():
    with pytest.raises(CommsDenied) as err:
        resolve_recipients("COPILOT", ["GROUND CREW"])
    assert err.value.rule == "unknown_callsign"
    with pytest.raises(CommsDenied) as err:
        resolve_recipients("COPILOT", ["COPILOT"])
    assert err.value.rule == "no_recipient"
