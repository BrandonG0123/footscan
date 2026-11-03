"""The iPhone app's privacy manifest (PrivacyInfo.xcprivacy) against what its Swift code actually calls.

The App Store refuses an app that calls a "required reason" API (UserDefaults, file dates, free disk space,
system boot time, the active keyboard) without declaring why in the manifest. These tests read the Swift
sources as text, so they run anywhere (no Xcode), and fail when a new use appears with no declaration, or a
declaration outlives the code that needed it.
"""

import plistlib
import re
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parent.parent / "ios" / "FootscanCapture" / "FootscanCapture"
MANIFEST = APP / "PrivacyInfo.xcprivacy"

# category -> (patterns in Swift source that use it, the reasons that fit how this app uses it).
# The APIs are the ones Apple lists for each category ("Describing use of required reason API").
CATEGORIES = {
    "NSPrivacyAccessedAPICategoryUserDefaults": (
        [r"\b(NS)?UserDefaults\b", r"@AppStorage\b", r"@SceneStorage\b"], {"CA92.1"}),  # the app's own settings
    "NSPrivacyAccessedAPICategoryFileTimestamp": (
        [r"\.creationDate(Key)?\b", r"\.contentModificationDate(Key)?\b", r"\.attributeModificationDate(Key)?\b",
         r"\bmodificationDate\b", r"\bfileModificationDate\b", r"\bNSFile(Creation|Modification)Date\b",
         r"\bNSURL(Creation|ContentModification|AttributeModification)DateKey\b",
         r"\b(f|l)?getattrlist(bulk|at)?\(", r"\b(f|l)?stat(at)?\((?!\s*\"\")"],    # C stat(); not the app's
         {"C617.1"}),                                                            # own stat("label", …) helper
    "NSPrivacyAccessedAPICategoryDiskSpace": (
        [r"volume(Available|Total)Capacity", r"\bNSURLVolume(Available|Total)Capacity", r"\bsystemFreeSize\b",
         r"\bsystemSize\b", r"\bf?statv?fs\("],
        {"E174.1", "85F4.1"}),   # room to write a scan; how much is free, shown when there isn't
    "NSPrivacyAccessedAPICategorySystemBootTime": (
        [r"\bsystemUptime\b", r"\bmach_absolute_time\b"], set()),          # not used: no reason chosen yet
    "NSPrivacyAccessedAPICategoryActiveKeyboards": (
        [r"\bactiveInputModes\b"], set()),
}


def manifest() -> dict:
    with MANIFEST.open("rb") as f:
        return plistlib.load(f)


def strip(text: str) -> str:
    """Swift code without its strings and comments, so only real calls count (a URL's "//" isn't a comment,
    and a comment or a message naming an API isn't a use)."""
    text = re.sub(r'"""[\s\S]*?"""', '""', text)            # multi-line strings
    text = re.sub(r'"(?:\\.|[^"\\\n])*"', '""', text)        # one-line strings
    text = re.sub(r"/\*[\s\S]*?\*/", "", text)                # block comments
    return re.sub(r"//[^\n]*", "", text)


def swift_source() -> str:
    return strip("\n".join(p.read_text() for p in sorted(APP.rglob("*.swift"))))


def declared() -> dict[str, set[str]]:
    return {d["NSPrivacyAccessedAPIType"]: set(d["NSPrivacyAccessedAPITypeReasons"])
            for d in manifest()["NSPrivacyAccessedAPITypes"]}


def used() -> set[str]:
    src = swift_source()
    return {cat for cat, (patterns, _) in CATEGORIES.items() if any(re.search(p, src) for p in patterns)}


def test_the_app_has_a_privacy_manifest_inside_its_own_folder():
    # The Xcode project syncs this folder, so a file here is bundled with the app without a project edit.
    assert MANIFEST.is_file()


def test_the_app_neither_tracks_nor_collects_data():
    m = manifest()
    assert m["NSPrivacyTracking"] is False
    assert m["NSPrivacyTrackingDomains"] == []
    # Scans go only to a studio the person connected; the developer receives nothing.
    assert m["NSPrivacyCollectedDataTypes"] == []


def test_every_required_reason_api_the_code_calls_is_declared():
    missing = used() - set(declared())
    assert not missing, f"Swift code calls these but PrivacyInfo.xcprivacy doesn't declare them: {sorted(missing)}"


def test_nothing_is_declared_that_the_code_no_longer_calls():
    stale = set(declared()) - used()
    assert not stale, f"declared but no longer called (remove from PrivacyInfo.xcprivacy): {sorted(stale)}"


@pytest.mark.parametrize("category", sorted(CATEGORIES))
def test_each_declared_category_gives_the_reason_that_fits_this_app(category):
    reasons = declared().get(category)
    if reasons is None:
        pytest.skip("not used")
    assert reasons and reasons <= CATEGORIES[category][1]


def test_settings_links_a_privacy_policy_that_exists_in_this_repository():
    # Apple needs a privacy policy link inside the app; Settings points at docs/PRIVACY.md on GitHub.
    settings = (APP / "SettingsView.swift").read_text()
    link = re.search(r'privacyPolicy = URL\(string: "https://github\.com/BrandonG0123/footscan/blob/main/([^"]+)"\)',
                     settings)
    assert link, "SettingsView.swift no longer links the privacy policy in this repository"
    policy = APP.parent.parent.parent / link.group(1)
    assert policy.is_file()
    text = policy.read_text()
    assert "not a medical device" in text  # the same first line as everywhere else (docs/SAFETY.md)
    assert "Delete all scans" in text      # tells people how to delete their data, as Apple requires


def test_settings_and_the_privacy_policy_give_the_same_support_page():
    settings = (APP / "SettingsView.swift").read_text()
    support = re.search(r'support = URL\(string: "([^"]+)"\)', settings)
    assert support, "SettingsView.swift no longer has a support link"
    policy = (APP.parent.parent.parent / "docs" / "PRIVACY.md").read_text()
    assert f"]({support.group(1)})" in policy


def test_string_contents_and_comments_are_not_read_as_api_calls():
    src = 'let u = URL(string: "https://x")!; let v = home.resourceValues(forKeys: [.volumeTotalCapacityKey])\n' \
          '/* UserDefaults */ let w = "UserDefaults" // systemUptime'
    assert "volumeTotalCapacityKey" in strip(src)
    assert "UserDefaults" not in strip(src) and "systemUptime" not in strip(src)


def test_the_apps_own_stat_label_helper_is_not_read_as_a_file_date_call():
    # ScanDetailView has a display helper called like stat("Typical error", value); only C's stat(path, …) counts.
    pattern = CATEGORIES["NSPrivacyAccessedAPICategoryFileTimestamp"][0]
    assert not any(re.search(p, strip('stat("Typical error", median)')) for p in pattern)
    assert any(re.search(p, strip("_ = stat(path, &info)")) for p in pattern)
