FROM python:3.12-slim-bookworm AS core
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY scripts/fetch-core.py /fetch-core.py
COPY core-release.json /core-release.json
ARG TARGETARCH
RUN python /fetch-core.py --arch "$TARGETARCH" --output /core

FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends openssl ca-certificates iproute2 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --home-dir /data --shell /usr/sbin/nologin nara
WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --upgrade 'pip>=26.2,<27' \
    && python -m pip install --no-cache-dir -r requirements.txt
COPY --from=core /core/sing-box /usr/local/bin/sing-box
COPY --from=core /core/libcronet.so /usr/local/bin/libcronet.so
COPY --from=core /core/libcronet.LICENSE /usr/local/bin/libcronet.LICENSE
COPY --from=core /core/SING-BOX-LICENSE /core/SING-BOX-COPYING /core/build.json /usr/local/share/nara-core/
COPY nara ./nara
COPY web ./web
RUN mkdir /data && chown nara:nara /data
ENV NARA_DATA=/data NARA_BIND=0.0.0.0 NARA_PORT=10000 PYTHONDONTWRITEBYTECODE=1
USER nara
EXPOSE 10000 10001
VOLUME ["/data"]
CMD ["python", "-m", "nara", "serve"]
