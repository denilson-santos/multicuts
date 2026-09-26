from importlib.metadata import metadata, version

import multicuts


def test_package_is_importable_with_expected_metadata() -> None:
    distribution = metadata("multicuts")
    distribution_version = distribution["Version"]

    assert multicuts.__name__ == "multicuts"
    assert distribution["Name"] == "multicuts"
    assert distribution_version
    assert version("multicuts") == distribution_version
