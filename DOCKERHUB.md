# calibre-server (vm75/calibre-server)

[![Docker Pulls](https://img.shields.io/docker/pulls/vm75/calibre-server)](https://hub.docker.com/r/vm75/calibre-server)
[![Docker Stars](https://img.shields.io/docker/stars/vm75/calibre-server)](https://hub.docker.com/r/vm75/calibre-server)
[![Docker Image Size](https://img.shields.io/docker/image-size/vm75/calibre-server/v9.15.0-ls423)](https://hub.docker.com/r/vm75/calibre-server)
[![GitHub release (latest by date)](https://img.shields.io/github/v/tag/vm75/calibre-server?label=latest%20tag)](https://github.com/vm75/calibre-server/tags)
[![GitHub Workflow Status](https://img.shields.io/github/actions/workflow/status/vm75/calibre-server/publish.yml?label=publish)](https://github.com/vm75/calibre-server/actions/workflows/publish.yml)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-blue.svg)](https://github.com/vm75/calibre-server/blob/main/LICENSE)

LinuxServer Calibre with optional remembered persistent browser sessions. Retains upstream desktop, configuration, and libraries, while preserving HTTP Basic/Digest authentication for OPDS e-reader clients (such as Moon+ Reader, Librera, and KOReader).

Source repository & full documentation: [GitHub: vm75/calibre-server](https://github.com/vm75/calibre-server)

---

## Short Description (for Docker Hub repository summary / overview)

> LinuxServer Calibre with optional persistent remembered browser sessions and OPDS Basic/Digest authentication support.

---

## Overview

Upstream Calibre Content Server requires users to authenticate repeatedly or rely strictly on HTTP Basic authentication when accessed via modern browsers. This image provides a clean patch on top of the official `linuxserver/calibre` image to introduce an optional web-based login form with session management:

- **Session cookie** (expires after 24h or browser exit)
- **30 days persistent cookie**
- **Permanent login** ("Until I sign out", auto-renewing persistent session)
- **OPDS compatibility**: Retains native Basic/Digest authentication on `/opds` for mobile readers without interruption
- **Security & Integrity**: Token hashing, keyed credential fingerprints, CSRF tokens, strict origin validation, rate-limiting & banning integration, and password-change revocation

## Quick Start (Docker Compose)

Use this image as a drop-in replacement for `ghcr.io/linuxserver/calibre` / `linuxserver/calibre`:

```yaml
services:
  calibre-server:
    image: docker.io/vm75/calibre-server:v9.15.0-ls423
    container_name: calibre-server
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=Etc/UTC
      - CALIBRE_REMEMBER_ORIGIN=https://books.example.com
    volumes:
      - /path/to/calibre/config:/config
      - /path/to/calibre/library:/books
    ports:
      - 8080:8080
      - 8081:8081
    restart: unless-stopped
```

> **Note**: Replace `https://books.example.com` with your exact external HTTPS reverse proxy origin. When using reverse proxies (nginx, Caddy, Traefik), ensure the proxy forwards `Host` and `Authorization` headers.

## Available Tags & Versioning

Images are published under the **exact same version tag** as the upstream LinuxServer Calibre image:

- `docker.io/vm75/calibre-server:v9.15.0-ls423`
- `ghcr.io/vm75/calibre-server:v9.15.0-ls423`

There is intentionally no moving `latest` tag; specify the exact upstream version tag or pin an immutable image digest.

## Session Management & Usage

1. Open `/auth/login` in your web browser.
2. Sign in with an existing Calibre user account created in Calibre's Content Server user management.
3. Select your desired session persistence:
   - **This browser session**
   - **30 days**
   - **Until I sign out**
4. Manage or revoke active sessions at `/auth/sessions` or via **Account · sign out**.

For detailed architecture, local builds, security model, and CI/CD release workflow, see the [GitHub repository README](https://github.com/vm75/calibre-server).
