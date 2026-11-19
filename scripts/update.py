#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "krakenfx/kraken-cli"
PUBLIC_KEY = "RWQJue8SwPzZBZO8Up5ppAUqm0wM/gK5yjnam+Dbf7KbY0utkiO+7XCd"
ARTIFACTS = {
    "kraken-cli": {"sha256sums": "source.tar.gz"},
    "kraken-cli-bin": {
        "sha256sums_x86_64": "kraken-cli-x86_64-unknown-linux-gnu.tar.gz",
        "sha256sums_aarch64": "kraken-cli-aarch64-unknown-linux-gnu.tar.gz",
    },
}


def validate_version(version):
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError(f"Not a stable release version: {version!r}")
    return version


def download(url, destination):
    request = urllib.request.Request(url, headers={"User-Agent": "aur-kraken-cli"})
    with urllib.request.urlopen(request, timeout=120) as response:
        with destination.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)


def latest_version():
    request = urllib.request.Request(
        f"https://api.github.com/repos/{REPOSITORY}/releases/latest",
        headers={"User-Agent": "aur-kraken-cli", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        release = json.load(response)
    if release["draft"] or release["prerelease"]:
        raise ValueError("Latest release is not stable")
    tag = release["tag_name"]
    if not tag.startswith("v"):
        raise ValueError(f"Unexpected upstream tag: {tag!r}")
    return validate_version(tag[1:])


def verified_hash(version, filename, directory):
    artifact = directory / filename
    url = f"https://github.com/{REPOSITORY}/releases/download/v{version}/{filename}"
    download(url, artifact)
    download(url + ".minisig", directory / (filename + ".minisig"))
    subprocess.run(
        ["minisign", "-Vm", str(artifact), "-P", PUBLIC_KEY], check=True
    )
    with artifact.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def replace_once(pattern, replacement, text):
    result, count = re.subn(pattern, lambda _: replacement, text, flags=re.MULTILINE)
    if count != 1:
        raise ValueError(f"Expected exactly one field matching {pattern!r}")
    return result


def render_recipe(text, version, hashes):
    validate_version(version)
    current = re.search(r"^pkgver=(\S+)$", text, re.MULTILINE)
    if current is None:
        raise ValueError("Missing pkgver")
    previous = validate_version(current[1])
    if tuple(map(int, version.split("."))) < tuple(map(int, previous.split("."))):
        raise ValueError(f"Refusing downgrade from {previous} to {version}")
    result = replace_once(r"^pkgver=\S+$", f"pkgver={version}", text)
    if version != previous:
        result = replace_once(r"^pkgrel=\d+$", "pkgrel=1", result)
    for field, digest in hashes.items():
        if not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError(f"Invalid SHA-256 for {field}")
        result = replace_once(
            rf"^{re.escape(field)}=\('[a-f0-9]{{64}}'\)$",
            f"{field}=('{digest}')", result,
        )
    return result


def update(version, packages, verify_only=False):
    validate_version(version)
    pending = {}
    with tempfile.TemporaryDirectory(prefix="kraken-release-") as temporary:
        for package in packages:
            recipe = ROOT / "packages" / package / "PKGBUILD"
            hashes = {
                field: verified_hash(version, filename, Path(temporary))
                for field, filename in ARTIFACTS[package].items()
            }
            original = recipe.read_text()
            rendered = render_recipe(original, version, hashes)
            if verify_only and original != rendered:
                raise ValueError(f"{package}: recipe differs from signed release {version}")
            pending[recipe] = rendered
    if verify_only:
        return
    metadata = {}
    try:
        originals = {recipe: recipe.read_text() for recipe in pending}
        for recipe, rendered in pending.items():
            recipe.write_text(rendered)
            metadata[recipe.parent / ".SRCINFO"] = subprocess.check_output(
                ["makepkg", "--printsrcinfo"], cwd=recipe.parent, text=True
            )
    except BaseException:
        for recipe, original in originals.items():
            recipe.write_text(original)
        raise
    for path, content in metadata.items():
        path.write_text(content)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", type=validate_version)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--package", choices=ARTIFACTS)
    args = parser.parse_args()
    version = args.version or latest_version()
    packages = [args.package] if args.package else list(ARTIFACTS)
    update(version, packages, args.verify_only)
    print(f"Verified release {version}")
    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a") as stream:
            stream.write(f"version={version}\n")


if __name__ == "__main__":
    main()
