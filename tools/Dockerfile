# The pinned toolchain image (docs/06 §9).
#
# Only this image's output is authoritative. A host ffmpeg or Pillow produces
# different bytes for media and images, and the manifest lock check will say so.
#
# Build context is the repository root:
#   docker build -f tools/Dockerfile -t loremfile-toolchain .
#
# Built and pushed to ghcr.io/kumarprabhashanand/loremfile-toolchain by .github/workflows/toolchain.yml;
# every other workflow references it by the digest in tools/TOOLCHAIN_DIGEST.

# python 3.12.14, Debian 12.15 "bookworm". Pinned by the multi-arch index digest;
# Dependabot bumps it (docs/09 §4), which is a reviewed PR that also re-pins
# tools/apt-versions.txt and tools/TOOLCHAIN_DIGEST.
FROM python:3.12-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254

# Links the GHCR package to this repository (docs/09 §1) and is what makes the
# package page show the source, README and licence. toolchain.yml overrides SOURCE_URL
# from the workflow context so it cannot drift; the default keeps local builds correct.
ARG SOURCE_URL="https://github.com/kumarprabhashanand/loremfile"
LABEL org.opencontainers.image.source="${SOURCE_URL}" \
      org.opencontainers.image.description="Pinned toolchain for generating the loremfile.dev fixtures" \
      org.opencontainers.image.licenses="MIT"

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
# gh comes from its GitHub release tarball, pinned by version and by SHA-256 for each
# architecture. GitHub's apt repository keeps only recent versions, so a pinned `gh=` stopped
# resolving (toolchain run on #66, 2026-09-15). tools/smoke.sh checks the installed version.
#
# When a pinned apt version disappears from the mirrors after a Debian point release,
# see the note at the top of tools/apt-versions.txt.
ARG GH_VERSION=2.100.0
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates=20250419~deb12u1 \
        curl=7.88.1-10+deb12u15 \
        git=1:2.39.5-0+deb12u3 \
        ffmpeg=7:5.1.9-0+deb12u1 \
        qpdf=11.3.0-1+deb12u1 \
        libavif-bin=0.11.1-1+deb12u1 \
        zstd=1.5.4+dfsg2-5 \
        xz-utils=5.4.1-1+deb12u1 \
        bzip2=1.0.8-5+b1 \
        sqlite3=3.40.1-2+deb12u2 \
        fonts-dejavu-core=2.37-6; \
    rm -rf /var/lib/apt/lists/*; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in \
        amd64) sha256=e4d4bb4498e8d007abe545b6568926793ace1b6447da598294a610018cb164be ;; \
        arm64) sha256=ea4e7a581a32ccad6cc7923cb1576ac5859ba4b9a16ab22eb8f8a96e78e2e961 ;; \
        *) echo "no pinned gh for $arch" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /tmp/gh.tar.gz \
        "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_${arch}.tar.gz"; \
    echo "${sha256}  /tmp/gh.tar.gz" | sha256sum -c -; \
    tar -xzf /tmp/gh.tar.gz -C /tmp; \
    install -m 0755 "/tmp/gh_${GH_VERSION}_linux_${arch}/bin/gh" /usr/local/bin/gh; \
    rm -rf /tmp/gh.tar.gz "/tmp/gh_${GH_VERSION}_linux_${arch}"; \
    gh --version

COPY tools/requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock \
    && rm -f /tmp/requirements.lock

# The repository is mounted here by every workflow job and by local development.
WORKDIR /work
