from importlib.metadata import metadata, version

import multicuts


def test_package_is_importable_with_expected_metadata() -> None:
    distribution = metadata("multicuts")

    assert multicuts.__name__ == "multicuts"
    assert distribution["Name"] == "multicuts"
    assert version("multicuts") == "0.0.0"
