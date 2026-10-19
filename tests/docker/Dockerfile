# The Linux environment scripts/test-in-docker.sh runs the suite in, on a laptop: the same
# hardcharger-server binary CI uses (Linux only), the driver library built from source, and
# any Python version through uv. CI runs the same steps on its runner.
FROM ubuntu:24.04
ARG GO_VERSION=1.27.2
ARG UV_VERSION=0.13.1
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      ca-certificates curl git openssh-client build-essential libssl3t64 openssl jq \
    && rm -rf /var/lib/apt/lists/*
RUN arch=$(dpkg --print-architecture) \
    && curl -fsSL "https://go.dev/dl/go${GO_VERSION}.linux-${arch}.tar.gz" | tar -C /usr/local -xz \
    && curl -fsSL "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-$(uname -m)-unknown-linux-gnu.tar.gz" \
       | tar -C /usr/local/bin --strip-components=1 -xz
ENV PATH=/usr/local/go/bin:$PATH
