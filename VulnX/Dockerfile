# Étape 1 : téléchargement du binaire vulnx depuis les releases GitHub
FROM debian:trixie-slim AS builder

ARG VULNX_VERSION=2.0.1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    wget \
    unzip \
    && rm -rf /var/lib/apt/lists/*

RUN wget -q "https://github.com/projectdiscovery/vulnx/releases/download/v${VULNX_VERSION}/vulnx_${VULNX_VERSION}_linux_amd64.zip" \
    && unzip "vulnx_${VULNX_VERSION}_linux_amd64.zip" vulnx \
    && chmod +x vulnx \
    && rm "vulnx_${VULNX_VERSION}_linux_amd64.zip"

# Étape 2 : image finale Debian Trixie légère
FROM debian:trixie-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /vulnx /usr/local/bin/vulnx

RUN mkdir /output

WORKDIR /output

ENTRYPOINT ["vulnx"]
CMD ["--help"]
