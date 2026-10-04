"""Obtain the pinned manufacturer's libraries locally; never vendor them in Git."""
import argparse
import hashlib
from pathlib import Path, PurePosixPath
import urllib.request
import zipfile

URL = "https://files.waveshare.com/wiki/ESP32-C6-Touch-LCD-1.47/ESP32-C6-Touch-LCD-1.47-Demo.zip"
SHA256 = "ad8e27b172035fb73b5dbe88b821b1ff37bd677c20db294a9da7e5317ee176dd"
LIBRARIES = {"GFX_Library_for_Arduino", "FastIMU", "esp_lcd_touch_axs5106l"}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, help="Use a previously downloaded official archive")
    parser.add_argument("--destination", type=Path, default=Path(".local/vendor/Arduino/libraries"))
    args = parser.parse_args()
    archive = args.archive or Path(".local/vendor/waveshare-demo.zip")
    if not archive.exists():
        if args.archive:
            parser.error("Provided archive does not exist")
        archive.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(URL, timeout=60) as response:
            archive.write_bytes(response.read())
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        parser.error("Archive SHA-256 mismatch; no libraries extracted")
    found = set()
    with zipfile.ZipFile(archive) as bundle:
        entries = []
        for member in bundle.infolist():
            path = PurePosixPath(member.filename)
            parts = path.parts
            if len(parts) < 4 or parts[:2] != ("Arduino", "libraries") or parts[2] not in LIBRARIES:
                continue
            if path.is_absolute() or ".." in parts:
                parser.error("Unsafe archive member; no libraries extracted")
            # Library sources are regular files, never links or device entries.
            mode = member.external_attr >> 16
            if (mode & 0o170000) == 0o120000:
                parser.error("Unexpected symlink; no libraries extracted")
            entries.append((member, parts[2:]))
            found.add(parts[2])
        if found != LIBRARIES:
            parser.error("Required library directories missing; no libraries extracted")
        for member, parts in entries:
            target = args.destination.joinpath(*parts)
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(bundle.read(member))
    print("Verified official archive; prepared local libraries:", ", ".join(sorted(found)))

if __name__ == "__main__":
    main()
