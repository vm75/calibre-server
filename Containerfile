ARG BASE_IMAGE
FROM ${BASE_IMAGE}
ARG RELEASE_VERSION=development
ARG SOURCE_REVISION=development
ARG UPSTREAM_IMAGE
ARG UPSTREAM_DIGEST
LABEL org.opencontainers.image.title="calibre-server" \
    org.opencontainers.image.description="LinuxServer Calibre with optional remembered browser sessions and unchanged OPDS authentication" \
    org.opencontainers.image.source="https://github.com/vm75/calibre-server" \
    org.opencontainers.image.licenses="GPL-3.0-only" \
    org.opencontainers.image.version="${RELEASE_VERSION}" \
    org.opencontainers.image.revision="${SOURCE_REVISION}" \
    org.opencontainers.image.base.name="${UPSTREAM_IMAGE}" \
    org.opencontainers.image.base.digest="${UPSTREAM_DIGEST}"
COPY LICENSE /opt/calibre-source/patch-LICENSE
COPY src /opt/calibre-source/src
COPY patch_auth.py /tmp/patch_auth.py
COPY remember.py /opt/calibre-source/src/calibre/srv/remember.py
RUN python3 /tmp/patch_auth.py /opt/calibre-source/src && rm /tmp/patch_auth.py \
    && cp -a /opt/calibre/resources /opt/calibre-source/resources
COPY remember-client.js /opt/calibre-source/resources/content-server/remember-client.js
RUN /opt/calibre/calibre-debug -c 'from calibre.constants import numeric_version; import ast; from pathlib import Path; expected = ast.literal_eval(next(x.split("=", 1)[1].strip() for x in Path("/opt/calibre-source/src/calibre/constants.py").read_text().splitlines() if x.startswith("numeric_version ="))); assert numeric_version == expected'
ENV CALIBRE_DEVELOP_FROM=/opt/calibre-source/src
# Keep the binary distribution's compiled web assets and resources.
RUN /opt/calibre/calibre-debug -c 'from calibre.build_forms import build_forms; build_forms("/opt/calibre-source/src", check_icons=False)'
RUN /opt/calibre/calibre-debug -c 'import calibre.srv.auth as a; assert a.__file__.startswith("/opt/calibre-source/"); from calibre.srv.code import index; assert index.auth_required'
