import pandas as pd
import pytest

from lakepulse import schema
from lakepulse import variables as V


def _nasa_rows():
    return schema.rows("simcoe_on", "forest_share", ["2010-01-01", "2011-01-01"], [41.0, 40.5])


def test_valid_rows_pass_and_keep_seven_columns():
    df = schema.validate(_nasa_rows())
    assert list(df.columns) == schema.COLUMNS
    assert set(df["tier"]) == {V.TIER_SATELLITE}


def test_model_training_track_rows_sit_beside_nasa_rows():
    track = schema.rows(
        "simcoe_on", "forest_share", ["2010-01-01", "2011-01-01"], [39.0, 39.2],
        source="Model-training track: land-cover classifier v0", tier=V.TIER_ML,
    )
    df = schema.combine(_nasa_rows(), track)
    assert len(df) == 4
    assert df.groupby("source").size().to_dict() == {
        "Model-training track: land-cover classifier v0": 2,
        V.SOURCE_MCD12: 2,
    }


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda d: d.assign(tier="Satellite"), "unknown tier"),
        (lambda d: d.assign(unit="fraction"), "must use unit"),
        (lambda d: d.assign(date="2010-06-01"), "dated 1 January"),
        (lambda d: d.assign(date="2010-01-15"), "first of the month"),
        (lambda d: d.assign(value=120.0), "outside 0–100"),
        (lambda d: d.assign(variable="lake_colour"), "unknown variable"),
        (lambda d: d.assign(value="n/a"), "non-numeric"),
        (lambda d: d.assign(source=""), "empty values"),
        (lambda d: d.assign(extra=1), "unexpected columns"),
        (lambda d: d.drop(columns="tier"), "missing columns"),
        (lambda d: pd.concat([d, d]), "duplicate rows"),
    ],
)
def test_bad_tables_are_rejected(mutate, message):
    with pytest.raises(schema.SchemaError, match=message):
        schema.validate(mutate(_nasa_rows()))


def test_roundtrip_csv(tmp_path):
    p = tmp_path / "t.csv"
    schema.write(_nasa_rows(), p)
    back = schema.read(p)
    assert back["value"].tolist() == [41.0, 40.5]
