"""The iPhone app's privacy manifest (PrivacyInfo.xcprivacy) against what its Swift code actually calls.

The App Store refuses an app that calls a "required reason" API (UserDefaults, file dates, free disk space,
system boot time, the active keyboard) without declaring why in the manifest. These tests read the Swift
sources as text, so they run anywhere (no Xcode), and fail when a new use appears with no declaration, or a
declaration outlives the code that needed it.
"""

import functools
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
         r"\b(f|l)?getattrlist(bulk|at)?\(", r"\b(f|l)?stat(at)?\("],               # C stat(), however called
         {"C617.1"}),
    "NSPrivacyAccessedAPICategoryDiskSpace": (
        [r"volume(Available|Total)Capacity", r"\bNSURLVolume(Available|Total)Capacity", r"\bsystemFreeSize\b",
         r"\bsystemSize\b", r"\bf?statv?fs\(", r"\bf?getattrlist(at)?\("],  # getattrlist: both lists, per Apple
        {"E174.1", "85F4.1"}),   # room to write a scan; how much is free, shown when there isn't
    "NSPrivacyAccessedAPICategorySystemBootTime": (
        [r"\bsystemUptime\b", r"\bmach_absolute_time\b"], set()),          # not used: no reason chosen yet
    "NSPrivacyAccessedAPICategoryActiveKeyboards": (
        [r"\bactiveInputModes\b"], set()),
}


@functools.cache
def manifest() -> dict:
    with MANIFEST.open("rb") as f:
        return plistlib.load(f)


HASH_QUOTE = re.compile(r'#+"')   # a raw string's opening: #" or ##" ...
HASH_SLASH = re.compile(r"#+/")   # an extended regex literal's opening: #/ ... /#


def strip(text: str) -> str:
    """Swift code without its strings and comments, so only real calls count (a URL's "//" isn't a comment,
    and a comment or a message naming an API isn't a use). Block comments nest, as in Swift. Extended regex
    literals (``#/.../#``) are skipped whole, so a quote in one doesn't open a string; a bare ``/.../`` regex
    can't be told from division by text alone and is read as code.

    The code inside a string's interpolations, ``"up \\(ProcessInfo.processInfo.systemUptime) s"``, is code and
    is kept (Apple's scan of the built app sees that call); a string inside an interpolation is still a string.
    Raw strings (``#"..."#``, interpolated with ``\\#(...)``) and multi-line ``\"\"\"`` strings too."""
    out: list[str] = []
    i, n = 0, len(text)

    def string(i: int) -> int:
        """Skip the string literal starting at i (its opening #s and quotes); append the code of its
        interpolations to ``out``. -> the index just after it."""
        hashes = 0
        while text[i] == "#":
            hashes, i = hashes + 1, i + 1
        multi = text.startswith('"""', i)
        i += 3 if multi else 1
        close = ('"""' if multi else '"') + "#" * hashes
        interp = "\\" + "#" * hashes + "("
        out.append('""')
        while i < n:
            if text.startswith(close, i):
                return i + len(close)
            if text.startswith(interp, i):
                i = code(i + len(interp), until=")")
                continue
            if hashes == 0 and text[i] == "\\":
                i += 2  # an escape (\\", \\\\, \\n): never the end of the string
                continue
            if not multi and text[i] == "\n":
                return i  # an unterminated one-line string ends at the line's end
            i += 1
        return i

    def block_comment(i: int) -> int:
        """Skip the /* ... */ starting at i, with any /* */ inside it. -> the index just after it."""
        depth = 0
        while i < n:
            if text.startswith("/*", i):
                depth, i = depth + 1, i + 2
            elif text.startswith("*/", i):
                depth, i = depth - 1, i + 2
                if depth == 0:
                    return i
            else:
                i += 1
        return i

    def code(i: int, until: str | None = None) -> int:
        """Copy code from i to ``out``, skipping comments and strings, up to the ``until`` that closes it
        (an interpolation's ")", counting the parentheses inside it). -> the index just after that."""
        depth = 0
        while i < n:
            c = text[i]
            if until and c == until and depth == 0:
                out.append(" ")
                return i + 1
            if text.startswith("//", i):
                j = text.find("\n", i)
                i = n if j < 0 else j
            elif text.startswith("/*", i):
                i = block_comment(i)
            elif c == '"' or (c == "#" and HASH_QUOTE.match(text, i)):
                i = string(i)
            elif c == "#" and (m := HASH_SLASH.match(text, i)):
                close = "/" + "#" * (m.end() - i - 1)
                j = text.find(close, m.end())
                i = n if j < 0 else j + len(close)
            else:
                if c == "(":
                    depth += 1
                elif c == ")":
                    depth -= 1
                out.append(c)
                i += 1
        return i

    code(0)
    return "".join(out)


@functools.cache
def swift_source() -> str:
    return strip("\n".join(p.read_text(encoding="utf-8") for p in sorted(APP.rglob("*.swift"))))


def declared() -> dict[str, set[str]]:  # (manifest() is read once; the sets are new each call)
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
    # exactly the reasons this app needs: one missing (a 85F4.1 for showing the free space, say) would let the
    # upload through this test and fail Apple's review
    assert reasons == CATEGORIES[category][1]


def test_settings_links_a_privacy_policy_that_exists_in_this_repository():
    # Apple needs a privacy policy link inside the app; Settings points at docs/PRIVACY.md on GitHub.
    settings = (APP / "SettingsView.swift").read_text(encoding="utf-8")
    link = re.search(r'privacyPolicy = URL\(string: "https://github\.com/BrandonG0123/footscan/blob/main/([^"]+)"\)',
                     settings)
    assert link, "SettingsView.swift no longer links the privacy policy in this repository"
    policy = APP.parent.parent.parent / link.group(1)
    assert policy.is_file()
    text = policy.read_text(encoding="utf-8")
    assert "not a medical device" in text  # the same first line as everywhere else (docs/SAFETY.md)
    assert "Delete all scans" in text      # tells people how to delete their data, as Apple requires


def test_settings_and_the_privacy_policy_give_the_same_support_page():
    settings = (APP / "SettingsView.swift").read_text(encoding="utf-8")
    support = re.search(r'support = URL\(string: "([^"]+)"\)', settings)
    assert support, "SettingsView.swift no longer has a support link"
    policy = (APP.parent.parent.parent / "docs" / "PRIVACY.md").read_text(encoding="utf-8")
    assert f"]({support.group(1)})" in policy


def test_string_contents_and_comments_are_not_read_as_api_calls():
    src = 'let u = URL(string: "https://x")!; let v = home.resourceValues(forKeys: [.volumeTotalCapacityKey])\n' \
          '/* UserDefaults */ let w = "UserDefaults" // systemUptime'
    assert "volumeTotalCapacityKey" in strip(src)
    assert "UserDefaults" not in strip(src) and "systemUptime" not in strip(src)


def test_api_calls_inside_string_interpolations_count_and_strings_inside_them_dont():
    src = 'let line = "Phone up for \\(Int(ProcessInfo.processInfo.systemUptime)) s"'
    assert "systemUptime" in strip(src)
    assert "systemUptime" not in strip('let t = "\\(f ? "systemUptime" : "")"')  # a string nested in one
    assert "systemUptime" in strip('let t = #"raw \\#(ProcessInfo.processInfo.systemUptime)"#')
    assert "systemUptime" not in strip('let t = #"raw \\(systemUptime)"#')  # not an interpolation in a raw string
    assert "systemUptime" in strip('let t = """\nup \\(ProcessInfo.processInfo.systemUptime)\n"""')
    assert "UserDefaults" not in strip('let t = "a \\"UserDefaults\\" b" // \\(UserDefaults)')
    assert strip('let a = "x"; let b = UserDefaults.standard').endswith("UserDefaults.standard")


def test_no_app_function_is_called_stat_so_the_file_date_check_cant_be_kept_green_by_one():
    """C's stat() reads file dates. The check used to skip calls whose first argument is a string, for a display
    helper of that name, but the helper's own definition still matched, keeping the file-date declaration
    looking needed with no real use. The helper is called statRow now, and every stat( counts."""
    src = swift_source()
    assert not re.search(r"\bfunc\s+(f|l)?stat(at)?\s*\(", src)
    pattern = CATEGORIES["NSPrivacyAccessedAPICategoryFileTimestamp"][0]
    assert any(re.search(p, strip('_ = stat("/tmp/x", &info)')) for p in pattern)
    assert not any(re.search(p, strip('statRow("Typical error", median)')) for p in pattern)


def test_nested_comments_and_regex_literals_hide_nothing_and_show_nothing():
    """Swift's block comments nest, and a quote inside a #/.../# regex isn't a string."""
    assert "UserDefaults" not in strip("/* outer /* inner */ UserDefaults */ let x = 1")
    assert strip("/* a /* b */ c */ let x = 1").strip() == "let x = 1"
    assert "UserDefaults.standard" in strip('let r = #/"x/#; let d = UserDefaults.standard')
    assert "UserDefaults" in strip('let r = ##/a/#b/##; let d = UserDefaults.standard')


def test_getattrlist_counts_as_free_disk_space_too():
    # Apple lists getattrlist and its variants under both file timestamps and disk space
    disk = CATEGORIES["NSPrivacyAccessedAPICategoryDiskSpace"][0]
    assert any(re.search(p, strip("getattrlist(path, &attrs, &buf, size, 0)")) for p in disk)
