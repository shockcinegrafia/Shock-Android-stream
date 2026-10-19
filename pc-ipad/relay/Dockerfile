FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN pip install --no-cache-dir cryptography==46.0.3 && mkdir /data && chown 10001:10001 /data
COPY windows/remote.py /app/windows/remote.py
COPY windows/tls_channel.py /app/windows/tls_channel.py
COPY relay/server.py /app/relay/server.py
USER 10001:10001
EXPOSE 8443
ENTRYPOINT ["python", "/app/relay/server.py"]
CMD ["--data", "/data"]
