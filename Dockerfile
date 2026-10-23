FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .
USER 10001:10001
EXPOSE 8768
ENTRYPOINT ["rsna-knee-reader"]
CMD ["serve", "--catalog", "/data/catalog.json", "--data-root", "/data/dicom", "--archives", "/data/archives", "--transport", "http", "--host", "0.0.0.0"]
