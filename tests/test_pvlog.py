"""pvLog: the EPICS PVs an auxiliary-equipment component drives or logs."""

import json

import pytest

import snapwrap.SEEMeta.component as component

# conftest.py reloads the SEEMeta modules before every test, so classes are looked up
# per test (component.pvLog), never bound at import.


def _records():
    """The three Teledyne2 analog-output records."""
    pvLog = component.pvLog
    return (
        pvLog(name="BL3:SE:Teledyne2:PCPressSet", recordType="ao", DESC="Synchronized setpoint", EGU="bar", DRVH=0, DRVL=0),
        pvLog(name="BL3:SE:Teledyne2:MaxFlow", recordType="ao", EGU="ml/min", DRVH=50, DRVL=0),
        pvLog(name="BL3:SE:Teledyne2:BDetPThresh", recordType="ao", DESC="Blowout pressure threshold", EGU="bar", DOL="5.0"),
    )


def test_fields_carry_the_record_values():
    PC_PRESS_SET, MAX_FLOW, BLOWOUT = _records()
    assert (PC_PRESS_SET.recordType, PC_PRESS_SET.DRVH, PC_PRESS_SET.DRVL) == ("ao", 0.0, 0.0)
    assert (MAX_FLOW.DRVH, MAX_FLOW.DRVL, MAX_FLOW.DOL) == (50.0, 0.0, None)
    assert BLOWOUT.DOL == 5.0  # a .db record writes it as a string
    assert str(BLOWOUT) == "BL3:SE:Teledyne2:BDetPThresh"


def test_drive_low_above_drive_high_is_refused():
    with pytest.raises(ValueError, match="DRVL .* is above DRVH"):
        component.pvLog(name="BL3:SE:Teledyne2:MaxFlow", DRVH=10, DRVL=20)


@pytest.mark.parametrize("kwargs,match", [({"name": ""}, "needs a PV name"),
                                          ({"name": "BL3:X", "recordType": "bo"}, "not supported yet"),
                                          ({"name": "BL3:X", "recordType": "ai", "DRVH": 1}, "output fields")])
def test_bad_pvlogs_are_refused(kwargs, match):
    with pytest.raises(ValueError, match=match):
        component.pvLog(**kwargs)


def test_an_input_record_takes_its_units():
    p = component.pvLog(name="BL3:SE:Teledyne1:Pressure", recordType="ai", EGU="bar")
    assert (p.recordType, p.EGU, p.DRVH) == ("ai", "bar", None)


def test_an_integer_output_takes_drive_limits():
    """SITEC's setpoint is a longout."""
    p = component.pvLog(name="BL3:SE:SITEC:SetPressure", recordType="longout", DESC="Set the pressure",
                        DRVL=0, DRVH=10000)
    assert (p.recordType, p.DRVL, p.DRVH) == ("longout", 0.0, 10000.0)


def test_bare_pv_names_still_work():
    """The original form of pvLogs, as scripts/buildSEE.py writes it."""
    pvLog, (_, MAX_FLOW, _) = component.pvLog, _records()
    c = component.pressureController(manufacturer="teledyne", pvLogs=["BL3:SE:Teledyne1:PressSet", MAX_FLOW])
    assert c.pvLogs == [pvLog(name="BL3:SE:Teledyne1:PressSet"), MAX_FLOW]
    assert c.pvLogs[0].recordType is None  # a bare name says nothing about its record


def test_round_trip_through_json():
    PC_PRESS_SET, MAX_FLOW, BLOWOUT = _records()
    c = component.pressureController(manufacturer="teledyne", pvLogs=[PC_PRESS_SET, MAX_FLOW, BLOWOUT])
    payload = json.loads(json.dumps(c.to_dict()))
    assert payload["version"] == 2
    assert payload["pvLogs"][2] == {"name": "BL3:SE:Teledyne2:BDetPThresh", "recordType": "ao",
                                    "DESC": "Blowout pressure threshold", "EGU": "bar",
                                    "DRVH": None, "DRVL": None, "DOL": 5.0}
    back = component.Component.from_dict(payload)
    assert isinstance(back, component.pressureController)
    assert back.pvLogs == [PC_PRESS_SET, MAX_FLOW, BLOWOUT]


def test_version_1_json_with_pv_names_loads():
    old = {"type": "aux.equipment.pressure", "version": 1, "manufacturer": "pace",
           "pvLogs": ["BL3:SE:PACE1:PressSet", "BL3:SE:PACE1:Pressure"]}
    back = component.Component.from_dict(old)
    pvLog = component.pvLog
    assert back.pvLogs == [pvLog(name="BL3:SE:PACE1:PressSet"), pvLog(name="BL3:SE:PACE1:Pressure")]
