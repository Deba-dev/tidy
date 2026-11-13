"""The updater only ever takes a newer Tidy-Setup.exe from Tidy's own GitHub releases."""
from tidy import updater

URL = "https://github.com/Deba-dev/tidy/releases/download/v%s/Tidy-Setup.exe"


def release(tag, url=None, draft=False, digest=""):
    return {"tag_name": tag, "draft": draft, "html_url": "https://github.com/Deba-dev/tidy/releases/tag/" + tag,
            "body": "# Tidy %s\n\nNew things **here**." % tag,
            "assets": [{"name": "Tidy-Setup.exe", "browser_download_url": url or URL % tag.lstrip("v"),
                        "digest": digest, "url": "https://api.github.com/repos/Deba-dev/tidy/releases/assets/12"}]}


def test_picks_newest_newer_release():
    info = updater.pick_release([release("v0.1.0"), release("v0.3.0"), release("v0.2.5")], current="0.2.0")
    assert info["version"] == "0.3.0" and info["notes"] == "New things here."
    assert info["api_asset"].endswith("/12")


def test_nothing_when_up_to_date_or_draft():
    assert updater.pick_release([release("v0.2.0"), release("v0.1.0")], current="0.2.0") is None
    assert updater.pick_release([release("v9.0.0", draft=True)], current="0.2.0") is None


def test_only_own_release_files():
    assert updater.is_release_asset(URL % "0.3.0")
    for bad in ("http://github.com/Deba-dev/tidy/releases/download/v1/Tidy-Setup.exe",
                "https://github.com/someone/tidy/releases/download/v1/Tidy-Setup.exe",
                "https://evil.com/Deba-dev/tidy/releases/download/v1/Tidy-Setup.exe",
                "https://github.com/Deba-dev/tidy/releases/download/../../x/Tidy-Setup.exe",
                "https://user@github.com/Deba-dev/tidy/releases/download/v1/Tidy-Setup.exe"):
        assert not updater.is_release_asset(bad), bad
    assert updater.pick_release([release("v0.9.0", url="https://evil.com/Tidy-Setup.exe")], current="0.2.0") is None


def test_versions():
    assert updater.parse_version("v0.10.0") > updater.parse_version("0.9.9")
    assert updater.parse_version("1.2") == (1, 2, 0, 0)
