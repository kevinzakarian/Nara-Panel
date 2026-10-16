FROM golang:1.27.1-bookworm AS core
RUN apt-get update && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/*
COPY scripts/build-core.sh scripts/build-step.py /
RUN sh /build-core.sh /sing-box

FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends openssl ca-certificates iproute2 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --home-dir /data --shell /usr/sbin/nologin nara
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY --from=core /sing-box /usr/local/bin/sing-box
COPY --from=core /libcronet.so /usr/local/bin/libcronet.so
COPY --from=core /libcronet.LICENSE /usr/local/bin/libcronet.LICENSE
COPY nara ./nara
COPY web ./web
RUN mkdir /data && chown nara:nara /data
ENV NARA_DATA=/data NARA_BIND=0.0.0.0 NARA_PORT=10000 PYTHONDONTWRITEBYTECODE=1
USER nara
EXPOSE 10000 10001
VOLUME ["/data"]
CMD ["python", "-m", "nara", "serve"]
