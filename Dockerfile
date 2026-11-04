FROM python:3.13-alpine

LABEL org.opencontainers.image.title="syncthing-dashboard" \
      org.opencontainers.image.description="One page with topology and sync status of all Syncthing hosts" \
      org.opencontainers.image.licenses="MIT"

RUN adduser -D -H -u 10001 dashboard
WORKDIR /app
COPY syncthing_dashboard/ /app/syncthing_dashboard/

USER dashboard
ENV PYTHONUNBUFFERED=1
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3).status == 200 else 1)"

ENTRYPOINT ["python", "-m", "syncthing_dashboard"]
CMD ["--config", "/config/hosts.toml", "--serve", "8080"]
