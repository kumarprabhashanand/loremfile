# The pinned toolchain image (docs/06 §9).
#
# Only this image's output is authoritative. A host ffmpeg or Pillow produces
# different bytes for media and images, and the manifest lock check will say so.
#
# Build context is the repository root:
#   docker build -f tools/Dockerfile -t loremfile-toolchain .
#
# Built and pushed to ghcr.io/<OWNER>/loremfile-toolchain by .github/workflows/toolchain.yml;
# every other workflow references it by the digest in tools/TOOLCHAIN_DIGEST.

# python 3.12.14, Debian 12.15 "bookworm". Pinned by the multi-arch index digest;
# Dependabot bumps it (docs/09 §4), which is a reviewed PR that also re-pins
# tools/apt-versions.txt and tools/TOOLCHAIN_DIGEST.
FROM python:3.12-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=UTC \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONHASHSEED=0 \
    SOURCE_DATE_EPOCH=1577836800

# Every package is pinned to the exact version in tools/apt-versions.txt.
#
# git and gh are here because every workflow job runs inside this image:
# actions/checkout needs git for a real clone, `build --new` reads
# origin/main:manifest.json, check_lock.sh diffs against the merge-base, and
# gh_issue.py and release.py shell out to gh.
#
# gh comes from GitHub's own apt repository. The keyring it ships is already a
# binary OpenPGP keyring, so it is fetched with curl and used via signed-by=;
# apt verifies it with gpgv (an apt dependency), and gnupg is not installed.
#
# When a pinned version disappears from the mirrors after a Debian point release,
# see the note at the top of tools/apt-versions.txt.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates=20250419~deb12u1 \
        curl=7.88.1-10+deb12u15; \
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        -o /usr/share/keyrings/githubcli-archive-keyring.gpg; \
    chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg; \
    printf 'deb [arch=%s signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main\n' \
        "$(dpkg --print-architecture)" > /etc/apt/sources.list.d/github-cli.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        git=1:2.39.5-0+deb12u3 \
        gh=2.100.0 \
        ffmpeg=7:5.1.9-0+deb12u1 \
        qpdf=11.3.0-1+deb12u1 \
        libavif-bin=0.11.1-1+deb12u1 \
        zstd=1.5.4+dfsg2-5 \
        xz-utils=5.4.1-1+deb12u1 \
        bzip2=1.0.8-5+b1 \
        sqlite3=3.40.1-2+deb12u2 \
        fonts-dejavu-core=2.37-6; \
    rm -rf /var/lib/apt/lists/*

COPY tools/requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock \
    && rm -f /tmp/requirements.lock

# The repository is mounted here by every workflow job and by local development.
WORKDIR /work
