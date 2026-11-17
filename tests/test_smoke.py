import tomllib

import canal
from canal import alerts, budget, dedupe, pipeline, queue, quota, render, youtube


def test_package_imports():
    assert canal is not None
    assert all((alerts, budget, dedupe, pipeline, queue, quota, render, youtube))


def test_example_config_disables_publication():
    with open("config.example.toml", "rb") as config_file:
        config = tomllib.load(config_file)
    assert config["publish_public_enabled"] is False
